"""Contract tests for classic_shadow.client and named_shadow.client.

The clients run against FakeShadowService. "cloud" below means the shadow
document held by the fake service.
"""

from typing import Any, List, Optional, Tuple

import pytest
from awscrt import mqtt
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from awsiotclient import ExceptionAwsIotClient, classic_shadow, named_shadow
from awsiotclient.shadow import ExceptionAwsIotShadowInvalidDelta

from .fakes import FakeBroker, FakeConnection, FakeShadowService
from .test_dictdiff import documents

THING = "thing-1"


class Classic:
    """A classic shadow client owns one top-level property of the document."""

    label = "prop"
    shadow_name: Optional[str] = None

    @staticmethod
    def make(connection: FakeConnection, **kwargs: Any) -> classic_shadow.client:
        return classic_shadow.client(connection, THING, "prop", **kwargs)

    @staticmethod
    def wrap(value: Any) -> Any:
        return {"prop": value}

    @staticmethod
    def cloud(service: FakeShadowService, section: str) -> Any:
        doc = service.document(THING)
        return None if doc is None else doc[section].get("prop")


class Named:
    """A named shadow client owns the whole document of its shadow."""

    label = "shadow-1"
    shadow_name: Optional[str] = "shadow-1"

    @staticmethod
    def make(connection: FakeConnection, **kwargs: Any) -> named_shadow.client:
        return named_shadow.client(connection, THING, "shadow-1", **kwargs)

    @staticmethod
    def wrap(value: Any) -> Any:
        return value

    @staticmethod
    def cloud(service: FakeShadowService, section: str) -> Any:
        doc = service.document(THING, "shadow-1")
        return None if doc is None else doc[section] or None


@pytest.fixture(params=[Classic, Named], ids=["classic", "named"])
def kind(request: pytest.FixtureRequest) -> Any:
    return request.param


class Recorder:
    def __init__(self) -> None:
        self.calls: List[Tuple[str, str, Any]] = []

    def __call__(self, thing_name: str, label: str, value: Any) -> None:
        self.calls.append((thing_name, label, value))

    @property
    def values(self) -> List[Any]:
        return [value for _, _, value in self.calls]


def update_payloads(broker: FakeBroker, kind: Any) -> List[Any]:
    topic = FakeShadowService.base_topic(THING, kind.shadow_name) + "/update"
    return [p["state"] for p in broker.payloads(topic)]


def set_desired_elsewhere(service: FakeShadowService, kind: Any, value: Any) -> None:
    service.update(THING, kind.shadow_name, desired=kind.wrap(value))


class TestInitialization:
    def test_subscribes_to_every_response_topic(
        self, kind, broker, shadow_service, connection
    ):
        kind.make(connection)

        base = FakeShadowService.base_topic(THING, kind.shadow_name)
        assert set(connection.subscriptions) == {
            f"{base}/update/delta",
            f"{base}/update/accepted",
            f"{base}/update/rejected",
            f"{base}/get/accepted",
            f"{base}/get/rejected",
        }

    def test_missing_shadow_is_not_created_implicitly(
        self, kind, broker, shadow_service, connection
    ):
        kind.make(connection)

        assert update_payloads(broker, kind) == []
        assert shadow_service.document(THING, kind.shadow_name) is None

    def test_adopts_reported_value_already_in_the_cloud(
        self, kind, broker, shadow_service, connection
    ):
        shadow_service.update(
            THING, kind.shadow_name, reported=kind.wrap({"a": 1, "b": 2})
        )
        client = kind.make(connection)

        client.change_reported_value({"a": 1, "b": 2}).result()
        assert (
            update_payloads(broker, kind) == []
        ), "an unchanged value must not be published"

        client.change_reported_value({"a": 1, "b": 3}).result()
        assert update_payloads(broker, kind) == [{"reported": kind.wrap({"b": 3})}]

    def test_pending_delta_is_passed_to_delta_func(
        self, kind, broker, shadow_service, connection
    ):
        shadow_service.update(
            THING,
            kind.shadow_name,
            desired=kind.wrap({"a": 1}),
            reported=kind.wrap({"a": 0}),
        )
        delta_func = Recorder()

        kind.make(connection, delta_func=delta_func)

        assert delta_func.calls == [(THING, kind.label, {"a": 1})]

    def test_get_rejected_for_another_reason_is_surfaced(
        self, kind, broker, shadow_service, connection
    ):
        shadow_service.reject_next("get", code=500, message="internal error")

        kind.make(connection)

        errors = broker.take_callback_errors()
        assert len(errors) == 1 and isinstance(errors[0], ExceptionAwsIotClient)

    def test_pending_delta_survives_a_late_get_response(
        self, kind, broker, shadow_service, connection
    ):
        shadow_service.update(THING, kind.shadow_name, desired=kind.wrap({"a": 1}))
        shadow_service.hold_get_responses()
        delta_func = Recorder()
        client = kind.make(connection, delta_func=delta_func)

        client.change_reported_value({"a": 0, "b": 0}).result()
        shadow_service.release_get_responses()

        assert delta_func.values == [{"a": 1}]
        client.change_reported_value({"a": 0, "b": 0}).result()
        assert kind.cloud(shadow_service, "reported") == {
            "a": 0,
            "b": 0,
        }, "a late get must not replace the newer reported value"

    def test_subscription_failure_is_raised(
        self, kind, broker, shadow_service, connection
    ):
        base = FakeShadowService.base_topic(THING, kind.shadow_name)
        connection.reject_subscription(f"{base}/get/accepted")

        with pytest.raises(mqtt.SubscribeError):
            kind.make(connection)


class TestReportedValue:
    def test_publishes_only_the_difference(
        self, kind, broker, shadow_service, connection
    ):
        client = kind.make(connection)

        client.change_reported_value({"a": 1, "b": {"x": 1, "y": 2}}).result()
        client.change_reported_value(
            {"a": 1, "b": {"x": 1, "y": 3}, "c": True}
        ).result()
        client.change_reported_value({"b": {"x": 1, "y": 3}, "c": True}).result()

        assert update_payloads(broker, kind) == [
            {"reported": kind.wrap({"a": 1, "b": {"x": 1, "y": 2}})},
            {"reported": kind.wrap({"b": {"y": 3}, "c": True})},
            {"reported": kind.wrap({"a": None})},
        ]
        assert kind.cloud(shadow_service, "reported") == {
            "b": {"x": 1, "y": 3},
            "c": True,
        }

    def test_publishes_the_full_document_when_requested(
        self, kind, broker, shadow_service, connection
    ):
        client = kind.make(connection, publish_full_doc=True)

        client.change_reported_value({"a": 1, "b": 2}).result()
        client.change_reported_value({"a": 1, "b": 3}).result()

        assert update_payloads(broker, kind) == [
            {"reported": kind.wrap({"a": 1, "b": 2})},
            {"reported": kind.wrap({"a": 1, "b": 3})},
        ]

    def test_unchanged_value_returns_a_completed_future(
        self, kind, broker, shadow_service, connection
    ):
        client = kind.make(connection)
        client.change_reported_value({"a": 1}).result()

        future = client.change_reported_value({"a": 1})

        assert future.done() and future.result() is None
        assert len(update_payloads(broker, kind)) == 1

    def test_publish_failure_is_returned_through_the_future(
        self, kind, broker, shadow_service, connection
    ):
        client = kind.make(connection)
        base = FakeShadowService.base_topic(THING, kind.shadow_name)
        connection.fail_next_publish(f"{base}/update")

        with pytest.raises(RuntimeError, match="publish failed"):
            client.change_reported_value({"a": 1}).result()

    def test_rejected_update_is_surfaced(
        self, kind, broker, shadow_service, connection
    ):
        client = kind.make(connection)
        shadow_service.reject_next("update", code=400, message="bad request")

        client.change_reported_value({"a": 1}).result()

        errors = broker.take_callback_errors()
        assert len(errors) == 1 and isinstance(errors[0], ExceptionAwsIotClient)

    @settings(
        max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture]
    )
    @given(st.lists(documents, min_size=1, max_size=5))
    def test_cloud_follows_every_change(self, kind, values):
        broker = FakeBroker()
        service = FakeShadowService()
        broker.add_service(service)
        client = kind.make(broker.connect())

        for value in values:
            client.change_reported_value(value).result()
            assert kind.cloud(service, "reported") == value
        assert broker.take_callback_errors() == []


class TestDesiredValue:
    @settings(
        max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture]
    )
    @given(st.lists(documents, min_size=1, max_size=5))
    def test_cloud_follows_every_change(self, kind, values):
        broker = FakeBroker()
        service = FakeShadowService()
        broker.add_service(service)
        client = kind.make(broker.connect())

        for value in values:
            client.change_desired_value(value).result()
            assert kind.cloud(service, "desired") == value
        assert broker.take_callback_errors() == []

    def test_desired_func_receives_the_whole_desired_value(
        self, kind, broker, shadow_service, connection
    ):
        desired_func = Recorder()
        client = kind.make(connection, desired_func=desired_func)

        client.change_desired_value({"a": 1, "b": 2}).result()
        client.change_desired_value({"a": 1, "b": 3}).result()

        assert desired_func.calls == [
            (THING, kind.label, {"a": 1, "b": 2}),
            (THING, kind.label, {"a": 1, "b": 3}),
        ]

    def test_desired_func_sees_changes_made_elsewhere(
        self, kind, broker, shadow_service, connection
    ):
        desired_func = Recorder()
        client = kind.make(connection, desired_func=desired_func)
        client.change_desired_value({"a": 1}).result()

        set_desired_elsewhere(shadow_service, kind, {"b": 2})

        assert desired_func.values == [{"a": 1}, {"a": 1, "b": 2}]

    def test_change_both_values_publishes_one_update(
        self, kind, broker, shadow_service, connection
    ):
        client = kind.make(connection)

        client.change_both_values({"a": 1}, {"a": 0}).result()

        assert update_payloads(broker, kind) == [
            {"desired": kind.wrap({"a": 1}), "reported": kind.wrap({"a": 0})}
        ]
        assert kind.cloud(shadow_service, "delta") == {"a": 1}


class TestDelta:
    def test_delta_func_receives_the_delta(
        self, kind, broker, shadow_service, connection
    ):
        delta_func = Recorder()
        client = kind.make(connection, delta_func=delta_func)
        client.change_reported_value({"a": 1, "b": 1}).result()

        set_desired_elsewhere(shadow_service, kind, {"a": 2, "b": 1})

        assert delta_func.calls == [(THING, kind.label, {"a": 2})]

    def test_invalid_delta_clears_the_desired_value(
        self, kind, broker, shadow_service, connection
    ):
        def reject(thing_name: str, label: str, value: Any) -> None:
            raise ExceptionAwsIotShadowInvalidDelta(value)

        client = kind.make(connection, delta_func=reject)
        client.change_reported_value({"a": 1}).result()

        set_desired_elsewhere(shadow_service, kind, {"a": 2})

        assert kind.cloud(shadow_service, "delta") is None
        assert kind.cloud(shadow_service, "reported") == {"a": 1}

    def test_invalid_delta_keeps_the_valid_part_of_the_desired_value(
        self, kind, broker, shadow_service, connection
    ):
        def reject(thing_name: str, label: str, value: Any) -> None:
            raise ExceptionAwsIotShadowInvalidDelta(value)

        client = kind.make(connection, delta_func=reject)
        client.change_both_values(
            {"config": {"a": 1}}, {"config": {"a": 1, "b": 0}}
        ).result()

        set_desired_elsewhere(shadow_service, kind, {"config": {"a": 1, "b": 2}})

        assert kind.cloud(shadow_service, "delta") is None
        assert kind.cloud(shadow_service, "desired") == {"config": {"a": 1}}

    def test_delta_accepted_after_an_invalid_one(
        self, kind, broker, shadow_service, connection
    ):
        seen: List[Any] = []

        def delta_func(thing_name: str, label: str, value: Any) -> None:
            seen.append(value)
            if value == {"a": "invalid"}:
                raise ExceptionAwsIotShadowInvalidDelta(value)

        kind.make(connection, delta_func=delta_func)

        set_desired_elsewhere(shadow_service, kind, {"a": "invalid"})
        set_desired_elsewhere(shadow_service, kind, {"a": 2})

        assert seen == [{"a": "invalid"}, {"a": 2}]
        assert kind.cloud(shadow_service, "desired") == {"a": 2}

    def test_error_in_delta_func_is_not_swallowed(
        self, kind, broker, shadow_service, connection
    ):
        def broken(thing_name: str, label: str, value: Any) -> None:
            raise ValueError("boom")

        kind.make(connection, delta_func=broken)
        set_desired_elsewhere(shadow_service, kind, {"a": 1})

        errors = broker.take_callback_errors()
        assert [type(e) for e in errors] == [ValueError]


class TestClassicShadowSharesTheDocument:
    """Several classic clients may own different properties of one thing.

    Each client needs its own connection: subscribing to the same topic twice
    on one MQTT connection replaces the earlier callback.
    """

    @pytest.fixture
    def pair(self, broker, shadow_service):
        delta_a, delta_b = Recorder(), Recorder()
        client_a = classic_shadow.client(
            broker.connect(), THING, "a", delta_func=delta_a
        )
        client_b = classic_shadow.client(
            broker.connect(), THING, "b", delta_func=delta_b
        )
        client_a.change_reported_value({"x": 1}).result()
        client_b.change_reported_value({"y": 2}).result()
        return client_a, client_b, delta_a, delta_b

    def test_properties_are_reported_independently(self, pair, shadow_service):
        assert shadow_service.document(THING)["reported"] == {
            "a": {"x": 1},
            "b": {"y": 2},
        }

    def test_delta_goes_only_to_the_owner(self, pair, broker, shadow_service):
        client_a, client_b, delta_a, delta_b = pair
        published = len(update_payloads(broker, Classic))

        shadow_service.update(THING, desired={"a": {"x": 5}})

        assert delta_a.values == [{"x": 5}]
        assert delta_b.values == []
        assert (
            len(update_payloads(broker, Classic)) == published
        ), "b must not react to a's delta"

        client_b.change_reported_value({"y": 2}).result()
        assert (
            len(update_payloads(broker, Classic)) == published
        ), "b must still know its reported value"

    def test_desired_func_ignores_other_properties(
        self, broker, shadow_service, connection
    ):
        desired_func = Recorder()
        classic_shadow.client(connection, THING, "a", desired_func=desired_func)

        shadow_service.update(THING, desired={"b": {"y": 1}})

        assert desired_func.calls == []


def test_clients_do_not_share_state(broker, shadow_service):
    client_1 = named_shadow.client(broker.connect(), THING, "shadow-1")
    client_2 = named_shadow.client(broker.connect(), THING, "shadow-2")

    client_1.change_reported_value({"a": 1}).result()
    client_2.change_reported_value({"a": 1}).result()

    assert shadow_service.document(THING, "shadow-2")["reported"] == {"a": 1}
