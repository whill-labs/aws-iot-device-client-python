"""In-memory fakes of AWS IoT Core for unit tests.

The fakes sit at the MQTT layer. ``FakeConnection`` stands in for
``awscrt.mqtt.Connection`` and the fake services answer the ``$aws/things/...``
topics that the real ``awsiot`` SDK clients publish to. Tests therefore drive
awsiotclient only through its public API, while the SDK's own topic building
and JSON (de)serialization still run for real.

The services model the documented behavior of AWS IoT closely enough for the
client's contract, not every detail. Behavior that matters but is only
approximated is noted where it is implemented.
"""

import inspect
import json
import re
import threading
import time
from concurrent.futures import Future
from copy import deepcopy
from typing import Any, Callable, Dict, List, Optional, Tuple

from awscrt import mqtt

Message = Tuple[str, bytes]


def topic_matches(topic_filter: str, topic: str) -> bool:
    filter_levels = topic_filter.split("/")
    topic_levels = topic.split("/")
    for i, level in enumerate(filter_levels):
        if level == "#":
            return True
        if i >= len(topic_levels):
            return False
        if level != "+" and level != topic_levels[i]:
            return False
    return len(filter_levels) == len(topic_levels)


def completed(result: Any = None, exception: Optional[BaseException] = None) -> Future:
    future: Future = Future()
    if exception is None:
        future.set_result(result)
    else:
        future.set_exception(exception)
    return future


def _invoke_message_callback(
    callback: Callable[..., None], topic: str, payload: bytes, qos: mqtt.QoS
) -> None:
    # awscrt supports both the legacy (topic, payload) callback signature and
    # the current one with dup/qos/retain, choosing by inspecting the callback.
    kwargs = dict(topic=topic, payload=payload, dup=False, qos=qos, retain=False)
    try:
        inspect.signature(callback).bind(**kwargs)
    except TypeError:
        callback(topic=topic, payload=payload)
    else:
        callback(**kwargs)


class FakeBroker:
    """Routes messages between FakeConnections and fake AWS services.

    Delivery is synchronous: ``publish`` returns after every subscriber
    callback has run. Like the CRT event loop, the broker does not let an
    exception raised by a subscriber callback reach the publisher; it records
    it in ``callback_errors`` instead.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._connections: List["FakeConnection"] = []
        self._services: List["FakeService"] = []
        self.messages: List[Message] = []
        self.callback_errors: List[BaseException] = []

    def connect(self) -> "FakeConnection":
        connection = FakeConnection(self)
        with self._lock:
            self._connections.append(connection)
        return connection

    def add_service(self, service: "FakeService") -> None:
        service.broker = self
        with self._lock:
            self._services.append(service)

    def route(self, topic: str, payload: bytes) -> None:
        responses: List[Message] = []
        with self._lock:
            services = list(self._services)
        for service in services:
            responses.extend(service.handle(topic, payload))
        self.deliver(topic, payload)
        for response in responses:
            self.deliver(*response)

    def deliver(self, topic: str, payload: bytes) -> None:
        with self._lock:
            self.messages.append((topic, payload))
            connections = list(self._connections)
        for connection in connections:
            connection.deliver(topic, payload)

    def payloads(self, topic: str) -> List[Any]:
        """JSON payloads published to exactly ``topic``, oldest first."""
        with self._lock:
            messages = list(self.messages)
        return [json.loads(p) if p else None for t, p in messages if t == topic]

    def record_callback_error(self, error: BaseException) -> None:
        with self._lock:
            self.callback_errors.append(error)

    def take_callback_errors(self) -> List[BaseException]:
        with self._lock:
            errors, self.callback_errors = self.callback_errors, []
        return errors


class FakeConnection(mqtt.Connection):
    """Stand-in for ``awscrt.mqtt.Connection`` backed by a FakeBroker.

    It subclasses the real class because the awsiot SDK checks
    ``isinstance(connection, mqtt.Connection)``. The native connection is
    deliberately never created.
    """

    def __init__(self, broker: FakeBroker) -> None:
        self._broker = broker
        self._lock = threading.Lock()
        self._packet_id = 0
        self.subscriptions: Dict[
            str, Tuple[mqtt.QoS, Optional[Callable[..., None]]]
        ] = {}
        self._publish_failures: List[Tuple[str, BaseException]] = []
        self._rejected_filters: List[str] = []
        self.resubscribe_count = 0

    def _next_packet_id(self) -> int:
        with self._lock:
            self._packet_id += 1
            return self._packet_id

    def fail_next_publish(
        self, topic_filter: str, error: Optional[BaseException] = None
    ) -> None:
        """Make the next publish to a matching topic fail without being sent."""
        with self._lock:
            self._publish_failures.append(
                (topic_filter, error or RuntimeError("publish failed"))
            )

    def reject_subscription(self, topic_filter: str) -> None:
        """Make the server reject subscriptions to exactly ``topic_filter``."""
        with self._lock:
            self._rejected_filters.append(topic_filter)

    def subscribe(self, topic, qos, callback=None):  # type: ignore[no-untyped-def]
        packet_id = self._next_packet_id()
        with self._lock:
            if topic in self._rejected_filters:
                return completed(exception=mqtt.SubscribeError(topic)), packet_id
            self.subscriptions[topic] = (qos, callback)
        return completed(dict(packet_id=packet_id, topic=topic, qos=qos)), packet_id

    def unsubscribe(self, topic):  # type: ignore[no-untyped-def]
        with self._lock:
            self.subscriptions.pop(topic, None)
        packet_id = self._next_packet_id()
        return completed(dict(packet_id=packet_id)), packet_id

    def resubscribe_existing_topics(self):  # type: ignore[no-untyped-def]
        packet_id = self._next_packet_id()
        with self._lock:
            self.resubscribe_count += 1
            topics = [(t, qos) for t, (qos, _) in self.subscriptions.items()]
        return completed(dict(packet_id=packet_id, topics=topics)), packet_id

    def publish(self, topic, payload, qos, retain=False):  # type: ignore[no-untyped-def]
        packet_id = self._next_packet_id()
        with self._lock:
            for i, (topic_filter, error) in enumerate(self._publish_failures):
                if topic_matches(topic_filter, topic):
                    del self._publish_failures[i]
                    return completed(exception=error), packet_id
        data = payload.encode() if isinstance(payload, str) else bytes(payload)
        self._broker.route(topic, data)
        return completed(dict(packet_id=packet_id)), packet_id

    def deliver(self, topic: str, payload: bytes) -> None:
        with self._lock:
            subscriptions = list(self.subscriptions.items())
        for topic_filter, (qos, callback) in subscriptions:
            if callback is None or not topic_matches(topic_filter, topic):
                continue
            try:
                _invoke_message_callback(callback, topic, payload, qos)
            except Exception as e:
                self._broker.record_callback_error(e)


class FakeService:
    """A fake AWS IoT service that answers request topics."""

    def __init__(self) -> None:
        self.broker: Optional[FakeBroker] = None
        self._cond = threading.Condition()
        self._rejections: List[Tuple[str, Dict[str, Any]]] = []

    def handle(self, topic: str, payload: bytes) -> List[Message]:
        raise NotImplementedError

    def _publish(self, messages: List[Message]) -> None:
        if self.broker is None:
            raise RuntimeError("service is not attached to a broker")
        for message in messages:
            self.broker.deliver(*message)

    def reject_next(self, operation: str, **error: Any) -> None:
        """Answer the next ``operation`` request on the rejected topic."""
        with self._cond:
            self._rejections.append((operation, error))

    def _take_rejection(self, operation: str) -> Optional[Dict[str, Any]]:
        for i, (op, error) in enumerate(self._rejections):
            if op == operation:
                del self._rejections[i]
                return error
        return None

    def wait_until(self, predicate: Callable[[], bool], timeout: float = 2.0) -> None:
        deadline = time.monotonic() + timeout
        with self._cond:
            while not predicate():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise AssertionError("timed out waiting for the fake service state")
                # Poll as well: some conditions (e.g. callback errors) never notify.
                self._cond.wait(min(remaining, 0.01))


def _encode(obj: Any) -> bytes:
    return json.dumps(obj).encode()


def merge_state(target: Dict[str, Any], patch: Dict[str, Any]) -> None:
    """Apply a shadow update the way the Device Shadow service does.

    Objects merge recursively and ``null`` deletes a key. Other values,
    including lists, replace what was there.
    """
    for key, value in patch.items():
        if value is None:
            target.pop(key, None)
        elif isinstance(value, dict):
            if not isinstance(target.get(key), dict):
                target[key] = {}
            merge_state(target[key], value)
        else:
            target[key] = deepcopy(value)


def compute_delta(desired: Dict[str, Any], reported: Dict[str, Any]) -> Dict[str, Any]:
    delta: Dict[str, Any] = {}
    for key, value in desired.items():
        if key not in reported:
            delta[key] = deepcopy(value)
        elif isinstance(value, dict) and isinstance(reported[key], dict):
            nested = compute_delta(value, reported[key])
            if nested:
                delta[key] = nested
        elif value != reported[key]:
            delta[key] = deepcopy(value)
    return delta


class FakeShadowService(FakeService):
    """Device Shadow service for classic and named shadows.

    Approximation: a delta message is published only when an accepted update
    touched the desired section and a delta remains afterwards.
    """

    _TOPIC = re.compile(r"^\$aws/things/([^/]+)/shadow(?:/name/([^/]+))?/(get|update)$")

    def __init__(self) -> None:
        super().__init__()
        self._shadows: Dict[Tuple[str, Optional[str]], Dict[str, Any]] = {}

    @staticmethod
    def base_topic(thing_name: str, shadow_name: Optional[str] = None) -> str:
        if shadow_name is None:
            return f"$aws/things/{thing_name}/shadow"
        return f"$aws/things/{thing_name}/shadow/name/{shadow_name}"

    def document(
        self, thing_name: str, shadow_name: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Current ``{"desired", "reported", "delta"}`` or None if no shadow exists."""
        with self._cond:
            shadow = self._shadows.get((thing_name, shadow_name))
            if shadow is None:
                return None
            state = deepcopy(shadow["state"])
            state["delta"] = compute_delta(state["desired"], state["reported"])
            return state

    def update(
        self,
        thing_name: str,
        shadow_name: Optional[str] = None,
        desired: Any = None,
        reported: Any = None,
    ) -> None:
        """Update the shadow as another party would, publishing the responses."""
        state = {}
        if desired is not None:
            state["desired"] = desired
        if reported is not None:
            state["reported"] = reported
        self._publish(self._update(thing_name, shadow_name, {"state": state}))

    def handle(self, topic: str, payload: bytes) -> List[Message]:
        match = self._TOPIC.match(topic)
        if match is None:
            return []
        thing_name, shadow_name, operation = match.groups()
        request = json.loads(payload) if payload else {}
        with self._cond:
            error = self._take_rejection(operation)
        if error is not None:
            error.setdefault("timestamp", int(time.time()))
            return [(f"{topic}/rejected", _encode(error))]
        if operation == "get":
            return self._get(thing_name, shadow_name, request)
        return self._update(thing_name, shadow_name, request)

    def _get(
        self, thing_name: str, shadow_name: Optional[str], request: Dict[str, Any]
    ) -> List[Message]:
        topic = self.base_topic(thing_name, shadow_name) + "/get"
        with self._cond:
            shadow = self._shadows.get((thing_name, shadow_name))
            if shadow is None:
                error = dict(
                    code=404, message=f"No shadow exists with name: '{thing_name}'"
                )
                return [(f"{topic}/rejected", _encode(error))]
            state = {k: deepcopy(v) for k, v in shadow["state"].items() if v}
            delta = compute_delta(
                shadow["state"]["desired"], shadow["state"]["reported"]
            )
            if delta:
                state["delta"] = delta
            response = dict(
                state=state, version=shadow["version"], timestamp=int(time.time())
            )
        if "clientToken" in request:
            response["clientToken"] = request["clientToken"]
        return [(f"{topic}/accepted", _encode(response))]

    def _update(
        self, thing_name: str, shadow_name: Optional[str], request: Dict[str, Any]
    ) -> List[Message]:
        base = self.base_topic(thing_name, shadow_name)
        topic = base + "/update"
        state = request.get("state")
        if not isinstance(state, dict):
            error = dict(
                code=400,
                message="Missing required node: state",
                timestamp=int(time.time()),
            )
            return [(f"{topic}/rejected", _encode(error))]

        with self._cond:
            shadow = self._shadows.setdefault(
                (thing_name, shadow_name),
                dict(state=dict(desired={}, reported={}), version=0),
            )
            for section in ("desired", "reported"):
                if section not in state:
                    continue
                if state[section] is None:
                    shadow["state"][section] = {}
                else:
                    merge_state(shadow["state"][section], state[section])
            shadow["version"] += 1
            version = shadow["version"]
            delta = compute_delta(
                shadow["state"]["desired"], shadow["state"]["reported"]
            )
            self._cond.notify_all()

        now = int(time.time())
        accepted = dict(state=state, version=version, timestamp=now)
        if "clientToken" in request:
            accepted["clientToken"] = request["clientToken"]
        messages = [(f"{topic}/accepted", _encode(accepted))]
        if "desired" in state and delta:
            messages.append(
                (
                    f"{topic}/delta",
                    _encode(dict(state=delta, version=version, timestamp=now)),
                )
            )
        return messages


class FakeJobsService(FakeService):
    """Jobs service: one queue of job executions per thing.

    ``notify_before_accept`` swaps the order of the update/accepted response
    and the notify-next event, which AWS IoT does not guarantee.
    """

    _START_NEXT = re.compile(r"^\$aws/things/([^/]+)/jobs/start-next$")
    _UPDATE = re.compile(r"^\$aws/things/([^/]+)/jobs/([^/]+)/update$")
    TERMINAL = ("SUCCEEDED", "FAILED", "REJECTED", "CANCELED", "REMOVED", "TIMED_OUT")

    def __init__(self, notify_before_accept: bool = False) -> None:
        super().__init__()
        self._jobs: Dict[str, List[Dict[str, Any]]] = {}
        self.notify_before_accept = notify_before_accept

    def add_job(
        self,
        thing_name: str,
        job_id: str,
        document: Dict[str, Any],
    ) -> None:
        with self._cond:
            before = self._next_job(thing_name)
            self._jobs.setdefault(thing_name, []).append(
                dict(
                    jobId=job_id,
                    jobDocument=document,
                    status="QUEUED",
                    versionNumber=1,
                    executionNumber=1,
                )
            )
            after = self._next_job(thing_name)
            self._cond.notify_all()
        if after is not before:
            self._publish([self._notify_next(thing_name, after)])

    def set_status(self, thing_name: str, job_id: str, status: str) -> None:
        """Change a job execution from the cloud side, e.g. cancel or time out."""
        with self._cond:
            before = self._next_job(thing_name)
            self._find(thing_name, job_id)["status"] = status
            after = self._next_job(thing_name)
            self._cond.notify_all()
        if after is not before:
            self._publish([self._notify_next(thing_name, after)])

    def job(self, thing_name: str, job_id: str) -> Dict[str, Any]:
        with self._cond:
            return deepcopy(self._find(thing_name, job_id))

    def wait_for_status(
        self, thing_name: str, job_id: str, status: str, timeout: float = 2.0
    ) -> None:
        self.wait_until(
            lambda: self._find(thing_name, job_id)["status"] == status, timeout
        )

    def _find(self, thing_name: str, job_id: str) -> Dict[str, Any]:
        for job in self._jobs.get(thing_name, []):
            if job["jobId"] == job_id:
                return job
        raise KeyError(job_id)

    def _next_job(self, thing_name: str) -> Optional[Dict[str, Any]]:
        jobs = [
            j
            for j in self._jobs.get(thing_name, [])
            if j["status"] not in self.TERMINAL
        ]
        in_progress = [j for j in jobs if j["status"] == "IN_PROGRESS"]
        return (in_progress or jobs or [None])[0]

    def _execution(self, thing_name: str, job: Dict[str, Any]) -> Dict[str, Any]:
        now = int(time.time())
        execution = dict(
            deepcopy(job), thingName=thing_name, queuedAt=now, lastUpdatedAt=now
        )
        if job["status"] != "QUEUED":
            execution["startedAt"] = now
        return execution

    def _notify_next(self, thing_name: str, job: Optional[Dict[str, Any]]) -> Message:
        event: Dict[str, Any] = dict(timestamp=int(time.time()))
        if job is not None:
            event["execution"] = self._execution(thing_name, job)
        return (f"$aws/things/{thing_name}/jobs/notify-next", _encode(event))

    def handle(self, topic: str, payload: bytes) -> List[Message]:
        request = json.loads(payload) if payload else {}
        match = self._START_NEXT.match(topic)
        if match is not None:
            return self._start_next(topic, match.group(1), request)
        match = self._UPDATE.match(topic)
        if match is not None:
            return self._update(topic, match.group(1), match.group(2), request)
        return []

    def _start_next(
        self, topic: str, thing_name: str, request: Dict[str, Any]
    ) -> List[Message]:
        with self._cond:
            error = self._take_rejection("start-next")
            if error is not None:
                error.setdefault("timestamp", int(time.time()))
                return [(f"{topic}/rejected", _encode(error))]
            job = self._next_job(thing_name)
            response: Dict[str, Any] = dict(timestamp=int(time.time()))
            if job is not None:
                job["status"] = "IN_PROGRESS"
                job["versionNumber"] += 1
                response["execution"] = self._execution(thing_name, job)
            self._cond.notify_all()
        if "clientToken" in request:
            response["clientToken"] = request["clientToken"]
        return [(f"{topic}/accepted", _encode(response))]

    def _update(
        self, topic: str, thing_name: str, job_id: str, request: Dict[str, Any]
    ) -> List[Message]:
        with self._cond:
            error = self._take_rejection("update")
            try:
                job = self._find(thing_name, job_id)
            except KeyError:
                error = error or dict(
                    code="ResourceNotFound", message=f"Job {job_id} not found"
                )
            if error is not None:
                error.setdefault("timestamp", int(time.time()))
                return [(f"{topic}/rejected", _encode(error))]

            before = self._next_job(thing_name)
            job["status"] = request["status"]
            if "statusDetails" in request:
                job["statusDetails"] = request["statusDetails"]
            job["versionNumber"] += 1
            after = self._next_job(thing_name)
            self._cond.notify_all()

        messages = [(f"{topic}/accepted", _encode(dict(timestamp=int(time.time()))))]
        if after is not before:
            notify = self._notify_next(thing_name, after)
            if self.notify_before_accept:
                messages.insert(0, notify)
            else:
                messages.append(notify)
        return messages
