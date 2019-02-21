import usb.core, usb.util
import json, bitstruct, sys, threading

VENDOR_ID=9463
PRODUCT_ID=8708

#Structs from Seneye sample C++ code
#https://github.com/seneye/SUDDriver/blob/master/Cpp/sud_data.h

#[unused], Kelvin, x, y, Par, Lux, PUR
B_LIGHTMETER = "u64s32s32s32u32u32u8"

#[unused], InWater, SlideNotFitted, SlideExpired, StateT, StatePH, StateNH3, 
#Error, IsKelvin, [unused], PH, NH3, Temperature, [unused]
SUDREADING_VALUES = "u2b1b1b1u2u2u2b1b1u3u16u16s32u128" + B_LIGHTMETER

#Timestamp
SUDREADING = "u32" + SUDREADING_VALUES

#IsKelvin
SUDLIGHTMETER = "b1" + B_LIGHTMETER

#This isn't specified as a struct but it is required
#Header, Command, ACK
WRITE_RESPONSE = "u8u8b8"


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


    def close(self):
        # re-attach kernel driver
        usb.util.release_interface(self.instance, 0)
        self.instance.attach_kernel_driver(0)
        
        # clean up
        usb.util.release_interface(self.instance, 0)
        usb.util.dispose_resources(self.instance)
        self.instance.reset()     


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



