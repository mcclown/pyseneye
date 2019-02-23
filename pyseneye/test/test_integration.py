import py.test
import time
from unittest.mock import Mock, patch

from pyseneye.sud import SUDevice, Command, DeviceType, Response, EnterInteractiveResponse, SensorReadingResponse

# Requires a device plugged in, currently. 

def init_device():

    time.sleep(5)
    
    d = SUDevice()
    r = d.action(Command.ENTER_INTERACTIVE_MODE)
    return d, r
    


def test_SUDevice_enter_interactive_mode():

    d, r = init_device()
    assert r.__class__ == EnterInteractiveResponse
    assert r.ack == True
    assert r.device_type == DeviceType.REEF
    assert r.version != None
    assert r.version != ""

    d.close()


def test_SUDevice_leave_interactive_mode():

    d, r = init_device()
    assert r.ack == True
    
    r = d.action(Command.LEAVE_INTERACTIVE_MODE)
    assert r.ack == True
    assert r.__class__ == Response

    d.close()


def test_SUDevice_get_light_reading():

    d, r = init_device()
    assert r.ack == True

    r = d.action(Command.LIGHT_READING)
    assert r.__class__ == SensorReadingResponse
    assert r.flags == None
    assert r.is_light_reading == True
    assert r.ph == 0.0
    assert r.nh3 == 0.0
    assert r.temperature == 0.0
    assert r.kelvin != None
    assert r.kelvin_x != None
    assert r.kelvin_y != None
    assert r.par != None
    assert r.lux != None
    assert r.pur != None

    d.close()


def test_SUDevice_get_sensor_reading():

    d, r = init_device()
    assert r.ack == True

    r = d.action(Command.SENSOR_READING)
    assert r.__class__ == SensorReadingResponse
    assert r.flags != None
    assert r.is_light_reading == False
    assert r.ph >= 7.0
    assert r.ph <= 9.0
    assert r.nh3 >= 0.0
    assert r.nh3 <= 0.1
    assert r.temperature >= 20.0
    assert r.temperature <= 28.0
    assert r.kelvin != None
    assert r.kelvin_x != None
    assert r.kelvin_y != None
    assert r.par != None
    assert r.lux != None
    assert r.pur != None

    d.close()

