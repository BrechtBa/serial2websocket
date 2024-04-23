import asyncio
import os
import pty
import subprocess
from typing import List, Optional, Callable

import websockets

from serial2websocket.main import ISerialConnection, IWebsocketServer


class MockSerialServer(ISerialConnection):
    def __init__(self, read_buffer: List[str] = None):
        self._is_open = False
        self._read_buffer = read_buffer or []
        self.write_buffer = []

    @property
    def is_open(self) -> bool:
        return self._is_open

    async def open(self) -> None:
        self._is_open = True

    def close(self) -> None:
        self._is_open = False

    def write(self, raw: str) -> None:
        if self._is_open:
            self.write_buffer.append(raw)

    async def read(self) -> Optional[str]:
        if self._is_open:
            try:
                return self._read_buffer.pop(0)
            except IndexError:
                pass


class MockWebsocketServer(IWebsocketServer):
    def __init__(self, message_consumer: Callable[[str], None], messages: list[str] = None):
        self._message_consumer = message_consumer
        self._read_messages = messages or []
        self.sent_messages = []

        self._stop_event = asyncio.Event()

    async def send_message(self, message: str) -> None:
        self.sent_messages.append(message)

    async def start(self):
        while not self._stop_event.is_set():
            try:
                message = self._read_messages.pop(0)
                self._message_consumer(message)
            except IndexError:
                pass

            await asyncio.sleep(0.1)

    def stop(self):
        self._stop_event.set()


class WebsocketClient:
    def __init__(self, uri: str):
        self._uri = uri
        self.messages = []

        self._websocket = None
        self._stop_event = asyncio.Event()

    async def send_message(self, message: str) -> None:
        await self._websocket.send(message)

    async def start(self):
        async with websockets.connect(self._uri) as websocket:
            self._websocket = websocket
            while not self._stop_event.is_set():
                try:
                    message = await websocket.recv()
                    self.messages.append(message)

                except websockets.exceptions.ConnectionClosed:
                    break

    def stop(self):
        self._stop_event.set()


class SocatSerialDevice:
    """
    linux only, requires `socat`
    """
    def __init__(self):
        self._process = None
        self.ports = []

    def start(self) -> List[str]:
        master, slave = pty.openpty()
        cmd = ["socat", "-d", "-d", "pty,raw,echo=1", "pty,raw,echo=1"]
        self._process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=slave, stderr=slave, close_fds=True)

        stdout = os.fdopen(master)
        line = stdout.readline()
        self.ports.append(line.split(" ")[-1][:-1])

        line = stdout.readline()
        self.ports.append(line.split(" ")[-1][:-1])

        return self.ports

    def stop(self):
        self._process.kill()
