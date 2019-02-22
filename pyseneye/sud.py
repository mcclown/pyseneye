import usb.core, usb.util
import json, struct, bitstruct, sys, threading, time

VENDOR_ID=9463
PRODUCT_ID=8708

#Structs from Seneye sample C++ code
#https://github.com/seneye/SUDDriver/blob/master/Cpp/sud_data.h

ENDIAN = "<"

#[unused], Kelvin, x, y, Par, Lux, PUR
B_LIGHTMETER = "8s3i2IBc"

#Flags (1&2), [reserved], PH, NH3, T, [reserved] 
SUDREADING_VALUES = "4Hi16s" + B_LIGHTMETER

#Timestamp
SUDREADING = ENDIAN + "2sI" + SUDREADING_VALUES
#struct.unpack("<2cI4Hi16s8s3i2IBc", s)

#IsKelvin
SUDLIGHTMETER = ENDIAN + "2sI" + B_LIGHTMETER

#This isn't specified as a struct but it is required
#Header, Command, ACK
WRITE_RESPONSE = "2B?"

#[unused], InWater, SlideNotFitted, SlideExpired, StateT, StatePH, StateNH3, 
#Error, IsKelvin, [unused], PH, NH3, Temperature, [unused]
SUDREADING_FLAGS = "u2b1b1b1u2u2u2b1b1u3" 


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


    @property
    def instance(self):
        
        return self._instance


    def write(self, msg):

        return self.instance.write(self._ep_out, msg)


    def read(self, packet_size = None):
        
        if packet_size is None:
            packet_size = self._ep_in.wMaxPacketSize

        return self.instance.read(self._ep_in, packet_size)

    def open(self):

        self.write("HELLOSUD")
        r = self.read()
        print(r)

    def close(self):
        
        self.write("BYESUD")
        r = self.read()
        print(r)

        # re-attach kernel driver
        usb.util.release_interface(self.instance, 0)
        self.instance.attach_kernel_driver(0)
        
        # clean up
        usb.util.release_interface(self.instance, 0)
        usb.util.dispose_resources(self.instance)
        self.instance.reset()


    def get_light_reading(self):

        return self.read()


    def get_sensor_reading(self, timeout = 10000):

        self.write("READING")
        result = None
        
        start = time.time()

        while not result:
            try:
                r = self.read()
                if r[1] != 2:
                    result = r
            except:
                pass
            
            if ((time.time() - start) * 1000) > timeout:
                return None

        return SUDData(r)


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




class SUDMonitor:

    def __init__(self, device):
    
        self._cmd = None
        self._stop = True

        self._device = device


    def monitor_thread(self):

        while not self._stop:

            try:
                if self._cmd:
                    self._device.write(self._cmd)
                    self._cmd = None

                print(self._device.read())
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



