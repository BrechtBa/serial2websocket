import asyncio

import pytest

from serial2websocket.main import Serial2WebsocketServer
from mocks import MockSerialServer, MockWebsocketServer


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
