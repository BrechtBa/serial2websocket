import asyncio
import logging
import sys

import websockets
from websockets.legacy.server import WebSocketServerProtocol

from typing import Optional, Callable
from signal import SIGINT, SIGTERM

from serial import Serial, SerialException
from serial.serialutil import EIGHTBITS, PARITY_NONE, STOPBITS_ONE
from argparse import ArgumentParser


logger = logging.getLogger(__name__)


class ISerialConnection:
    @property
    def is_open(self):
        raise NotImplementedError

    async def open(self):
        raise NotImplementedError

    def close(self):
        raise NotImplementedError

    def write(self, raw: str):
        raise NotImplementedError

    async def read(self) -> Optional[str]:
        raise NotImplementedError


class SerialConnection(ISerialConnection):
    def __init__(self, device: str, baudrate: int = 9600, bytesize=EIGHTBITS, parity=PARITY_NONE, stopbits=STOPBITS_ONE):
        self._device = device
        self._baudrate = baudrate
        self._bytesize = bytesize
        self._parity = parity
        self._stopbits = stopbits

        self._stop_event = asyncio.Event()
        self._serial = Serial(baudrate=self._baudrate)

    @property
    def is_open(self):
        return self._serial is not None and self._serial.is_open

    async def open(self):
        self._serial.close()
        if not self._stop_event.is_set():
            self._serial.port = self._device
            try:
                self._serial.open()
                logger.info("opened serial connection at %s", self._device)
            except SerialException as e:
                logger.error("error opening serial connection %s, retrying", e)
                await asyncio.sleep(5)
                await self.open()

    def close(self):
        self._stop_event.set()
        logger.info("closing serial connection")
        if self._serial.is_open:
            self._serial.close()

    def write(self, raw: str):
        try:
            print("writing")
            self._serial.write(str.encode(raw.upper() + '\r\n'))
            self._serial.flush()
        except Exception as e:  # noqa
            logger.error("serial error try to reconnect")
            self.open()

    async def read(self) -> str:
        if self.is_open:
            try:
                loop = asyncio.get_running_loop()
                line = await loop.run_in_executor(None, self._serial.readline)
                return line.strip().decode('utf8')

            except Exception as e:  # noqa
                logger.error("could not read %s" % e)
                try:
                    self._serial.reset_input_buffer()
                except Exception as e:
                    logger.error("could not reset_input_buffer %s" % e)


class IWebsocketServer:
    async def send_message(self, message: str) -> None:
        pass

    async def start(self):
        raise NotImplementedError

    def stop(self):
        raise NotImplementedError


class WebsocketServer(IWebsocketServer):
    def __init__(self, host: str, port: int, message_consumer: Callable[[str], None]):
        self._host = host
        self._port = port
        self._message_consumer = message_consumer

        self._stop_event = asyncio.Event()
        self._clients = set()

    async def send_message(self, message: str):
        for client in self._clients:
            try:
                await client.send(message)
                logger.debug("sent message %s to client %s", message, client)
            except Exception:  # noqa
                logger.error("could not send message to client")

    async def connect_client(self, websocket: WebSocketServerProtocol):
        logger.info("connecting client")
        self._clients.add(websocket)
        try:
            async for message in websocket:
                self._message_consumer(message)

            await websocket.wait_closed()
        finally:
            self._clients.remove(websocket)
            logger.info("disconnected client")

    async def start(self):
        async with websockets.serve(self.connect_client, self._host, self._port):
            await self._stop_event.wait()

    def stop(self):
        self._stop_event.set()


class Serial2WebsocketServer:
    def __init__(self, serial_connection: ISerialConnection, websocket_server: IWebsocketServer):
        self._serial_connection = serial_connection
        self._websocket_server = websocket_server

        self._stop_event = asyncio.Event()

    async def start(self):
        logger.info("starting")
        await self._serial_connection.open()
        task = asyncio.create_task(self._websocket_server.start())

        logger.info("listening for serial messages")
        while not self._stop_event.is_set():
            line = await self._serial_connection.read()
            if line is not None:
                logger.debug("read message from serial device %s", line)
                await self._websocket_server.send_message(line)
            await asyncio.sleep(0.01)
        await task

    def stop(self):
        logger.info("stopping")
        self._stop_event.set()
        self._serial_connection.close()
        self._websocket_server.stop()


class MockSerialServer(ISerialConnection):
    def __init__(self, read_buffer=None):
        self._is_open = False
        self._read_buffer = read_buffer or []
        self.write_buffer = []

    @property
    def is_open(self) -> bool:
        return self._is_open

    def open(self) -> None:
        self._is_open = True

    def close(self) -> None:
        self._is_open = False

    def write(self, raw: str) -> None:
        if self._is_open:
            logger.info(raw)

    def read(self) -> Optional[str]:
        if self._is_open:
            try:
                return self._read_buffer.pop(0)
            except IndexError:
                pass


def main():
    parser = ArgumentParser()
    parser.add_argument("device", type=str, help="serial port device, e.g. /dev/ttyS0")
    parser.add_argument("--host", type=str, default="localhost", help="websocket host, set to 0.0.0.0 to make it network accessible")
    parser.add_argument("--port", type=int, default=9899, help="websocket port")

    parser.add_argument("-b", "--baudrate", type=int, default=19200)
    parser.add_argument("-s", "--bytesize", type=int, default=EIGHTBITS)
    parser.add_argument("-p", "--parity", type=str, default=PARITY_NONE)
    parser.add_argument("-t", "--stopbits", type=int, default=STOPBITS_ONE)
    parser.add_argument("-l", "--loglevel", type=str, default="INFO")

    args = parser.parse_args()

    logging.basicConfig(level=logging.getLevelName(args.loglevel), stream=sys.stdout)

    serial_connection = SerialConnection(
        device=args.device, baudrate=args.baudrate, bytesize=args.bytesize, parity=args.parity, stopbits=args.stopbits)
    # serial_connection = MockSerialServer(["test1", "test2"])
    websocket_server = WebsocketServer(
        host=args.host, port=args.port, message_consumer=serial_connection.write)

    server = Serial2WebsocketServer(serial_connection, websocket_server)

    loop = asyncio.new_event_loop()
    loop.add_signal_handler(SIGINT, server.stop)
    loop.add_signal_handler(SIGTERM, server.stop)

    loop.run_until_complete(server.start())
    logger.info("exit")


if __name__ == "__main__":
    main()
