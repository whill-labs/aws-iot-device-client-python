from pathlib import Path
from os import environ
from uuid import uuid4

from awscrt.mqtt import Connection

from awsiotclient import mqtt


def init_connection(client_id_prefix: str) -> Connection:
    conn_params = mqtt.ConnectionParams(
        endpoint=environ["AWSIOT_ENDPOINT"],
        signing_region=environ["AWS_REGION"],
        root_ca=str(Path(__file__).parent / "certs" / "AmazonRootCA1.pem"),
        cert=str(Path(__file__).parent / "certs" / "certificate.pem.crt"),
        key=str(Path(__file__).parent / "certs" / "private.pem.key"),
        client_id=f"{client_id_prefix}-{uuid4()}",
    )

    connection = mqtt.init(conn_params)
    connection.connect().result(timeout=1)
    return connection
