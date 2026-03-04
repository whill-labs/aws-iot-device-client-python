from os.path import expanduser
from unittest.mock import MagicMock, patch

import pytest

from awscrt import mqtt

from awsiotclient.mqtt import (
    ConnectionParams,
    ExceptionAwsIotMqtt,
    init,
    on_connection_interrupted,
    on_connection_resumed,
    on_resubscribe_complete,
)


class TestConnectionParams:
    def test_defaults(self):
        p = ConnectionParams()
        assert p.endpoint == ""
        assert p.signing_region == "ap-northeast-1"
        assert p.use_websocket is False
        assert p.proxy_host is None
        assert p.proxy_port == 8080

    def test_expands_home(self):
        p = ConnectionParams(root_ca="~/root.pem", cert="~/cert.pem", key="~/key.pem")
        assert p.root_ca == expanduser("~/root.pem")
        assert p.cert == expanduser("~/cert.pem")
        assert p.key == expanduser("~/key.pem")


class TestInit:
    @patch("awsiotclient.mqtt.mqtt_connection_builder")
    def test_mtls(self, mock_builder):
        mock_builder.mtls_from_path.return_value = MagicMock()
        params = ConnectionParams(endpoint="example.com", cert="/cert", key="/key", root_ca="/ca")
        result = init(params)

        mock_builder.mtls_from_path.assert_called_once()
        assert result == mock_builder.mtls_from_path.return_value

    @patch("awsiotclient.mqtt.mqtt_connection_builder")
    @patch("awsiotclient.mqtt.auth")
    def test_websocket(self, mock_auth, mock_builder):
        mock_builder.websockets_with_default_aws_signing.return_value = MagicMock()
        params = ConnectionParams(endpoint="example.com", use_websocket=True, root_ca="/ca")
        result = init(params)

        mock_builder.websockets_with_default_aws_signing.assert_called_once()
        assert result == mock_builder.websockets_with_default_aws_signing.return_value


class TestCallbacks:
    def test_on_resubscribe_complete_raises_on_rejected(self, make_done_future):
        future = make_done_future({"topics": [("my/topic", None)]})

        with pytest.raises(ExceptionAwsIotMqtt):
            on_resubscribe_complete(future)

    def test_on_resubscribe_complete_succeeds(self, make_done_future):
        future = make_done_future({"topics": [("my/topic", mqtt.QoS.AT_LEAST_ONCE)]})

        on_resubscribe_complete(future)  # should not raise


class TestConnectionCallbacks:
    def test_on_connection_interrupted(self):
        conn = MagicMock(spec=mqtt.Connection)
        error = RuntimeError("network error")

        on_connection_interrupted(conn, error)

    def test_on_connection_resumed_resubscribes_when_session_not_present(self):
        conn = MagicMock(spec=mqtt.Connection)
        resubscribe_future = MagicMock()
        conn.resubscribe_existing_topics.return_value = (resubscribe_future, 1)

        on_connection_resumed(
            conn,
            mqtt.ConnectReturnCode.ACCEPTED,
            session_present=False,
        )

        conn.resubscribe_existing_topics.assert_called_once()
        resubscribe_future.add_done_callback.assert_called_once_with(
            on_resubscribe_complete
        )

    def test_on_connection_resumed_skips_resubscribe_when_session_present(self):
        conn = MagicMock(spec=mqtt.Connection)

        on_connection_resumed(
            conn,
            mqtt.ConnectReturnCode.ACCEPTED,
            session_present=True,
        )

        conn.resubscribe_existing_topics.assert_not_called()


class TestWebsocketProxy:
    @patch("awsiotclient.mqtt.http.HttpProxyOptions")
    @patch("awsiotclient.mqtt.mqtt_connection_builder")
    @patch("awsiotclient.mqtt.auth")
    def test_init_websocket_with_proxy_options(self, mock_auth, mock_builder, MockProxy):
        proxy_options = MagicMock()
        MockProxy.return_value = proxy_options
        mock_builder.websockets_with_default_aws_signing.return_value = MagicMock()

        params = ConnectionParams(
            endpoint="example.com",
            use_websocket=True,
            root_ca="/ca",
            proxy_host="proxy.local",
            proxy_port=3128,
        )
        result = init(params)

        MockProxy.assert_called_once_with(host_name="proxy.local", port=3128)
        mock_builder.websockets_with_default_aws_signing.assert_called_once()
        assert (
            mock_builder.websockets_with_default_aws_signing.call_args.kwargs[
                "websocket_proxy_options"
            ]
            == proxy_options
        )
        assert result == mock_builder.websockets_with_default_aws_signing.return_value
