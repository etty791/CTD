import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from server.connection import Connection
from server.connection_manager import ConnectionManager
from server.dispatcher import dispatch
from server.persistence.persistence_config import resolve_db_path
from shared.protocol import Envelope
from server.server_config import (
    DEBUG_CONNECTIONS_PATH,
    GAME_OVER_REASON_DISCONNECT,
    HEALTH_PATH,
    WS_PATH,
)
import server.handlers as handlers  # noqa: F401 -- import registers handlers with the dispatcher

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    handlers.persistence.start(resolve_db_path())
    yield
    handlers.persistence.stop()


app = FastAPI(lifespan=lifespan)
manager = ConnectionManager()


@app.get(HEALTH_PATH)
def health():
    return {"status": "ok"}


@app.get(DEBUG_CONNECTIONS_PATH)
def debug_connections():
    return {"count": manager.count()}


@app.websocket(WS_PATH)
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
        pass
    except Exception:
        logger.exception("%s crashed", conn.id)
    finally:
        manager.remove(conn.id)
        session = conn.player_session
        if session is not None:
            handlers.logged_in_usernames.discard(session.player_id)
            game = handlers.registry.get_game_for_player(session.player_id)
            if game is not None:
                if session.player_id in game.color_of:
                    opponent = game.opponent_of(session.player_id)
                    winner_color = game.color_of[opponent.player_id]
                    await game.finalize_by_forfeit(winner_color, GAME_OVER_REASON_DISCONNECT)
                else:
                    game.remove_observer(session)
                    handlers.registry.remove_player_mapping(session.player_id)
            else:
                handlers.room_manager.leave(session)
        print(f"{conn.id} disconnected")
