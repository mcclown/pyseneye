import usb.core, usb.util
import json, struct, bitstruct, sys, threading, time
from abc import ABC, abstractmethod
from array import array
from enum import Enum

#used to identify the undelying USB device
VENDOR_ID=9463
PRODUCT_ID=8708

#Structs from Seneye sample C++ code
#https://github.com/seneye/SUDDriver/blob/master/Cpp/sud_data.h

ENDIAN = "<"

#[unused], Kelvin, x, y, Par, Lux, PUR, [unused]
B_LIGHTMETER = "8s3i2IBc"

#Flags, [unused], PH, NH3, Temp, [unused] 
SUDREADING_VALUES = "4Hi16s" + B_LIGHTMETER

#Header, cmd, Timestamp
SUDREADING = ENDIAN + "2sI" + SUDREADING_VALUES

#Header, cmd, IsKelvin
SUDLIGHTMETER = ENDIAN + "2sI" + B_LIGHTMETER


#These aren't specified as a struct but I'm treating them as if they were
#Header, Cmd, ACK
RESPONSE = ENDIAN + "2s?"

GENERIC_RESPONSE = RESPONSE + "61s"

HELLOSUD_RESPONSE = RESPONSE + "BH58s"


# WIP - Decoding the flags
#[unused], InWater, SlideNotFitted, SlideExpired, StateT, StatePH, StateNH3, 
#Error, IsKelvin, [unused], PH, NH3, Temperature, [unused]
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
            raise ValueError("Returned data length doesn't match expected data length")

        for i in range(0, length):

            setattr(self, "_{0}".format(expected_values[i]), parsed_values[i])

    @property
    def validation_bytes(self):

        return self._validation_bytes


class InteractiveModeResponse(BaseResponse):

    def __init__(self, raw_data, read_def):

        self._ack = False

        super().__init__(raw_data, read_def)


    @property
    def ack(self):

        return self._ack


class EnterInteractiveResponse(InteractiveModeResponse):

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

        super().__init__(raw_data, read_def)

    @property
    def is_light_reading(self):
        return self._validation_bytes == COMMAND_DEFINITIONS[Command.LIGHT_READING].reading_definitions[0].validator

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

    def __init__(self, parse_str, validator, return_values):

        self._validator = validator
        self._parse_str = parse_str
        self._return_values = return_values

    @property
    def validator(self):

        return self._validator

    @property
    def parse_str(self):

        return self._parse_str

    @property
    def return_values(self):

        return self._return_values

SENSOR_RETURN_VALUES = "validation_bytes,timestamp,flags,unused,ph,nh3,temperature,unused,unused,kelvin,kelvin_x,kelvin_y,par,lux,pur,unused"
HELLOSUD_RETURN_VALUES = "validation_bytes,ack,device_type,version,unused"
GENERIC_RETURN_VALUES = "validation_bytes,ack,unused"

COMMAND_DEFINITIONS = {
        Command.SENSOR_READING: CommandDefinition("READING", [
            ReadDefinition(
                GENERIC_RESPONSE, 
                array('B', [0x88,0x02]),
                GENERIC_RETURN_VALUES), 
            ReadDefinition(
                SUDREADING, 
                array('B', [0x00, 0x01]),
                SENSOR_RETURN_VALUES)
            ]),

        Command.LIGHT_READING: CommandDefinition(None, [
            ReadDefinition(
                SUDLIGHTMETER, 
                array('B', [0x00, 0x02]),
                SENSOR_RETURN_VALUES)
            ]),
        
        Command.ENTER_INTERACTIVE_MODE: CommandDefinition("HELLOSUD", [
            ReadDefinition(
                HELLOSUD_RESPONSE, 
                array('B', [0x88, 0x01]),
                HELLOSUD_RETURN_VALUES)
            ]),

        Command.LEAVE_INTERACTIVE_MODE: CommandDefinition("BYESUD", [
            ReadDefinition(
                GENERIC_RESPONSE, 
                array('B', [0x77, 0x01]), # Differs from documented response
                GENERIC_RETURN_VALUES)
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


    def close(self):
        
        # re-attach kernel driver
        usb.util.release_interface(self._instance, 0)
        self._instance.attach_kernel_driver(0)
        
        # clean up
        usb.util.release_interface(self._instance, 0)
        usb.util.dispose_resources(self._instance)
        self._instance.reset()


    def get_data(self, cmd, timeout = 10000):

        d = COMMAND_DEFINITIONS[cmd]
        
        # TODO Operation can timeout here, need to add sme error handling
        if d.cmd_str is not None:
            self._write(d.cmd_str)
        
        start = time.time()

        for rdef in d.read_definitions:
            
            if __debug__:
                print("validator: {0}".format(rdef.validator))

            result = None
            
            while not result:
                try:
                    r = self._read()
                    
                    if __debug__:
                        print("Validation bytes: {0}".format(r[0:2]))
                
                    if r[0:2] == rdef.validator:
                        result = r
                        
                        if __debug__:
                            print("Result: {0}".format(r))
                except:
                    pass
            
                if ((time.time() - start) * 1000) > timeout:
                    
                    if __debug__:
                        print("Operation timed out")

                    return None

        # TODO Add validation of result and add internal flag for interactive/non-interactive mode

        return result


class SUDMonitor:

    def __init__(self, device):
    
        self._cmd = None
        self._stop = True

        self._device = device


    def monitor_thread(self):

        while not self._stop:

            try:
                if self._cmd:
                    self._device._write(self._cmd)
                    self._cmd = None

                print(self._device._read())
            except:
                pass


    def run(self):

        self._stop = False

        t = threading.Thread(target=self.monitor_thread)
        t.start()

        while not self._stop:
            cmd = input("cmd (r|h|b|q):")

            if cmd == "r":
                self._cmd = "READING"
            elif cmd == "h":
                self._cmd = "HELLOSUD"
            elif cmd == "b":
                self._cmd = "BYESUD"
            elif cmd == "q":
                self._stop = True



