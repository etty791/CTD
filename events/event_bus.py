import logging
from collections import defaultdict
from typing import Any, Callable, Dict, List, Type

logger = logging.getLogger(__name__)

Handler = Callable[[Any], None]


class EventBus:
    """A minimal synchronous publish/subscribe dispatcher
    """

    def __init__(self) -> None:
        self._handlers: Dict[Type[Any], List[Handler]] = defaultdict(list)

    def subscribe(self, event_type: Type[Any], handler: Handler) -> None:
        self._handlers[event_type].append(handler)

    def unsubscribe(self, event_type: Type[Any], handler: Handler) -> None:
        handlers = self._handlers.get(event_type)
        if handlers is not None and handler in handlers:
            handlers.remove(handler)

    def publish(self, event: Any) -> None:
        """Dispatch `event` to every handler subscribed for `type(event)`,
        in subscription order. A handler that raises is logged and skipped
        so it can't prevent the remaining handlers from running."""
        for handler in list(self._handlers.get(type(event), ())):
            try:
                handler(event)
            except Exception:
                logger.exception(
                    "EventBus handler %r raised while handling %r", handler, event
                )
