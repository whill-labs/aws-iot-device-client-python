import json

from awscrt import mqtt

from awsiotclient import pubsub


class TestSubscriber:
    def test_subscribes_to_topic(self, make_pubsub_connection):
        conn = make_pubsub_connection(mqtt.QoS.AT_LEAST_ONCE)
        pubsub.Subscriber(conn, "my/topic")

        conn.subscribe.assert_called_once()
        call_kwargs = conn.subscribe.call_args
        assert call_kwargs.kwargs["topic"] == "my/topic"
        assert call_kwargs.kwargs["qos"] == mqtt.QoS.AT_LEAST_ONCE

    def test_callback_parses_json(self, make_pubsub_connection):
        conn = make_pubsub_connection(mqtt.QoS.AT_LEAST_ONCE)
        received = []

        def callback(topic, payload):
            received.append((topic, payload))

        sub = pubsub.Subscriber(conn, "my/topic", callback=callback)

        # Simulate message received
        sub.on_message_received("my/topic", json.dumps({"key": "value"}).encode())

        assert len(received) == 1
        assert received[0] == ("my/topic", {"key": "value"})


class TestPublisher:
    def test_publishes_payload(self, make_pubsub_connection):
        conn = make_pubsub_connection(mqtt.QoS.AT_LEAST_ONCE)
        pub = pubsub.Publisher(conn, "my/topic")
        pub.publish({"foo": "bar"})

        conn.publish.assert_called_once()
        call_kwargs = conn.publish.call_args
        assert call_kwargs.kwargs["topic"] == "my/topic"
        assert json.loads(call_kwargs.kwargs["payload"]) == {"foo": "bar"}
        assert call_kwargs.kwargs["qos"] == mqtt.QoS.AT_LEAST_ONCE

    def test_empty_payload_does_not_publish(self, make_pubsub_connection):
        conn = make_pubsub_connection(mqtt.QoS.AT_LEAST_ONCE)
        pub = pubsub.Publisher(conn, "my/topic")
        result = pub.publish(None)

        conn.publish.assert_not_called()
        assert result.result() is None
