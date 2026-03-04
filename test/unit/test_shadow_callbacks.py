from concurrent.futures import Future
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from awscrt import mqtt

import awsiotclient.classic_shadow as classic_shadow
from awsiotclient import ExceptionAwsIotClient
from awsiotclient.shadow import ExceptionAwsIotShadowInvalidDelta


class TestShadowCallbacks:
    @patch("awsiotclient.classic_shadow.iotshadow.IotShadowClient")
    def test_delta_ignored_when_state_is_none(
        self, MockShadowClient, make_classic_shadow_client, make_done_future
    ):
        mock_client = make_classic_shadow_client()
        MockShadowClient.return_value = mock_client

        conn = MagicMock(spec=mqtt.Connection)
        c = classic_shadow.client(conn, "thing1", "prop1")

        c.change_reported_value = MagicMock(return_value=make_done_future())
        c.on_shadow_delta_updated(SimpleNamespace(state=None))

        c.change_reported_value.assert_not_called()

    @patch("awsiotclient.classic_shadow.iotshadow.IotShadowClient")
    def test_delta_deleted_property_resets_reported(
        self, MockShadowClient, make_classic_shadow_client, make_done_future
    ):
        mock_client = make_classic_shadow_client()
        MockShadowClient.return_value = mock_client

        conn = MagicMock(spec=mqtt.Connection)
        c = classic_shadow.client(conn, "thing1", "prop1")

        c.change_reported_value = MagicMock(return_value=make_done_future())
        c.on_shadow_delta_updated(SimpleNamespace(state={"other": "value"}))

        c.change_reported_value.assert_called_once_with(None)

    @patch("awsiotclient.classic_shadow.iotshadow.IotShadowClient")
    def test_delta_invalid_request_resets_desired(
        self, MockShadowClient, make_classic_shadow_client, make_done_future
    ):
        mock_client = make_classic_shadow_client()
        MockShadowClient.return_value = mock_client

        conn = MagicMock(spec=mqtt.Connection)

        def invalid_delta(*args, **kwargs):
            raise ExceptionAwsIotShadowInvalidDelta("invalid")

        c = classic_shadow.client(conn, "thing1", "prop1", delta_func=invalid_delta)

        c.change_desired_value = MagicMock(return_value=make_done_future())
        c.on_shadow_delta_updated(SimpleNamespace(state={"prop1": 123}))

        c.change_desired_value.assert_called_once_with(None)

    @patch("awsiotclient.classic_shadow.iotshadow.IotShadowClient")
    def test_delta_unexpected_exception_is_reraised(
        self, MockShadowClient, make_classic_shadow_client
    ):
        mock_client = make_classic_shadow_client()
        MockShadowClient.return_value = mock_client

        conn = MagicMock(spec=mqtt.Connection)

        def failing_delta(*args, **kwargs):
            raise RuntimeError("unexpected delta error")

        c = classic_shadow.client(conn, "thing1", "prop1", delta_func=failing_delta)

        with pytest.raises(RuntimeError):
            c.on_shadow_delta_updated(SimpleNamespace(state={"prop1": 123}))

    @patch("awsiotclient.classic_shadow.iotshadow.IotShadowClient")
    def test_get_shadow_accepted_uses_reported_state(
        self, MockShadowClient, make_classic_shadow_client
    ):
        mock_client = make_classic_shadow_client()
        MockShadowClient.return_value = mock_client

        conn = MagicMock(spec=mqtt.Connection)
        c = classic_shadow.client(conn, "thing1", "prop1")

        response = SimpleNamespace(
            state=SimpleNamespace(delta=None, reported={"prop1": "on"})
        )
        c.on_get_shadow_accepted(response)

        assert c.locked_data.get_reported_value() == "on"

    @patch("awsiotclient.classic_shadow.iotshadow.IotShadowClient")
    def test_get_shadow_accepted_ignores_when_delta_present(
        self, MockShadowClient, make_classic_shadow_client, make_done_future
    ):
        mock_client = make_classic_shadow_client()
        MockShadowClient.return_value = mock_client

        conn = MagicMock(spec=mqtt.Connection)
        c = classic_shadow.client(conn, "thing1", "prop1")

        c.change_reported_value = MagicMock(return_value=make_done_future())
        response = SimpleNamespace(
            state=SimpleNamespace(delta={"prop1": "pending"}, reported={"prop1": "on"})
        )
        c.on_get_shadow_accepted(response)

        c.change_reported_value.assert_not_called()

    @patch("awsiotclient.classic_shadow.iotshadow.IotShadowClient")
    def test_get_shadow_accepted_sets_default_when_property_missing(
        self, MockShadowClient, make_classic_shadow_client, make_done_future
    ):
        mock_client = make_classic_shadow_client()
        MockShadowClient.return_value = mock_client

        conn = MagicMock(spec=mqtt.Connection)
        c = classic_shadow.client(conn, "thing1", "prop1")

        c.change_reported_value = MagicMock(return_value=make_done_future())
        response = SimpleNamespace(state=SimpleNamespace(delta=None, reported={"other": 1}))
        c.on_get_shadow_accepted(response)

        c.change_reported_value.assert_called_once_with(None)

    @patch("awsiotclient.classic_shadow.iotshadow.IotShadowClient")
    def test_get_shadow_accepted_returns_early_when_reported_already_set(
        self, MockShadowClient, make_classic_shadow_client, make_done_future
    ):
        mock_client = make_classic_shadow_client()
        MockShadowClient.return_value = mock_client

        conn = MagicMock(spec=mqtt.Connection)
        c = classic_shadow.client(conn, "thing1", "prop1")
        c.locked_data.set_reported_value("already-set")

        c.change_reported_value = MagicMock(return_value=make_done_future())
        response = SimpleNamespace(state=SimpleNamespace(delta=None, reported={"prop1": "new"}))
        c.on_get_shadow_accepted(response)

        c.change_reported_value.assert_not_called()
        assert c.locked_data.get_reported_value() == "already-set"

    @patch("awsiotclient.classic_shadow.iotshadow.IotShadowClient")
    def test_get_shadow_accepted_reraises_unexpected_errors(
        self, MockShadowClient, make_classic_shadow_client
    ):
        mock_client = make_classic_shadow_client()
        MockShadowClient.return_value = mock_client

        class ExplodingMapping:
            def get(self, key):
                raise RuntimeError(f"forced failure: {key}")

        conn = MagicMock(spec=mqtt.Connection)
        c = classic_shadow.client(conn, "thing1", "prop1")

        bad_response = SimpleNamespace(
            state=SimpleNamespace(delta=ExplodingMapping(), reported=None)
        )
        with pytest.raises(RuntimeError, match="forced failure"):
            c.on_get_shadow_accepted(bad_response)

    @patch("awsiotclient.classic_shadow.iotshadow.IotShadowClient")
    def test_get_shadow_rejected_404_sets_default(
        self, MockShadowClient, make_classic_shadow_client, make_done_future
    ):
        mock_client = make_classic_shadow_client()
        MockShadowClient.return_value = mock_client

        conn = MagicMock(spec=mqtt.Connection)
        c = classic_shadow.client(conn, "thing1", "prop1")

        c.change_reported_value = MagicMock(return_value=make_done_future())
        c.on_get_shadow_rejected(SimpleNamespace(code=404, message="not found"))

        c.change_reported_value.assert_called_once_with(None)

    @patch("awsiotclient.classic_shadow.iotshadow.IotShadowClient")
    def test_get_shadow_rejected_non_404_raises(
        self, MockShadowClient, make_classic_shadow_client
    ):
        mock_client = make_classic_shadow_client()
        MockShadowClient.return_value = mock_client

        conn = MagicMock(spec=mqtt.Connection)
        c = classic_shadow.client(conn, "thing1", "prop1")

        with pytest.raises(ExceptionAwsIotClient):
            c.on_get_shadow_rejected(SimpleNamespace(code=500, message="error"))

    @patch("awsiotclient.classic_shadow.iotshadow.IotShadowClient")
    def test_update_shadow_accepted_sets_desired_and_calls_callback(
        self, MockShadowClient, make_classic_shadow_client
    ):
        mock_client = make_classic_shadow_client()
        MockShadowClient.return_value = mock_client

        conn = MagicMock(spec=mqtt.Connection)
        desired_func = MagicMock()
        c = classic_shadow.client(
            conn,
            "thing1",
            "prop1",
            desired_func=desired_func,
        )

        response = SimpleNamespace(
            state=SimpleNamespace(reported={"prop1": 1}, desired={"prop1": 2})
        )
        c.on_update_shadow_accepted(response)

        assert c.locked_data.get_desired_value() == {"prop1": 2}
        desired_func.assert_called_once_with("thing1", "prop1", {"prop1": 2})

    @patch("awsiotclient.classic_shadow.iotshadow.IotShadowClient")
    def test_update_shadow_accepted_reraises_when_desired_callback_fails(
        self, MockShadowClient, make_classic_shadow_client
    ):
        mock_client = make_classic_shadow_client()
        MockShadowClient.return_value = mock_client

        conn = MagicMock(spec=mqtt.Connection)

        def failing_desired(*args, **kwargs):
            raise RuntimeError("desired callback failed")

        c = classic_shadow.client(
            conn,
            "thing1",
            "prop1",
            desired_func=failing_desired,
        )

        response = SimpleNamespace(
            state=SimpleNamespace(reported={"prop1": 1}, desired={"prop1": 2})
        )
        with pytest.raises(RuntimeError):
            c.on_update_shadow_accepted(response)

    @patch("awsiotclient.classic_shadow.iotshadow.IotShadowClient")
    def test_update_shadow_rejected_raises(self, MockShadowClient, make_classic_shadow_client):
        mock_client = make_classic_shadow_client()
        MockShadowClient.return_value = mock_client

        conn = MagicMock(spec=mqtt.Connection)
        c = classic_shadow.client(conn, "thing1", "prop1")

        with pytest.raises(ExceptionAwsIotClient):
            c.on_update_shadow_rejected(SimpleNamespace(code=409, message="conflict"))

    @patch("awsiotclient.classic_shadow.iotshadow.IotShadowClient")
    def test_on_publish_update_shadow_raises_when_future_fails(
        self, MockShadowClient, make_classic_shadow_client
    ):
        mock_client = make_classic_shadow_client()
        MockShadowClient.return_value = mock_client

        conn = MagicMock(spec=mqtt.Connection)
        c = classic_shadow.client(conn, "thing1", "prop1")

        failed = Future()
        failed.set_exception(RuntimeError("publish failed"))

        with pytest.raises(RuntimeError):
            c.on_publish_update_shadow(failed)

    @patch("awsiotclient.classic_shadow.iotshadow.IotShadowClient")
    def test_change_both_values_publishes_update(
        self, MockShadowClient, make_classic_shadow_client
    ):
        mock_client = make_classic_shadow_client()
        MockShadowClient.return_value = mock_client

        conn = MagicMock(spec=mqtt.Connection)
        c = classic_shadow.client(conn, "thing1", "prop1")

        mock_client.publish_update_shadow.reset_mock()
        c.change_both_values(desired_value={"mode": "on"}, reported_value={"temp": 25})

        mock_client.publish_update_shadow.assert_called_once()

    @patch("awsiotclient.classic_shadow.iotshadow.IotShadowClient")
    def test_change_desired_value_publishes_update(
        self, MockShadowClient, make_classic_shadow_client
    ):
        mock_client = make_classic_shadow_client()
        MockShadowClient.return_value = mock_client

        conn = MagicMock(spec=mqtt.Connection)
        c = classic_shadow.client(conn, "thing1", "prop1")

        mock_client.publish_update_shadow.reset_mock()
        c.change_desired_value({"mode": "eco"})

        mock_client.publish_update_shadow.assert_called_once()
        request = mock_client.publish_update_shadow.call_args[0][0]
        assert request.state.desired == {"prop1": {"mode": "eco"}}
