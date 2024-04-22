import asyncio
from typing import List, Callable, Optional

import pytest
import websockets

from serial2websocket.main import Serial2WebsocketServer, ISerialConnection, IWebsocketServer, WebsocketServer


class MockSerialServer(ISerialConnection):
    def __init__(self, read_buffer: List[str] = None):
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
            self.write_buffer.append(raw)

    def read(self) -> Optional[str]:
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


@pytest.mark.asyncio
async def test_server():
    mock_serial_server = MockSerialServer(read_buffer=["test-serial2websocket1", "test-serial2websocket2"])
    mock_websocket_server = MockWebsocketServer(mock_serial_server.write, messages=["test-websocket2serial1", "test-websocket2serial2"])

    server = Serial2WebsocketServer(mock_serial_server, mock_websocket_server)
    task = asyncio.create_task(server.start())

    await asyncio.sleep(0.5)

    server.stop()
    await task
    assert mock_serial_server.write_buffer == ["test-websocket2serial1", "test-websocket2serial2"]
    assert mock_websocket_server.sent_messages == ["test-serial2websocket1", "test-serial2websocket2"]


@pytest.mark.asyncio
async def test_websocket_server():
    mock_serial_server = MockSerialServer()
    mock_serial_server.open()

    websocket_server = WebsocketServer("localhost", 9899, mock_serial_server.write)
    websocket_client = WebsocketClient("ws://localhost:9899")

    server_task = asyncio.create_task(websocket_server.start())
    await asyncio.sleep(0.1)

    client_task = asyncio.create_task(websocket_client.start())
    await asyncio.sleep(0.1)

    await websocket_server.send_message("test-serial2websocket1")
    await websocket_server.send_message("test-serial2websocket2")
    await asyncio.sleep(0.1)

    await websocket_client.send_message("test-websocket2serial1")
    await websocket_client.send_message("test-websocket2serial2")
    await asyncio.sleep(0.1)

    websocket_server.stop()
    websocket_client.stop()

    await server_task
    await client_task

    assert mock_serial_server.write_buffer == ["test-websocket2serial1", "test-websocket2serial2"]
    assert websocket_client.messages == ["test-serial2websocket1", "test-serial2websocket2"]
