from typing import Any, List, Tuple

import pytest
from awscrt import mqtt

from awsiotclient import pubsub


class Inbox:
    def __init__(self) -> None:
        self.messages: List[Tuple[str, Any]] = []

    def __call__(self, topic: str, payload: Any) -> None:
        self.messages.append((topic, payload))


def test_message_travels_from_publisher_to_subscriber(broker):
    inbox = Inbox()
    pubsub.Subscriber(broker.connect(), "devices/1/status", callback=inbox)

    pubsub.Publisher(broker.connect(), "devices/1/status").publish(
        {"battery": 80}
    ).result()

    assert inbox.messages == [("devices/1/status", {"battery": 80})]


def test_subscriber_accepts_wildcards(broker):
    inbox = Inbox()
    pubsub.Subscriber(broker.connect(), "devices/+/status", callback=inbox)
    publisher_connection = broker.connect()

    pubsub.Publisher(publisher_connection, "devices/1/status").publish(
        {"n": 1}
    ).result()
    pubsub.Publisher(publisher_connection, "devices/2/other").publish({"n": 2}).result()

    assert inbox.messages == [("devices/1/status", {"n": 1})]


def test_subscriber_reports_the_granted_qos(broker):
    subscriber = pubsub.Subscriber(broker.connect(), "a", qos=mqtt.QoS.AT_MOST_ONCE)

    assert subscriber.result["qos"] == mqtt.QoS.AT_MOST_ONCE


def test_subscription_failure_is_raised(broker, connection):
    connection.reject_subscription("a")

    with pytest.raises(mqtt.SubscribeError):
        pubsub.Subscriber(connection, "a")


@pytest.mark.parametrize("payload", [None, {}])
def test_empty_payload_is_not_published(broker, connection, payload):
    future = pubsub.Publisher(connection, "a").publish(payload)

    assert future.result() is None
    assert broker.messages == []


def test_publish_failure_is_returned_through_the_future(broker, connection):
    connection.fail_next_publish("a")

    with pytest.raises(RuntimeError, match="publish failed"):
        pubsub.Publisher(connection, "a").publish({"n": 1}).result()


def test_non_json_message_does_not_reach_the_callback(broker):
    inbox = Inbox()
    pubsub.Subscriber(broker.connect(), "a", callback=inbox)

    broker.connect().publish("a", b"not json", mqtt.QoS.AT_LEAST_ONCE)

    assert inbox.messages == []
    assert len(broker.take_callback_errors()) == 1
