from dataclasses import dataclass

from events.event_bus import EventBus


@dataclass(frozen=True)
class DummyEvent:
    value: int


@dataclass(frozen=True)
class OtherEvent:
    pass


class TestSubscribePublish:
    def test_subscribed_handler_receives_event(self):
        bus = EventBus()
        received = []
        bus.subscribe(DummyEvent, received.append)
        event = DummyEvent(1)
        bus.publish(event)
        assert received == [event]

    def test_publish_with_no_subscribers_does_not_raise(self):
        bus = EventBus()
        bus.publish(DummyEvent(1))

    def test_handler_only_receives_its_own_event_type(self):
        bus = EventBus()
        received = []
        bus.subscribe(DummyEvent, received.append)
        bus.publish(OtherEvent())
        assert received == []

    def test_multiple_handlers_all_receive_event(self):
        bus = EventBus()
        first, second = [], []
        bus.subscribe(DummyEvent, first.append)
        bus.subscribe(DummyEvent, second.append)
        event = DummyEvent(1)
        bus.publish(event)
        assert first == [event]
        assert second == [event]

    def test_handlers_called_in_subscription_order(self):
        bus = EventBus()
        order = []
        bus.subscribe(DummyEvent, lambda e: order.append("first"))
        bus.subscribe(DummyEvent, lambda e: order.append("second"))
        bus.publish(DummyEvent(1))
        assert order == ["first", "second"]


class TestUnsubscribe:
    def test_unsubscribed_handler_does_not_receive_event(self):
        bus = EventBus()
        received = []
        bus.subscribe(DummyEvent, received.append)
        bus.unsubscribe(DummyEvent, received.append)
        bus.publish(DummyEvent(1))
        assert received == []

    def test_unsubscribe_unknown_handler_does_not_raise(self):
        bus = EventBus()
        bus.unsubscribe(DummyEvent, lambda e: None)

    def test_unsubscribe_only_removes_targeted_handler(self):
        bus = EventBus()
        first, second = [], []
        bus.subscribe(DummyEvent, first.append)
        bus.subscribe(DummyEvent, second.append)
        bus.unsubscribe(DummyEvent, first.append)
        bus.publish(DummyEvent(1))
        assert first == []
        assert second == [DummyEvent(1)]


class TestHandlerFailureIsolation:
    def test_raising_handler_does_not_block_others(self):
        bus = EventBus()
        received = []

        def bad_handler(event):
            raise ValueError("boom")

        bus.subscribe(DummyEvent, bad_handler)
        bus.subscribe(DummyEvent, received.append)
        bus.publish(DummyEvent(1))
        assert received == [DummyEvent(1)]

    def test_raising_handler_does_not_propagate(self):
        bus = EventBus()
        bus.subscribe(DummyEvent, lambda e: (_ for _ in ()).throw(ValueError("boom")))
        bus.publish(DummyEvent(1))
