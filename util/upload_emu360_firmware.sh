#!/bin/bash

declare -r COMMENT=''
PORTNAME=''
DEFAULT_PORTNAME='/dev/ttyACM0'
case "${1}" in
	--help)
		echo "$0 [portname]"
		exit 0
		;;
	*)
		PORTNAME="${1}"
		;;
esac
: ${PORTNAME:=${DEFAULT_PORTNAME}}

read -p "Reset the Arduino Leonardo since we need to talk to the bootloader. Press Enter, or CTRL+C to abort. "
if [ ! -e "${PORTNAME}" ]
then
	echo "Portname ${PORTNAME@Q} does not exist." 1>&2
	exit 1
fi
NUM_TRIES_MAX=10
NUM_TRIES=0
while [ ${NUM_TRIES} -le ${NUM_TRIES_MAX} ]
do
	if [ -w "${PORTNAME}" ]
	then
		break
	fi
	echo "Portname ${PORTNAME@Q} is not (yet?) writable." 1>&2
	let ++NUM_TRIES
	sleep 0.2
done

avrdude\
	${COMMENT:+partno}\
	-p atmega32u4\
	${COMMENT:+programmer-id}\
	-c avr109\
	${COMMENT:+portname}\
	-P /dev/ttyACM0\
	${COMMENT:+Disable auto erase for flash.}\
	-D\
	${COMMENT:+memtype:op:filename:filefmt}\
	-U flash:w:EMU360.hex:i
