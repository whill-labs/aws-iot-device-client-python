"""Tests for awsiotclient.mqtt.

init() runs the real awsiot connection builder. Building a connection does
not touch the network; only connect() would.
"""

import shutil
import subprocess
from os.path import expanduser
from pathlib import Path

import pytest
from awscrt import mqtt as crt_mqtt

from awsiotclient import mqtt

from .fakes import completed

ROOT_CA = str(Path(__file__).parent.parent / "e2e" / "certs" / "AmazonRootCA1.pem")


def proxy_options(connection: crt_mqtt.Connection):
    # awscrt renamed websocket_proxy_options to proxy_options.
    if hasattr(connection, "proxy_options"):
        return connection.proxy_options
    return connection.websocket_proxy_options


@pytest.fixture(scope="module")
def device_cert(tmp_path_factory: pytest.TempPathFactory):
    if shutil.which("openssl") is None:
        pytest.skip("openssl is required to create a throwaway device certificate")
    directory = tmp_path_factory.mktemp("cert")
    cert, key = directory / "cert.pem", directory / "key.pem"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-subj",
            "/CN=awsiotclient-test",
            "-keyout",
            str(key),
            "-out",
            str(cert),
        ],
        check=True,
        capture_output=True,
    )
    return str(cert), str(key)


class TestConnectionParams:
    def test_paths_expand_the_home_directory(self):
        params = mqtt.ConnectionParams(
            root_ca="~/ca.pem", cert="~/cert.pem", key="~/key.pem"
        )

        assert (params.root_ca, params.cert, params.key) == (
            expanduser("~/ca.pem"),
            expanduser("~/cert.pem"),
            expanduser("~/key.pem"),
        )

    def test_default_client_ids_are_unique(self):
        # Two connections with one client ID keep disconnecting each other.
        ids = {mqtt.ConnectionParams().client_id for _ in range(3)}

        assert len(ids) == 3
        assert all(i.startswith("mqtt-") for i in ids)

    def test_explicit_client_id_is_kept(self):
        assert mqtt.ConnectionParams(client_id="device-1").client_id == "device-1"


class TestInit:
    def test_mtls(self, device_cert):
        cert, key = device_cert
        params = mqtt.ConnectionParams(
            endpoint="example.invalid",
            root_ca=ROOT_CA,
            cert=cert,
            key=key,
            client_id="device-1",
        )

        connection = mqtt.init(params)

        assert isinstance(connection, crt_mqtt.Connection)
        assert connection.host_name == "example.invalid"
        assert connection.client_id == "device-1"
        assert connection.clean_session is False
        assert connection.keep_alive_secs == 6

    def test_websocket(self):
        params = mqtt.ConnectionParams(
            endpoint="example.invalid",
            root_ca=ROOT_CA,
            use_websocket=True,
            client_id="device-1",
        )

        connection = mqtt.init(params)

        assert connection.host_name == "example.invalid"
        assert connection.client_id == "device-1"
        assert connection.clean_session is False
        assert proxy_options(connection) is None

    def test_websocket_through_a_proxy(self):
        params = mqtt.ConnectionParams(
            endpoint="example.invalid",
            root_ca=ROOT_CA,
            use_websocket=True,
            proxy_host="proxy.invalid",
            proxy_port=3128,
        )

        connection = mqtt.init(params)

        assert (
            proxy_options(connection).host_name,
            proxy_options(connection).port,
        ) == (
            "proxy.invalid",
            3128,
        )


class TestConnectionResumed:
    def test_resubscribes_when_the_session_was_lost(self, broker, connection):
        connection.subscribe("a/b", crt_mqtt.QoS.AT_LEAST_ONCE)

        mqtt.on_connection_resumed(
            connection, crt_mqtt.ConnectReturnCode.ACCEPTED, session_present=False
        )

        assert connection.resubscribe_count == 1

    @pytest.mark.parametrize(
        "return_code, session_present",
        [
            (crt_mqtt.ConnectReturnCode.ACCEPTED, True),
            (crt_mqtt.ConnectReturnCode.NOT_AUTHORIZED, False),
        ],
    )
    def test_does_not_resubscribe_otherwise(
        self, broker, connection, return_code, session_present
    ):
        mqtt.on_connection_resumed(
            connection, return_code, session_present=session_present
        )

        assert connection.resubscribe_count == 0

    def test_rejected_resubscription_is_an_error(self):
        result = completed(
            dict(
                packet_id=1, topics=[("a/b", crt_mqtt.QoS.AT_LEAST_ONCE), ("c/d", None)]
            )
        )

        with pytest.raises(mqtt.ExceptionAwsIotMqtt, match="c/d"):
            mqtt.on_resubscribe_complete(result)

    def test_accepted_resubscription_is_fine(self):
        mqtt.on_resubscribe_complete(
            completed(dict(packet_id=1, topics=[("a/b", crt_mqtt.QoS.AT_LEAST_ONCE)]))
        )
