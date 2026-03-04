from unittest.mock import MagicMock, patch

from awscrt import mqtt

import awsiotclient.classic_shadow as classic_shadow


class TestClassicShadowClient:
    @patch("awsiotclient.classic_shadow.iotshadow.IotShadowClient")
    def test_subscribes_on_init(self, MockShadowClient, make_classic_shadow_client):
        mock_client = make_classic_shadow_client()
        MockShadowClient.return_value = mock_client

        conn = MagicMock(spec=mqtt.Connection)
        classic_shadow.client(conn, "thing1", "prop1")

        mock_client.subscribe_to_shadow_delta_updated_events.assert_called_once()
        mock_client.subscribe_to_update_shadow_accepted.assert_called_once()
        mock_client.subscribe_to_update_shadow_rejected.assert_called_once()
        mock_client.subscribe_to_get_shadow_accepted.assert_called_once()
        mock_client.subscribe_to_get_shadow_rejected.assert_called_once()

    @patch("awsiotclient.classic_shadow.iotshadow.IotShadowClient")
    def test_publishes_get_shadow_on_init(self, MockShadowClient, make_classic_shadow_client):
        mock_client = make_classic_shadow_client()
        MockShadowClient.return_value = mock_client

        conn = MagicMock(spec=mqtt.Connection)
        classic_shadow.client(conn, "thing1", "prop1")

        mock_client.publish_get_shadow.assert_called_once()

    @patch("awsiotclient.classic_shadow.iotshadow.IotShadowClient")
    def test_update_shadow_request_publishes(
        self, MockShadowClient, make_classic_shadow_client
    ):
        mock_client = make_classic_shadow_client()
        MockShadowClient.return_value = mock_client

        conn = MagicMock(spec=mqtt.Connection)
        c = classic_shadow.client(conn, "thing1", "prop1")

        mock_client.publish_update_shadow.reset_mock()
        c.change_reported_value({"temp": 25})

        mock_client.publish_update_shadow.assert_called_once()

    @patch("awsiotclient.classic_shadow.iotshadow.IotShadowClient")
    def test_update_noop_when_both_none(self, MockShadowClient, make_classic_shadow_client):
        mock_client = make_classic_shadow_client()
        MockShadowClient.return_value = mock_client

        conn = MagicMock(spec=mqtt.Connection)
        c = classic_shadow.client(conn, "thing1", "prop1")

        mock_client.publish_update_shadow.reset_mock()
        c.update_shadow_request(desired=None, reported=None)

        mock_client.publish_update_shadow.assert_not_called()
