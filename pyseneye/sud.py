import usb.core, usb.util
import json, struct, bitstruct, sys, threading, time
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



class SUDData:

    def __init__(self, raw_data):

        cmd, ts, flags, unused, ph, nh3, t, *unused = struct.unpack(SUDREADING, raw_data)

        self._ts = ts
        self._ph = ph/100
        self._nh3 = nh3/1000
        self._t = t/1000
        self._flags = flags

    @property
    def timestamp(self):
        return self._ts

    @property
    def ph(self):
        return self._ph

    @property
    def nh3(self):
        return self._nh3

    @property
    def temperature(self):
        return self._t

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

    def __init__(self, parse_str, validator):

        self._validator = validator
        self._parse_str = parse_str

    @property
    def validator(self):

        return self._validator

    @property
    def parse_str(self):

        return self._parse_str


class Command(Enum):

    READING = 0
    OPEN = 1
    CLOSE = 2
    LIGHT_READING = 3


COMMAND_DEFINITIONS = {
        Command.READING: CommandDefinition("READING", [ReadDefinition(GENERIC_RESPONSE, b'\x88\x02'), ReadDefinition(SUDREADING, b'\x00\x01')]),
        Command.OPEN: CommandDefinition("HELLOSUD", [ReadDefinition(HELLOSUD_RESPONSE, b'\x88\x01')]),
        Command.CLOSE: CommandDefinition("BYESUD", [ReadDefinition(GENERIC_RESPONSE, b'\x88\x05')]),
        Command.LIGHT_READING: CommandDefinition(None, [ReadDefinition(SUDLIGHTMETER, b'\x00\x02')])
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
                
                    if r[0:2].tostring() == rdef.validator:
                        result = r
                        
                        if __debug__:
                            print("Result: {0}".format(r))
                except:
                    pass
            
                if ((time.time() - start) * 1000) > timeout:
                    
                    if __debug__:
                        print("Operation timed out")

                    return None

        return result


    def get_sensor_reading(self, timeout = 10000):
        
        r = self.get_data(Command.READING, timeout)

        if r is None:
            return None
        
        return SUDData(r)


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



