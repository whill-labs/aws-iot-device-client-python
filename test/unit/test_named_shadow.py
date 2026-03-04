from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from awscrt import mqtt

import awsiotclient.named_shadow as named_shadow


class TestNamedShadowClient:
    @patch("awsiotclient.named_shadow.iotshadow.IotShadowClient")
    def test_subscribes_with_shadow_name(self, MockShadowClient, make_named_shadow_client):
        mock_client = make_named_shadow_client()
        MockShadowClient.return_value = mock_client

        conn = MagicMock(spec=mqtt.Connection)
        named_shadow.client(conn, "thing1", "my-shadow")

        mock_client.subscribe_to_named_shadow_delta_updated_events.assert_called_once()
        mock_client.subscribe_to_update_named_shadow_accepted.assert_called_once()
        mock_client.subscribe_to_get_named_shadow_accepted.assert_called_once()

    @patch("awsiotclient.named_shadow.iotshadow.IotShadowClient")
    def test_publishes_get_named_shadow_on_init(
        self, MockShadowClient, make_named_shadow_client
    ):
        mock_client = make_named_shadow_client()
        MockShadowClient.return_value = mock_client

        conn = MagicMock(spec=mqtt.Connection)
        named_shadow.client(conn, "thing1", "my-shadow")

        mock_client.publish_get_named_shadow.assert_called_once()

    @patch("awsiotclient.named_shadow.iotshadow.IotShadowClient")
    def test_update_shadow_request_publishes(
        self, MockShadowClient, make_named_shadow_client
    ):
        mock_client = make_named_shadow_client()
        MockShadowClient.return_value = mock_client

        conn = MagicMock(spec=mqtt.Connection)
        c = named_shadow.client(conn, "thing1", "my-shadow")

        mock_client.publish_update_named_shadow.reset_mock()
        c.change_reported_value({"temp": 25})

        mock_client.publish_update_named_shadow.assert_called_once()

    @patch("awsiotclient.named_shadow.iotshadow.IotShadowClient")
    def test_label_returns_shadow_name(self, MockShadowClient, make_named_shadow_client):
        mock_client = make_named_shadow_client()
        MockShadowClient.return_value = mock_client

        conn = MagicMock(spec=mqtt.Connection)
        c = named_shadow.client(conn, "thing1", "my-shadow")

        assert c.label() == "my-shadow"

    @patch("awsiotclient.named_shadow.iotshadow.IotShadowClient")
    def test_update_noop_when_both_none(self, MockShadowClient, make_named_shadow_client):
        mock_client = make_named_shadow_client()
        MockShadowClient.return_value = mock_client

        conn = MagicMock(spec=mqtt.Connection)
        c = named_shadow.client(conn, "thing1", "my-shadow")

        mock_client.publish_update_named_shadow.reset_mock()
        result = c.update_shadow_request(desired=None, reported=None)

        mock_client.publish_update_named_shadow.assert_not_called()
        assert result.result() is None

    @patch("awsiotclient.named_shadow.iotshadow.IotShadowClient")
    def test_get_accepted_uses_full_document(self, MockShadowClient, make_named_shadow_client):
        mock_client = make_named_shadow_client()
        MockShadowClient.return_value = mock_client

        conn = MagicMock(spec=mqtt.Connection)
        c = named_shadow.client(conn, "thing1", "my-shadow")

        response = SimpleNamespace(state=SimpleNamespace(delta=None, reported={"temp": 27}))
        c.on_get_shadow_accepted(response)

        assert c.locked_data.get_reported_value() == {"temp": 27}
