#
#   Copyright 2019 Stephen Mc Gowan <mcclown@gmail.com>
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.

"""*pyseneye.sud* implements the HID interface for the Seneye USB devices."""

import time
import struct
from abc import ABC
from array import array
from enum import Enum

import usb.core
import usb.util
from usb.core import USBError

# used to identify the undelying USB device
VENDOR_ID = 9463
PRODUCT_ID = 8708


# Based on the structs from Seneye sample C++ code
# https://github.com/seneye/SUDDriver/blob/master/Cpp/sud_data.h

# little-endian
ENDIAN = "<"

# [unused], Kelvin, x, y, Par, Lux, PUR
B_LIGHTMETER = "11s3i2IB"

# Flags, [unused], PH, NH3, Temp, [unused]
SUDREADING_VALUES = "2s3Hi13s" + B_LIGHTMETER

# Header, cmd, Timestamp
SUDREADING = ENDIAN + "2sI" + SUDREADING_VALUES + "c"

# Header, cmd, IsKelvin
SUDLIGHTMETER = ENDIAN + "2s?" + B_LIGHTMETER + "29s"

# These are not specified as a struct, in the original C++ source
RESPONSE = ENDIAN + "2s?"
GENERIC_RESPONSE = RESPONSE + "61s"
HELLOSUD_RESPONSE = RESPONSE + "BH58s"


# Decoding the flags, currently unused
# [unused], InWater, SlideNotFitted, SlideExpired, StateT, StatePH, StateNH3,
# Error, IsKelvin, [unused], PH, NH3, Temperature, [unused]
SUDREADING_FLAGS = "u2b1b1b1u2u2u2b1b1u3"


# Return values expected for each read type
LIGHT_SENSOR_SUB_VALUES = ",kelvin,kelvin_x,kelvin_y,par,lux,pur,unused"
SENSOR_RETURN_VALUES = "validation_bytes,timestamp,flags,unused,ph,nh3," + \
        "temperature,unused,unused" + LIGHT_SENSOR_SUB_VALUES
LIGHT_SENSOR_RETURN_VALUES = "validation_bytes,is_kelvin,unused" + \
        LIGHT_SENSOR_SUB_VALUES
HELLOSUD_RETURN_VALUES = "validation_bytes,ack,device_type,version,unused"
GENERIC_RETURN_VALUES = "validation_bytes,ack,unused"


class Action(Enum):
    """Actions that can be passed to SUDevice.action()."""

    SENSOR_READING = 0
    ENTER_INTERACTIVE_MODE = 1
    LEAVE_INTERACTIVE_MODE = 2
    LIGHT_READING = 3


class DeviceType(Enum):
    """Differnent type of sensor devices."""

    HOME = 0
    POND = 1
    REEF = 3


class BaseResponse(ABC):  # pylint:disable=R0903
    """Abstract class for the SUD responses."""

    def __init__(self, raw_data, read_def):
        """Initialise response, parse data and populate instant attributes.

        :param raw_data: raw binary data, containing response data
        :param read_def: the definition of the expected data
        :type raw_data: array('B', [64])
        :type read_def: ReadDefinition
        """
        parsed_values = struct.unpack(read_def.parse_str, raw_data)
        length = len(parsed_values)
        expected_values = read_def.return_values.split(",")

        if length != len(expected_values):
            raise ValueError("Returned parameter number doesn't match " +
                             "expected return parameter number")

        # Loop through received data and populate specified instance variables
        for i in range(0, length):

            setattr(self, "_{0}".format(expected_values[i]), parsed_values[i])

        # Change the format of this, because it isn't being parsed correctly.
        self._validation_bytes = raw_data[0:2]

    @property
    def validation_bytes(self):
        """Bytes that are used to validate the message is correct.

        :returns: bytes used for validation
        :rtype: array('B', [2])
        """
        return self._validation_bytes


class Response(BaseResponse):
    """Response object, includes ACK status."""

    def __init__(self, raw_data, read_def):
        """Initialise response object, including an ACK attribute.

        :param raw_data: raw binary data, containing response data
        :param read_def: the definition of the expected data
        :type raw_data: array('B', [64])
        :type read_def: ReadDefinition
        """
        self._ack = False

        super().__init__(raw_data, read_def)

    @property
    def ack(self):
        """Acknowledgment result.

        :returns: True was process successfully, False if not
        :rtype: bool
        """
        return self._ack


class EnterInteractiveResponse(Response):
    """Received when entering interactive mode. Contains device metadata."""

    def __init__(self, raw_data, read_def):
        """Initialise enter interactive mode response.

        Includes device type and version.

        :param raw_data: raw binary data, containing response data
        :param read_def: the definition of the expected data
        :type raw_data: array('B', [64])
        :type read_def: ReadDefinition
        """
        self._device_type = None
        self._version = 0

        super().__init__(raw_data, read_def)

    @property
    def device_type(self):
        """Get the device type.

        :returns: the device type
        :rtype: DeviceType
        """
        if self._device_type is None:
            return None

        return DeviceType(self._device_type)

    @property
    def version(self):
        """Firmware version of the device.

        :returns: the version
        :rtype: str
        """
        ver = self._version

        major = int(ver / 10000)
        minor = int((ver / 100) % 100)
        rev = ver % 100

        return "{0}.{1}.{2}".format(major, minor, rev)


class SensorReadingResponse(BaseResponse):
    """Response which contains all sensor data."""

    # pylint: disable=too-many-instance-attributes
    # All attributes are required. I will try to break this up later.

    def __init__(self, raw_data, read_def):
        """Initialise sensor reading response, also populate sensor data.

        :param raw_data: raw binary data, containing response data
        :param read_def: the definition of the expected data
        :type raw_data: array('B', [64])
        :type read_def: ReadDefinition
        """
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
        """Is the sensor reading a light reading.

        :returns: True if a light reading, False if a sensor reading.
        :rtype: bool
        """
        rdef = ACTION_DEFINITIONS[Action.LIGHT_READING].read_definitions[0]

        return self._validation_bytes == rdef.validator

    @property
    def is_kelvin(self):
        """Is light reading on kelvin line: https://tinyurl.com/yy2wtaz5.

        :returns: True if on kelvin line, False if not
        :rtype: bool
        """
        if self.is_light_reading:
            return self._is_kelvin

        # Need to read this from flags, not implemented yet
        return None

    @property
    def timestamp(self):
        """Time the reading was taken at.

        (only available for sensor readings)

        :returns: Unix epoch time
        :rtype: float
        """
        return self._timestamp

    @property
    def ph(self):  # pylint:disable=C0103
        """PH reading from the device.

        :returns: the PH value
        :rtype: float
        """
        return self._ph/100

    @property
    def nh3(self):
        """NH3 reading from the device.

        :returns: the NH3 value
        :rtype: float
        """
        return self._nh3/1000

    @property
    def temperature(self):
        """Temperature reading from the device.

        :returns: the temperature
        :rtype: float
        """
        return self._temperature/1000

    @property
    def flags(self):
        """Raw flags information. Not usable yet.

        :returns: the raw flags bytes
        :rtype: array('B', [2])
        """
        return self._flags

    @property
    def kelvin(self):
        """Kelvin value of the light reading.

        :returns: the kelvin value
        :rtype: int
        """
        return self._kelvin

    @property
    def kelvin_x(self):
        """X co-ordinate on the CIE colourspace https://tinyurl.com/yy2wtaz5.

        Limited to colors that are near the kelvin line. Check with is_kelvin.

        :returns: X co-ordinate
        :rtype: int
        """
        return self._kelvin_x

    @property
    def kelvin_y(self):
        """Y co-ordinate on the CIE colourspace https://tinyurl.com/yy2wtaz5.

        Limited to colors that are near the kelvin line. Check with is_kelvin.

        :returns: Y co-ordinate
        :rtype: int
        """
        return self._kelvin_y

    @property
    def par(self):
        """PAR value for light reading.

        :returns: PAR value
        :rtype: int
        """
        return self._par

    @property
    def lux(self):
        """LUX value for light reading.

        :returns: LUX value
        :rtype: int
        """
        return self._lux

    @property
    def pur(self):
        """PUR value for light reading.

        :returns: PUR value
        :rtype: int
        """
        return self._pur


class ActionDefinition:
    """Definition for action and expected responses."""

    def __init__(self, cmd_str, rdefs):
        """Initialise action definition.

        :param cmd_str: the command string, to send to the device.
        :param rdefs: the definition of the expected responses
        :type cmd_str: str
        :type rdefs: ReadDefinition[]
        """
        self._cmd_str = cmd_str
        self._rdefs = rdefs

    @property
    def cmd_str(self):
        """Command string to write to the device.

        :returns: command string
        :rtype: str
        """
        return self._cmd_str

    @property
    def read_definitions(self):
        """Read definition for expected response.

        :returns: the read definitions
        :rtype: ReadDefinition[]
        """
        return self._rdefs


class ReadDefinition:
    """Definition of expected response, including validation and parsing."""

    def __init__(self, parse_str, validator, return_values, return_type):
        """Initialise read definition of expected response.

        :param parse_str: format string, with structure of raw response data
        :param validator: bytes that can be used to validate response
        :param return_values: the names and order of expected return values
        (comma separated list)
        :param return_type: BaseResponse subclass that represents the response
        :type parse_str: str
        :type validator: array('B', [2])
        :type return_values: str
        :type return_type: BaseResponse subclass
        """
        self._validator = validator
        self._parse_str = parse_str
        self._return_values = return_values
        self._return_type = return_type

    @property
    def validator(self):
        """Bytes that are used for validation of expected read.

        :returns: validation bytes
        :rtype: array('B', [2])
        """
        return self._validator

    @property
    def parse_str(self):
        """Parse string, as struct format string.

        :returns: format string
        :rtype: str
        """
        return self._parse_str

    @property
    def return_values(self):
        """Comma separate list of expected return value names.

        :returns: comma separated list
        :rtype: str
        """
        return self._return_values

    @property
    def return_type(self):
        """Subclass of BaseResponse, the expected response object.

        :returns: expected response object
        :rtype: BaseResponse subclass
        """
        return self._return_type


# Concrete definitions of all actions we can take..
ACTION_DEFINITIONS = {
        Action.SENSOR_READING: ActionDefinition("READING", [
            ReadDefinition(
                GENERIC_RESPONSE,
                array('B', [0x88, 0x02]),
                GENERIC_RETURN_VALUES,
                Response),
            ReadDefinition(
                SUDREADING,
                array('B', [0x00, 0x01]),
                SENSOR_RETURN_VALUES,
                SensorReadingResponse)
            ]),

        Action.LIGHT_READING: ActionDefinition(None, [
            ReadDefinition(
                SUDLIGHTMETER,
                array('B', [0x00, 0x02]),
                LIGHT_SENSOR_RETURN_VALUES,
                SensorReadingResponse)
            ]),

        Action.ENTER_INTERACTIVE_MODE: ActionDefinition("HELLOSUD", [
            ReadDefinition(
                HELLOSUD_RESPONSE,
                array('B', [0x88, 0x01]),
                HELLOSUD_RETURN_VALUES,
                EnterInteractiveResponse)
            ]),

        Action.LEAVE_INTERACTIVE_MODE: ActionDefinition("BYESUD", [
            ReadDefinition(
                GENERIC_RESPONSE,
                array('B', [0x77, 0x01]),  # Differs from documented response
                GENERIC_RETURN_VALUES,
                Response)
            ])
        }


class SUDevice:
    """Encapsulates a Seneye USB Device and it's capabilities."""

    def __init__(self):
        """Initialise and open connection to Seneye USB Device.

        Allowing for actions to be processed by the Seneye device.

        ..  note:: When finished SUDevice.close() should be called, to
            free the USB device, otherwise subsequent calls may fail.

        ..  note:: Device will need to be in interactive mode, before taking
            any readings. Send Action.ENTER_INTERACTIVE_MODE to do this.
            Devices can be left in interactive mode but readings will not be
            cached to be sent to the Seneye.me cloud service later.

        :raises ValueError: If USB device not found.
        :raises usb.core.USBError: If permissions or communications error
        occur while trying to connect to USB device.

        :Example:
            >>> from pyseneye.sud import SUDevice, Action
            >>> d.action(Action.ENTER_INTERACTIVE_MODE)
            >>> s = d.action(Action.SENSOR_READING)
            >>> s.ph
            8.16
            >>> s.nh3
            0.007
            >>> s.temperature
            25.125
            >>> d.action(Action.LEAVE_INTERACTIVE_MODE)
            >>> d.close()
        """
        dev = usb.core.find(idVendor=VENDOR_ID, idProduct=PRODUCT_ID)

        if dev is None:
            raise ValueError('Device not found')

        if dev.is_kernel_driver_active(0):
            dev.detach_kernel_driver(0)

        dev.set_configuration()
        usb.util.claim_interface(dev, 0)
        cfg = dev.get_active_configuration()
        intf = cfg[(0, 0)]

        self._instance = dev

        ep_in = usb.util.find_descriptor(
            intf,
            custom_match=lambda e:
            usb.util.endpoint_direction(e.bEndpointAddress) ==
            usb.util.ENDPOINT_IN)

        assert ep_in is not None
        self._ep_in = ep_in

        ep_out = usb.util.find_descriptor(
            intf,
            custom_match=lambda e:
            usb.util.endpoint_direction(e.bEndpointAddress) ==
            usb.util.ENDPOINT_OUT)

        assert ep_out is not None
        self._ep_out = ep_out

    def _write(self, msg):

        return self._instance.write(self._ep_out, msg)

    def _read(self, packet_size=None):

        if packet_size is None:
            packet_size = self._ep_in.wMaxPacketSize

        return self._instance.read(self._ep_in, packet_size)

    def action(self, cmd, timeout=10000):
        """Perform action on device.

        The available actions are specified by the Action Enum. These actions
        can include a single write to the device and potentially multiple
        reads.

        :raises usb.core.USBError: If having issues connecting to the USB
        :raises TimeoutError: If read operation times out

        :param cmd: Action to action
        :param timeout:  timeout in milliseconds
        :type cmd: Action
        :type timeout: int
        """
        cdef = ACTION_DEFINITIONS[cmd]

        if cdef.cmd_str is not None:
            self._write(cdef.cmd_str)

        start = time.time()

        # Preserve data and rdef, to generate the return value
        data = None
        rdef = None

        for rdef in cdef.read_definitions:

            # Re-set while, if there are multiple read defs
            data = None

            while not data:
                try:
                    resp = self._read()

                    if resp[0:2] == rdef.validator:
                        data = resp

                except USBError:
                    pass

                if ((time.time() - start) * 1000) > timeout:
                    raise TimeoutError("Operation timed out reading response.")

        return rdef.return_type(data, rdef)

    def close(self):
        """Close connection to USB device and clean up instance."""
        # re-attach kernel driver
        usb.util.release_interface(self._instance, 0)
        self._instance.attach_kernel_driver(0)

        # clean up
        usb.util.release_interface(self._instance, 0)
        usb.util.dispose_resources(self._instance)
        self._instance.reset()
