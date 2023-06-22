import json
from concurrent.futures import Future
from typing import Any, Callable, Dict, Optional

from awscrt import mqtt

from . import get_module_logger

logger = get_module_logger(__name__)


def empty_func(
    topic: str, payload: Optional[Dict[str, Any]], **kwargs: Optional[Dict[str, Any]]
) -> None:
    logger.debug(f"empty_func: {topic}, {payload}")


class Subscriber:
    def __init__(
        self,
        connection: mqtt.Connection,
        topic: str,
        qos: mqtt.QoS = mqtt.QoS.AT_LEAST_ONCE,
        callback: Callable[[str, Optional[Dict[str, Any]]], None] = empty_func,
    ):
        self.callback = callback
        self.future, self.packet_id = connection.subscribe(
            topic=topic, qos=qos, callback=self.on_message_received
        )

        self.result = self.future.result()
        logger.debug(f"Subscribed with {str(self.result['qos'])}")

    def on_message_received(self, topic: str, payload: bytes) -> None:
        packet = json.loads(payload)
        self.callback(topic, packet)
        logger.debug(f"Received message from topic '{topic}': {packet}")


class Publisher:
    def __init__(
        self,
        connection: mqtt.Connection,
        topic: str,
        qos: mqtt.QoS = mqtt.QoS.AT_LEAST_ONCE,
    ):
        self.connection = connection
        self.topic = topic
        self.qos = qos

    def publish(self, payload: Optional[Dict[str, Any]]) -> "Future[Any]":
        if payload:
            logger.debug(f"Publishing message to topic '{self.topic}': {payload}")
            future, _ = self.connection.publish(
                topic=self.topic, payload=json.dumps(payload), qos=self.qos
            )
        else:
            logger.debug(f"Empty payload. Nothing will be publshed to '{self.topic}'")
            future = Future()
            future.set_result(None)

        return future
