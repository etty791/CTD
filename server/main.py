from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from server.connection import Connection
from server.connection_manager import ConnectionManager
from server.dispatcher import dispatch
from server.protocol import Envelope
import server.handlers  # noqa: F401 -- import registers handlers with the dispatcher

app = FastAPI()
manager = ConnectionManager()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/debug/connections")
def debug_connections():
    return {"count": manager.count()}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    conn = Connection(websocket)
    manager.register(conn)
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                envelope = Envelope.model_validate_json(raw)
            except ValidationError as exc:
                await conn.send_error(str(exc))
                continue

            await dispatch(conn, envelope)
    except WebSocketDisconnect:
        manager.remove(conn.id)
        print(f"{conn.id} disconnected")
