import asyncio
import time

import pytest
import serial

from mocks import SocatSerialDevice
from serial2websocket.main import SerialConnection


@pytest.mark.asyncio
async def test_serial_connection_read():
    socket = SocatSerialDevice()
    ports = socket.start()

    serial_connection = SerialConnection(ports[0], 9600)
    open_task = asyncio.create_task(serial_connection.open())
    await asyncio.sleep(0.1)

    serial_device = serial.Serial(ports[1])
    read_task = asyncio.create_task(serial_connection.read())
    await asyncio.sleep(0.1)

    serial_device.write(str.encode("message-from-device\n"))
    serial_device.flush()
    serial_device.close()

    await read_task

    serial_connection.close()

    await open_task

    socket.stop()
    assert read_task.result() == "message-from-device"


@pytest.mark.asyncio
async def test_serial_connection_wite():
    socket = SocatSerialDevice()
    ports = socket.start()

    serial_connection = SerialConnection(ports[0], 9600)
    open_task = asyncio.create_task(serial_connection.open())
    await asyncio.sleep(0.1)

    serial_device = serial.Serial(ports[1])

    async def read():
        loop = asyncio.get_running_loop()
        line = await loop.run_in_executor(None, serial_device.readline)
        return line.strip().decode('utf8')

    read_task = asyncio.create_task(read())
    await asyncio.sleep(0.1)

    serial_connection.write("message-to-device")

    time.sleep(0.2)

    await open_task
    await read_task

    serial_device.close()

    socket.stop()
    assert read_task.result() == "MESSAGE-TO-DEVICE"