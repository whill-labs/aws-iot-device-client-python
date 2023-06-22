# aws-iot-device-client-python

The AWS IoT Device Client provides device-side functionality for AWS IoT services such as jobs, device shadow, and simple pubsub.

## Installation

### Minimum Requirements

- Python 3.7.1+

### Install from PyPI

```shell
python3 -m pip install awsiotclient
```

### Install from source

```shell
git clone https://github.com/whill-labs/aws-iot-device-client-python
python3 -m pip install ./aws-iot-device-client-python
```

## Usage

### Create MQTT connection

```python
from awsiotclient import mqtt

# Construct connection parameters
conn_params = mqtt.ConnectionParams()

# Required params
conn_params.endpoint = <your_endpoint_url>
conn_params.cert = <path_to_your_certificate>
conn_params.key = <path_to_your_private_key>
conn_params.root_ca = <path_to_your_root_ca>

# Optional params
conn_params.client_id = <client_id> # default "mqtt-" + uuid4()
conn_params.signing_region = <signing_region> # default "ap-northeast-1" (Tokyo Region)
conn_params.use_websocket = <True/False> # default False

# Initialize connection
mqtt_connection = mqtt.init(conn_params)
connect_future = mqtt_connection.connect()
connect_future.result()
```

### Use AWS IoT named shadow

Note that usage of classic shadow client is similar to named shadow client.

#### without delta (one-way communication from device to cloud)

```python
from awsiotclient import mqtt, named_shadow

# <create mqtt connection here as described above>
my_client = named_shadow.client(
    mqtt_connection,
    thing_name="my_thing",
    shadow_name="my_shadow"
)

my_value = dict(foo="var")
my_clinet.change_reported_value(my_value)
```

#### with delta (two-way communication from/to device and cloud)

```python
from awsiotclient import mqtt, named_shadow

def my_delta_func(thing_name: str, shadow_name: str, value: Dict[str, Any]) -> None:
    print("my_client invokes this callback when it receives delta message")
    print(f"thing_name: {thing_name}, shadow_name: {shadow_name}, value: {value}")

# <create mqtt connection here as described above>
my_client = named_shadow.client(
    mqtt_connection,
    thing_name="my_thing",
    shadow_name="my_shadow",
    delta_func=my_delta_func,
)

my_value = dict(foo="var")
my_client.change_reported_value(my_value)
# <wait until the client receives delta>
```

### Use AWS IoT jobs

```python
from awsiotclient import mqtt, named_shadow

def job_runner(id: str, document: dict):
    print("my_client invokes this callback when it receives job document")
    print(f"job id: {id}, document: {document}")

# <create mqtt connection here as described above
job_client = jobs.client(
    mqtt_connection,
    thing_name="my_thing",
    job_func=job_runner
)
# <wait until the client receives job>
```

## License

This library is licensed under the Apache 2.0 License.

## Acknowledgments

- [AWS IoT Device SDK v2 for Python](https://github.com/aws/aws-iot-device-sdk-python-v2)
