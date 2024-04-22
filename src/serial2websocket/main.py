import asyncio
import logging
import websockets
from websockets.legacy.server import WebSocketServerProtocol

from typing import Optional, Callable
from signal import SIGINT, SIGTERM

from serial import Serial

from argparse import ArgumentParser


logger = logging.getLogger(__name__)


class ISerialConnection:
    @property
    def is_open(self):
        raise NotImplementedError

    def open(self):
        raise NotImplementedError

    def close(self):
        raise NotImplementedError

    def write(self, raw: str):
        raise NotImplementedError

    def read(self) -> Optional[str]:
        raise NotImplementedError


class SerialConnection(ISerialConnection):
    def __init__(self, port: str, baudrate: int):
        self._port = port
        self._baudrate = baudrate

        self._serial: Optional[Serial] = None

    @property
    def is_open(self):
        return self._serial is not None and self._serial.is_open

    def open(self):
        self.close()

        self._serial = Serial(self._port, self._baudrate)
        self._serial.open()

    def close(self):
        if self.is_open:
            self._serial.close()

    def write(self, raw: str):
        try:
            self._serial.write(str.encode(raw.upper() + '\r\n'))
            self._serial.flush()
        except Exception as e:  # noqa
            logger.error("Serial error try to reconnect")
            self.open()

    def read(self) -> str:
        if self.is_open:
            try:
                line = self._serial.readline()
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
            except Exception:  # noqa
                logger.error("Could not send message to client")

    async def connect_client(self, websocket: WebSocketServerProtocol):
        logger.info("Connecting client")
        self._clients.add(websocket)
        try:
            async for message in websocket:
                self._message_consumer(message)

            await websocket.wait_closed()
        finally:
            self._clients.remove(websocket)
            logger.info("Disconnected client")

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
        self._serial_connection.open()
        task = asyncio.create_task(self._websocket_server.start())

        while not self._stop_event.is_set():
            line = self._serial_connection.read()
            if line is not None:
                await self._websocket_server.send_message(line)
            await asyncio.sleep(0.01)
        await task

    def stop(self):
        logger.info("stopping")
        self._stop_event.set()
        self._websocket_server.stop()


def main():
    parser = ArgumentParser()
    parser.add_argument("device", type=str, help="serial port device, e.g. /dev/ttyS0")
    parser.add_argument("host", type=str, default="localhost", help="websocket host, set to 0.0.0.0 to make it network accessible")
    parser.add_argument("port", type=int, default=9899, help="websocket port")

    parser.add_argument("-b", "--baudrate", type=int, default=19200)
    args = parser.parse_args()

    server = Serial2WebsocketServer(args.port, args.baudrate)

    loop = asyncio.new_event_loop()
    loop.add_signal_handler(SIGINT, server.stop)
    loop.add_signal_handler(SIGTERM, server.stop)

    loop.run_until_complete(server.start())
    logger.info("exit")


if __name__ == "__main__":
    main()
