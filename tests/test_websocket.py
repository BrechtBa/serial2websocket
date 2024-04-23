import asyncio

import pytest

from mocks import MockSerialServer, WebsocketClient

from serial2websocket.main import WebsocketServer


@pytest.mark.asyncio
async def test_websocket_server():
    mock_serial_server = MockSerialServer()
    await mock_serial_server.open()

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
