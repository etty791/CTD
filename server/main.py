from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from server.connection import Connection
from server.connection_manager import ConnectionManager
from server.protocol import Envelope, MessageType
from server.session import PlayerSession

app = FastAPI()
manager = ConnectionManager()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/debug/connections")
def debug_connections():
    return {"count": manager.count()}


async def handle_message(conn: Connection, envelope: Envelope) -> None:
    if envelope.type == MessageType.AUTH:
        player_id = envelope.payload.get("player_id")
        if not player_id:
            await conn.send_error("auth payload requires player_id")
            return
        PlayerSession(player_id, conn)
        await conn.send(Envelope(type=MessageType.AUTH, payload={"status": "ok", "player_id": player_id}))
        return

    if conn.player_session is None:
        await conn.send_error("not authenticated")
        return

    # other message types handled here in later steps


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

            await handle_message(conn, envelope)
    except WebSocketDisconnect:
        manager.remove(conn.id)
        print(f"{conn.id} disconnected")
