"""Wire contract shared by `server/` and `client/`.

Everything in this package describes what goes over the WebSocket: envelope
shape, payload models, and the literal values that appear inside them. It
depends only on `model/` (the pure domain layer), never on `server/`,
`client/`, `game_engine/` or `view/` -- so both sides can import it without
either side depending on the other.
"""
