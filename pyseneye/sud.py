import usb.core, usb.util
import json, struct, bitstruct, sys, threading, time
from abc import ABC
from array import array
from enum import Enum

#used to identify the undelying USB device
VENDOR_ID=9463
PRODUCT_ID=8708


# Based on the structs from Seneye sample C++ code
# https://github.com/seneye/SUDDriver/blob/master/Cpp/sud_data.h

# little-endian
ENDIAN = "<"

# [unused], Kelvin, x, y, Par, Lux, PUR
B_LIGHTMETER = "11s3i2IB"

# Flags, [unused], PH, NH3, Temp, [unused]
SUDREADING_VALUES = "4Hi13s" + B_LIGHTMETER

# Header, cmd, Timestamp
SUDREADING = ENDIAN + "2sI" + SUDREADING_VALUES + "c"

# Header, cmd, IsKelvin
SUDLIGHTMETER = ENDIAN + "2s?" + B_LIGHTMETER + "29s"

# These are not specified as a struct, in the original C++ source
RESPONSE = ENDIAN + "2s?"
GENERIC_RESPONSE = RESPONSE + "61s"
HELLOSUD_RESPONSE = RESPONSE + "BH58s"


# WIP - Decoding the flags
# [unused], InWater, SlideNotFitted, SlideExpired, StateT, StatePH, StateNH3, Error, IsKelvin, [unused], PH, NH3, Temperature, [unused]
SUDREADING_FLAGS = "u2b1b1b1u2u2u2b1b1u3" 

class Command(Enum):

    SENSOR_READING = 0
    ENTER_INTERACTIVE_MODE = 1
    LEAVE_INTERACTIVE_MODE = 2
    LIGHT_READING = 3


class DeviceType(Enum):

    HOME = 0
    POND = 1
    REEF = 3


class BaseResponse(ABC):
    
    def __init__(self, raw_data, read_def):

        parsed_values = struct.unpack(read_def.parse_str, raw_data)
        length = len(parsed_values)
        expected_values = read_def.return_values.split(",")

        if length != len(expected_values):
            raise ValueError("Returned parameter number doesn't match expected return parameter number")

        for i in range(0, length):

            setattr(self, "_{0}".format(expected_values[i]), parsed_values[i])

    @property
    def validation_bytes(self):

        return self._validation_bytes


class Response(BaseResponse):

    def __init__(self, raw_data, read_def):

        self._ack = False

        super().__init__(raw_data, read_def)


    @property
    def ack(self):

        return self._ack


class EnterInteractiveResponse(Response):

    def __init__(self, raw_data, read_def):
        self._device_type = None
        self._version = 0

        super().__init__(raw_data, read_def)

    @property
    def device_type(self):

        if self._device_type is None:
            return None

        return DeviceType(self._device_type)

    @property
    def version(self):

        v = self._version

        major = int(v / 10000)
        minor = int((v / 100) % 100)
        rev = v % 100

        return "{0}.{1}.{2}".format(major, minor, rev)


class SensorReadingResponse(BaseResponse):

    def __init__(self, raw_data, read_def):
        
        self._timestamp = 0
        self._ph = 0
        self._nh3 = 0
        self._temperature = 0
        self._flags = None
        self._is_kelvin = False
        self._kelvin = 0
        self._kelvin_x = 0
        self._kelvin_y = 0
        self._par = 0
        self._lux = 0
        self._pur = 0

        super().__init__(raw_data, read_def)

    @property
    def is_light_reading(self):
        return self._validation_bytes == COMMAND_DEFINITIONS[Command.LIGHT_READING].reading_definitions[0].validator

    @property
    def is_kelvin(self):

        if is_light_reading:
            return self._is_kelvin
        else:
            #Need to read this from flags, not implemented yet
            return None 

    @property
    def timestamp(self):
        return self._timestamp

    @property
    def ph(self):
        return self._ph/100

    @property
    def nh3(self):
        return self._nh3/1000

    @property
    def temperature(self):
        return self._temperature/1000

    @property
    def flags(self):
        return self._flags

    @property
    def kelvin(self):
        return self._kelvin

    @property
    def kelvin_x(self):
        return self._kelvin_x

    @property
    def kelvin_y(self):
        return self._kelvin_y

    @property
    def par(self):
        return self._par

    @property
    def lux(self):
        return self._lux

    @property
    def pur(self):
        return self._pur


class CommandDefinition:

    def __init__(self, cmd_str, rdefs):

        self._cmd_str = cmd_str
        self._rdefs = rdefs

    @property
    def cmd_str(self):

        return self._cmd_str

    @property
    def read_definitions(self):

        return self._rdefs


class ReadDefinition:

    def __init__(self, parse_str, validator, return_values, return_type):

        self._validator = validator
        self._parse_str = parse_str
        self._return_values = return_values
        self._return_type = return_type

    @property
    def validator(self):

        return self._validator

    @property
    def parse_str(self):

        return self._parse_str

    @property
    def return_values(self):

        return self._return_values

    @property
    def return_type(self):

        return self._return_type

LIGHT_SENSOR_SUB_VALUES = ",kelvin,kelvin_x,kelvin_y,par,lux,pur,unused"
SENSOR_RETURN_VALUES = "validation_bytes,timestamp,flags,unused,ph,nh3,temperature,unused,unused" + LIGHT_SENSOR_SUB_VALUES
LIGHT_SENSOR_RETURN_VALUES = "validation_bytes,is_kelvin,unused" + LIGHT_SENSOR_SUB_VALUES
HELLOSUD_RETURN_VALUES = "validation_bytes,ack,device_type,version,unused"
GENERIC_RETURN_VALUES = "validation_bytes,ack,unused"

COMMAND_DEFINITIONS = {
        Command.SENSOR_READING: CommandDefinition("READING", [
            ReadDefinition(
                GENERIC_RESPONSE, 
                array('B', [0x88,0x02]),
                GENERIC_RETURN_VALUES,
                Response), 
            ReadDefinition(
                SUDREADING, 
                array('B', [0x00, 0x01]),
                SENSOR_RETURN_VALUES,
                SensorReadingResponse)
            ]),

        Command.LIGHT_READING: CommandDefinition(None, [
            ReadDefinition(
                SUDLIGHTMETER, 
                array('B', [0x00, 0x02]),
                LIGHT_SENSOR_RETURN_VALUES,
                SensorReadingResponse)
            ]),
        
        Command.ENTER_INTERACTIVE_MODE: CommandDefinition("HELLOSUD", [
            ReadDefinition(
                HELLOSUD_RESPONSE, 
                array('B', [0x88, 0x01]),
                HELLOSUD_RETURN_VALUES,
                EnterInteractiveResponse)
            ]),

        Command.LEAVE_INTERACTIVE_MODE: CommandDefinition("BYESUD", [
            ReadDefinition(
                GENERIC_RESPONSE, 
                array('B', [0x77, 0x01]), # Differs from documented response
                GENERIC_RETURN_VALUES,
                Response)
            ])
        }


class SUDevice:

    def __init__(self):
        
        dev = usb.core.find(idVendor=VENDOR_ID, idProduct=PRODUCT_ID)

        if dev is None:
            raise ValueError('Device not found')

        if dev.is_kernel_driver_active(0):
            dev.detach_kernel_driver(0)

        dev.set_configuration()
        usb.util.claim_interface(dev, 0)
        cfg = dev.get_active_configuration()
        intf = cfg[(0,0)]
        
        self._instance = dev

        ep_in = usb.util.find_descriptor(
                intf,
                custom_match = \
                lambda e: \
                    usb.util.endpoint_direction(e.bEndpointAddress) == \
                    usb.util.ENDPOINT_IN)

        assert ep_in is not None
        self._ep_in = ep_in

        ep_out = usb.util.find_descriptor(
                intf,
                custom_match = \
                lambda e: \
                    usb.util.endpoint_direction(e.bEndpointAddress) == \
                    usb.util.ENDPOINT_OUT)

        assert ep_out is not None
        self._ep_out = ep_out


    def _write(self, msg):

        return self._instance.write(self._ep_out, msg)


    def _read(self, packet_size = None):
        
        if packet_size is None:
            packet_size = self._ep_in.wMaxPacketSize

        return self._instance.read(self._ep_in, packet_size)


    def action(self, cmd, timeout = 10000):

        cdef = COMMAND_DEFINITIONS[cmd]
        
        if cdef.cmd_str is not None:
            self._write(cdef.cmd_str)
        
        start = time.time()

        # Preserve data and rdef, to generate the return value
        data = None
        rdef = None


        for rdef in cdef.read_definitions:
            
            if __debug__:
                print("validator: {0}".format(rdef.validator))

            # Re-set while, if there are multiple read defs
            data = None 
            
            while not data:
                try:
                    r = self._read()
                    
                    if __debug__:
                        print("Validation bytes: {0}".format(r[0:2]))
                
                    if r[0:2] == rdef.validator:
                        data = r
                        
                        if __debug__:
                            print("Result: {0}".format(data))
                except:
                    pass
            
                if ((time.time() - start) * 1000) > timeout:
                    raise TimeoutError("Operation timed out reading response.")

        return rdef.return_type(data, rdef)


    def close(self):
        
        # re-attach kernel driver
        usb.util.release_interface(self._instance, 0)
        self._instance.attach_kernel_driver(0)
        
        # clean up
        usb.util.release_interface(self._instance, 0)
        usb.util.dispose_resources(self._instance)
        self._instance.reset()

