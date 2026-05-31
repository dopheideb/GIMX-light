import logging
import serial

logger = logging.getLogger(__name__)

## See GIMX/core/connectors/protocol.h
BYTE_NO_PACKET		= b"\x00"
BYTE_TYPE		= b"\x11"
BYTE_STATUS		= b"\x22"	## Not used anymore.
BYTE_START		= b"\x33"
BYTE_CONTROL_DATA	= b"\x44"
BYTE_RESET		= b"\x55"
BYTE_IDS		= b"\x66"	## Set VID (2 bytes) and PID (2 bytes).
BYTE_VERSION		= b"\x77"
BYTE_BAUDRATE		= b"\x88"
BYTE_DEBUG		= b"\x99"
BYTE_OUT_REPORT		= b"\xEE"
BYTE_IN_REPORT		= b"\xFF"

protocol_byte2string =\
{
    b"\x00": "BYTE_NO_PACKET",
      0x00 : "BYTE_NO_PACKET",

    b"\x11": "BYTE_TYPE",
      0x11 : "BYTE_TYPE",

    b"\x22": "BYTE_STATUS",
      0x22 : "BYTE_STATUS",

    b"\x33": "BYTE_START",
      0x33 : "BYTE_START",

    b"\x44": "BYTE_CONTROL_DATA",
      0x44 : "BYTE_CONTROL_DATA",

    b"\x55": "BYTE_RESET",
      0x55 : "BYTE_RESET",

    b"\x66": "BYTE_IDS",
      0x66 : "BYTE_IDS",

    b"\x77": "BYTE_VERSION",
      0x77 : "BYTE_VERSION",

    b"\x88": "BYTE_BAUDRATE",
      0x88 : "BYTE_BAUDRATE",

    b"\x99": "BYTE_DEBUG",
      0x99 : "BYTE_DEBUG",

    b"\xEE": "BYTE_OUT_REPORT",
      0xEE : "BYTE_OUT_REPORT",

    b"\xFF": "BYTE_IN_REPORT",
      0xFF : "BYTE_IN_REPORT",
}

## GIMX/core/controller.c
DEFAULT_BAUDRATE	= 500000



class SerialAdapter:
    def __init__(self, serial: serial):
        self.serial = serial
        self.serial.baudrate = DEFAULT_BAUDRATE
        self.serial.timeout  = None



    def get_next_type(self):
        while True:
            type = self.serial.read(1)
            if type != BYTE_DEBUG:
                ## This is a regular type.
                break

            ## This is a debug packet.
            length = self.serial.read(1)[0]
            message = self.serial.read(length)
            logger.debug(message)

        return type



    def get_baud_rate(self):
        reply = self.send_command_and_wait_for_reply(command=BYTE_BAUDRATE)
        length = len(reply)
        assert length == 1, f"Reply to get baud rate request must be 1 byte long, not {length:#04x}."
        return reply



    def get_type(self):
        reply = self.send_command_and_wait_for_reply(command=BYTE_TYPE)
        length = len(reply)
        assert length == 1, f"Reply to get type request must be 1 byte long, not {length:#04x}."
        return reply



    def get_version(self):
        reply = self.send_command_and_wait_for_reply(command=BYTE_VERSION)
        length = len(reply)
        assert length == 2, f"Reply to get version request must be 2 bytes long, not {length:#04x}."
        return reply



    def reset(self):
        logger.debug(f"Sending RESET ({BYTE_RESET[0]:#04x}) command.")
        self.serial.write(BYTE_RESET + b'\x00')
        logger.debug(f"Sending RESET ({BYTE_RESET[0]:#04x}) command done.")



    def start(self):
        logger.debug(f"Sending START ({BYTE_START[0]:#04x}) command.")
        self.serial.write(BYTE_START + b'\x00')
        logger.debug(f"Sending START ({BYTE_START[0]:#04x}) command done.")

        type = self.get_next_type()
        assert type == BYTE_START, 'Reply to get start request must start with 0x33, not {:#04x}'.format(type[0])

        length = self.serial.read(1)
        assert length == b'\x01', 'Reply to get start request must be 1 byte long'

        payload = self.serial.read(1)
        assert payload == b'\x00'



    ## Data to and from endpoint 0 is called control data in the USB 
    ## standard(s).
    def send_control_data(self, control_data: bytes):
        report_len = len(control_data)

        header = BYTE_CONTROL_DATA + bytes([report_len])
        packet = header + control_data
        self.serial.write(packet)



    def send_input_report(self, input_report: bytes):
        report_len = len(input_report)

        header = BYTE_IN_REPORT + bytes([report_len])
        packet = header + input_report
        self.serial.write(packet)



    def send_command_and_wait_for_reply(self, command: bytes, data: bytes=bytes(0), tries: int=1, timeout=None):
        old_timeout = self.serial.timeout
        self.serial.timeout = timeout
        for n in range(tries):
            logger.debug(f"Sending command {command[0]:#04x} ({protocol_byte2string[command]}).")
            self.serial.write(command + len(data).to_bytes() + data)
            logger.debug(f"Sending command {command[0]:#04x} ({protocol_byte2string[command]}) done.")

            type = self.serial.read(1)
            if type == b"":
                ## Timeout occured.
                continue
            assert type == command, f"Reply to {protocol_byte2string[command]} must start with {command[0]:#04x}, not {type[0]:#04x}."

            ## The GIMX adapter replied!
            break
        self.serial.timeout = old_timeout

        if type == b"":
            raise TimeoutError(f"Could not get a reply after trying {tries} time(s).")

        length = self.serial.read(1)[0]
        reply = self.serial.read(length)
        return reply



    def wait_online(self):
        self.send_command_and_wait_for_reply(command=BYTE_VERSION, tries=10, timeout=0.1)
