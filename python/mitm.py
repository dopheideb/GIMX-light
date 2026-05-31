#!/usr/bin/env python3

import array
import cProfile
import GIMX
import logging
import pstats
import serial
import socket
import time
import usb	## PyUSB



serial_port = '/dev/ttyUSB0'
udp_port = 1337



## Set up logging.
logformat = '%(asctime)s - %(name)s - %(levelname)-5s - %(message)s'
formatter = logging.Formatter(logformat)
handler = logging.StreamHandler()
handler.setLevel(logging.DEBUG)
handler.setFormatter(formatter)

def enable_module_logging(module_name, level=logging.DEBUG):
    module_logger = logging.getLogger(module_name)
    module_logger.setLevel(level)
    module_logger.addHandler(handler)
    return module_logger

logger = enable_module_logging(__name__)
enable_module_logging('GIMX')



product_ids = [
  0x028e,
  0x028f,
]
## Find and use the Xbox360 controller.
for pid in product_ids:
    devices = usb.core.find(find_all=True, idVendor=0x045e, idProduct=pid)
    for dev in devices:
        if dev is not None:
            serial_bytes = usb.util.get_string(dev, dev.iSerialNumber).encode()
            ## 1008366 is the serial of the GIMX adapter.
            if serial_bytes != b"1008366":
                break
if dev is None:
    raise ValueError('No Xbox 360 controller found.')
logger.debug('Xbox 360 controller found.')

logger.debug('Resetting the actual Xbox 360 controller. This clears the stall condition.')
dev.reset()
for cfg in dev:
    for intf in cfg:
        is_kernel_driver_active = dev.is_kernel_driver_active(intf.bInterfaceNumber)
        if is_kernel_driver_active:
            logger.debug('Detaching Xbox360 controller from kernel driver.')
            dev.detach_kernel_driver(intf.bInterfaceNumber)

logger.debug('Requesting Xbox360 controller to set the only configuration it has.')
dev.set_configuration()
for cfg in dev:
    for intf in cfg:
        logger.debug('Claiming Xbox360 interface {:d}.'.format(intf.bInterfaceNumber))
        usb.util.claim_interface(dev, intf)

logger.debug('Configured serial port: {:s}'.format(serial_port))
serial_adapter = serial.Serial(port=serial_port)

logger.debug('Connecting to the GIMX adapter via serial.')
gimx_adapter = GIMX.SerialAdapter(serial=serial_adapter)

gimx_adapter__type = gimx_adapter.get_type()
logger.debug(f'GIMX adapter type: {gimx_adapter__type[0]:#04x}')

gimx_adapter__version = gimx_adapter.get_version()
logger.debug(f'GIMX adapter version: {gimx_adapter__version[0]}.{gimx_adapter__version[1]}')

logger.debug('Baud rate: {:d}'.format(gimx_adapter.get_baud_rate()[0] * 100000))

logger.debug('Resetting GIMX adapter.')
gimx_adapter.reset()

logger.debug('Waiting for the GIMX adapter to complete the reset.')
gimx_adapter.wait_online()

gimx_adapter.start()



ip=''
address=(ip, udp_port)
## Note: AF_INET6 is capable of dual stack (at least on Linux), so it 
## will respond to IPv4 addresses like 127.0.0.1 too.
sock = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
sock.bind(address)
sock.setblocking(0)



def handle_incoming_serial():
    if gimx_adapter.serial.in_waiting == 0:
        ## No data available, so we have nothing to do.
        return
    #logger.debug('Serial data: {:d} byte(s) awaiting!'.format(gimx_adapter.serial.in_waiting))

    type_and_size = gimx_adapter.serial.read(2)
    type = type_and_size[0]
    size = type_and_size[1]

    try:
        type_str = GIMX.protocol_byte2string[type]
    except KeyError:
        type_str = 'UNKNOWN'
        pass

    ## Race condition: it can happen that we are called when serial data 
    ## is pouring in, i.e. we haven't received all serial data yet.
    tries = 1000
    while tries > 0:
        tries -= 1
        bytes_missing = size - gimx_adapter.serial.in_waiting

        ## Note: we can also have a surplus of data, i.e. the next 
        ## serial packet is already arriving. Hence don't test for equal 
        ## to 0 only.
        if bytes_missing <= 0:
            break

        logger.debug('Not enough serial data yet. Still needing {:d} bytes'.format(bytes_missing))
        time.sleep(0.001)
    assert gimx_adapter.serial.in_waiting >= size
    data = gimx_adapter.serial.read(size)
    logger.debug(f"[SERIAL] Data received. type={type:#04x} size={size:#04x} type_str={type_str}, data={data.hex(':')}")

    if type == GIMX.BYTE_CONTROL_DATA[0]:
        timeout_ms = 1000
        bmRequestType = data[0]
        bRequest      = data[1]
        wValue        = data[2] + (data[3] << 8)
        wIndex        = data[4] + (data[5] << 8)
        wLength       = data[6] + (data[7] << 8)
        payload       = data[8:]

        if bmRequestType & 0x80 == 0x80:
            ## Device-to-host. Ask for wLength bytes.
            data_or_wLength = wLength
        else:
            ## Host-to-device. Payload is the data to send to device.
            data_or_wLength = payload

        ## The return value is a byte array (not a byte string).
        answer = None

        try:
            logger.debug(f'CTRL transfer: bmRequestType={bmRequestType:02x}h')
            logger.debug(f'CTRL transfer: bRequest     ={bRequest:02x}h')
            answer = dev.ctrl_transfer(
                bmRequestType=bmRequestType,
                bRequest=bRequest,
                wValue=wValue,
                wIndex=wIndex,
                data_or_wLength=data_or_wLength,
                timeout=timeout_ms
            )
        except usb.core.USBError as e:
            logger.debug('USBError: {:s}'.format(str(e)))

            if str(e) == '[Errno 32] Pipe error':
                ## Linux USB errno 32 means "STALL".
                logger.debug('STALL received from Xbox 360 controller...')
                raise
            else:
                raise

        if bmRequestType & 0x80 == 0x80:
            ## Device-to-host. Return the received answer.
            logger.debug('[SERIAL] Answer from actual Xbox 360 controller: {:s}'.format(answer.tobytes().hex(sep=' ')))
            gimx_adapter.send_control_data(answer.tobytes())
        else:
            ## Host-to-device. No need to send back anything to the GIMX 
            ## adapter.
            logger.debug('[SERIAL] Number of bytes send to Xbox360 controller: {:d}'.format(answer))
            pass
    elif type == GIMX.BYTE_BAUDRATE:
        pass
    elif type == GIMX.BYTE_OUT_REPORT[0]:
        ep = 0x01
        timeout_ms = 10
        dev.write(endpoint=ep, data=data, timeout=timeout_ms)
    else:
        raise NotImplementedError



def handle_usb_endpoint(timeout_ms=1):
    try:
        data = dev.read(endpoint=0x81, size_or_buffer=0x20, timeout=timeout_ms)
    except usb.core.USBTimeoutError:
        pass
    else:
        logger.debug('[USB EP] Xbox 360 controller says: ' + data.tobytes().hex(':'))
        gimx_adapter.send_input_report(data.tobytes())



def main():
    ## The Xbox360 controller is a high-speed device (12Mbps). The 
    ## endpoint which actually reports buttons/triggers/thumbsticks, is 
    ## endpoint 0x01. Endpoint 0x01 reports bInterval 4. That means it 
    ## wants to be polled every 4 ms or faster.
    ## 
    ## If it was a high-speed device, the calculation would have been: 
    ## 2^(4-1) * 125 us = 2^3 * 125 us = 8 * 125 us = 1 ms.
    poll_frequency_ms = 4

    allow_input_from_controller = True
    while True:
        #profile = cProfile.Profile()
        #profile.enable()

        ## Checking for serial data is very cheap.
        handle_incoming_serial()

        if allow_input_from_controller:
            handle_usb_endpoint(timeout_ms=poll_frequency_ms)

        try:
            ## A UDP datagram/message is at most 64KiB. If we ask for 
            ## less, any pending data is silently discarded.
            data, addr = sock.recvfrom(64 * 1024)
            logger.debug('UDP connection from: {:s}'.format(str(addr)))
            logger.debug('UDP data: {:s}'.format(data.hex(sep=' ')))

            if len(data) == 1:
                allow_input_from_controller = (data != b'\x00')
                logger.debug('Allow input from controller {:s}'.format(str(allow_input_from_controller)))
            elif len(data) == 20:
                gimx_adapter.send_input_report(data)
            else:
                raise NotImplementedError("I don't know how to handle {:d} number of bytes.".format(len(data)))
        except BlockingIOError:
            pass

        #profile.disable()
        #ps = pstats.Stats(profile)
        #ps.sort_stats('cumtime', 'calls')
        #ps.print_stats(40)



if __name__ == '__main__':
    main()
