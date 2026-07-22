from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from server.protocol import Envelope

app = FastAPI()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                envelope = Envelope.model_validate_json(raw)
            except ValidationError as exc:
                error = Envelope(type="error", payload={"message": str(exc)})
                await websocket.send_text(error.model_dump_json())
                continue

            # temporary: just bounce it back as confirmation
            await websocket.send_text(envelope.model_dump_json())
    except WebSocketDisconnect:
        print("client disconnected")
