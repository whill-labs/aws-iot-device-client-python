from concurrent.futures import Future
from os.path import expanduser
from typing import Any, Dict, Optional
from uuid import uuid4

from awscrt import auth, exceptions, http, io, mqtt
from awsiot import mqtt_connection_builder

from . import ExceptionAwsIotClient, get_module_logger

logger = get_module_logger(__name__)
KwArgs = Optional[Dict[str, Any]]


class ExceptionAwsIotMqtt(ExceptionAwsIotClient):
    def __init__(self, *args: object) -> None:
        super().__init__(*args)


def on_connection_interrupted(
    connection: mqtt.Connection, error: exceptions.AwsCrtError, **kwargs: KwArgs
) -> None:
    logger.debug(f"Connection interrupted. error: {error}")


def on_connection_resumed(
    connection: mqtt.Connection,
    return_code: mqtt.ConnectReturnCode,
    session_present: bool,
    **kwargs: KwArgs,
) -> None:
    logger.debug(
        f"Connection resumed. return_code: {return_code} session_present: {session_present}"
    )

    if return_code == mqtt.ConnectReturnCode.ACCEPTED and not session_present:
        logger.debug("Session did not persist. Resubscribing to existing topics...")
        resubscribe_future, _ = connection.resubscribe_existing_topics()

        # Cannot synchronously wait for resubscribe result
        # because we're on the connection's event-loop thread,
        # evaluate result with a callback instead.
        resubscribe_future.add_done_callback(on_resubscribe_complete)


def on_resubscribe_complete(resubscribe_future: Future) -> None:  # type: ignore
    resubscribe_results = resubscribe_future.result()
    logger.debug(f"Resubscribe results: {resubscribe_results}")

    for topic, qos in resubscribe_results["topics"]:
        if qos is None:
            raise (
                ExceptionAwsIotMqtt(f"Server rejected resubscribe to topic: {topic}")
            )


class ConnectionParams:
    def __init__(
        self,
        endpoint: str = "",
        signing_region: str = "ap-northeast-1",
        root_ca: str = "~/.aws/cert/AmazonRootCA1.pem",
        cert: str = "~/.aws/cert/certificate.pem.crt",
        key: str = "~/.aws/cert/private.pem.key",
        client_id: str = "mqtt-" + str(uuid4()),
        use_websocket: bool = False,
        proxy_host: Optional[str] = None,
        proxy_port: int = 8080,
    ) -> None:
        self.endpoint = endpoint
        self.signing_region = signing_region
        self.root_ca = expanduser(root_ca)
        self.cert = expanduser(cert)
        self.key = expanduser(key)
        self.client_id = client_id
        self.use_websocket = use_websocket
        self.proxy_host = proxy_host
        self.proxy_port = proxy_port


def init(params: ConnectionParams) -> mqtt.Connection:
    # Spin up resources
    event_loop_group = io.EventLoopGroup(1)
    host_resolver = io.DefaultHostResolver(event_loop_group)
    client_bootstrap = io.ClientBootstrap(event_loop_group, host_resolver)

    if params.use_websocket:
        proxy_options = None
        if params.proxy_host:
            proxy_options = http.HttpProxyOptions(
                host_name=params.proxy_host, port=params.proxy_port
            )

        credentials_provider = auth.AwsCredentialsProvider.new_default_chain(
            client_bootstrap=client_bootstrap
        )
        mqtt_connection = mqtt_connection_builder.websockets_with_default_aws_signing(
            endpoint=params.endpoint,
            client_bootstrap=client_bootstrap,
            region=params.signing_region,
            credentials_provider=credentials_provider,
            websocket_proxy_options=proxy_options,
            ca_filepath=params.root_ca,
            on_connection_interrupted=on_connection_interrupted,
            on_connection_resumed=on_connection_resumed,
            clent_id=params.client_id,
            clean_session=False,
            keep_alive_secs=6,
        )

    else:
        mqtt_connection = mqtt_connection_builder.mtls_from_path(
            endpoint=params.endpoint,
            cert_filepath=params.cert,
            pri_key_filepath=params.key,
            client_bootstrap=client_bootstrap,
            ca_filepath=params.root_ca,
            on_connection_interrupted=on_connection_interrupted,
            on_connection_resumed=on_connection_resumed,
            client_id=params.client_id,
            clean_session=False,
            keep_alive_secs=6,
        )

    logger.debug(
        f"Connecting to {params.endpoint} with client ID '{params.client_id}'..."
    )

    return mqtt_connection
