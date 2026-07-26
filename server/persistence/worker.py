"""Threaded persistence worker.

Invariant: sqlite connections are single-thread-affine and blocking, and scrypt
hashing is CPU-heavy. Both must stay off the asyncio event loop. This worker
owns the Database + UserRepository on ONE dedicated thread
(`ThreadPoolExecutor(max_workers=1)`), so every job is serialized on that same
thread — which is exactly what sqlite's thread-affinity requires and makes
`self._repo`/`self._db` (assigned inside a worker job) safely visible to all
later jobs.

Jobs are submitted as Futures, so they can be driven from a synchronous context
(e.g. a sync event-bus handler) via `future.result()`, or awaited from async
code via `await asyncio.wrap_future(future)`.
"""

from concurrent.futures import Future, ThreadPoolExecutor
import os
from typing import Callable, TypeVar

from server.persistence.db import Database
from server.persistence.user_repository import UserRepository

T = TypeVar("T")

_SINGLE_WORKER = 1


class PersistenceNotStartedError(RuntimeError):
    """Raised when a job is submitted before `start` initialized the repository."""


class PersistenceWorker:
    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(max_workers=_SINGLE_WORKER)
        self._db: Database | None = None
        self._repo: UserRepository | None = None

    def start(self, db_path: str) -> None:
        """Initialize the DB + repository on the worker thread and block until ready."""
        self._executor.submit(self._startup, db_path).result()

    def _startup(self, db_path: str) -> None:
        parent = os.path.dirname(db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        db = Database(db_path)
        db.init_schema()
        self._db = db
        self._repo = UserRepository(db)

    def submit(self, fn: Callable[[UserRepository], T]) -> "Future[T]":
        """Schedule `fn(repository)` on the worker thread, returning its Future."""
        return self._executor.submit(self._run, fn)

    def _run(self, fn: Callable[[UserRepository], T]) -> T:
        if self._repo is None:
            raise PersistenceNotStartedError(
                "PersistenceWorker.submit called before start()"
            )
        return fn(self._repo)

    def stop(self) -> None:
        """Close the Database on the worker thread, then shut the pool down."""
        if self._db is not None:
            self._executor.submit(self._shutdown).result()
        self._executor.shutdown(wait=True)

    def _shutdown(self) -> None:
        if self._db is not None:
            self._db.close()
            self._db = None
            self._repo = None
