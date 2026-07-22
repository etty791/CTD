from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from server.connection import Connection
from server.protocol import Envelope

app = FastAPI()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    conn = Connection(websocket)
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                envelope = Envelope.model_validate_json(raw)
            except ValidationError as exc:
                await conn.send_error(str(exc))
                continue

            # temporary: just bounce it back as confirmation
            await conn.send(envelope)
    except WebSocketDisconnect:
        print(f"{conn.id} disconnected")
