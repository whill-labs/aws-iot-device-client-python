# Tests

## Layout

```
test/
├── unit/                 # No AWS access; run in CI
│   ├── fakes.py          # In-memory MQTT connection and AWS IoT (Shadow / Jobs) fakes
│   ├── conftest.py
│   ├── test_dictdiff.py  # Diff and merge of documents, including property-based tests
│   ├── test_shadow.py    # Classic and named shadow behavior
│   ├── test_jobs.py      # Job execution, failure reports, recovery and concurrency
│   ├── test_mqtt.py      # Connection parameters, building connections, reconnects
│   └── test_pubsub.py
└── e2e/                  # Talks to a real AWS IoT account; run locally only
```

### How the unit tests work

- Tests use the library only through its public API. They never call internal methods or callbacks directly.
- The only boundary with AWS is `awscrt.mqtt.Connection`. `FakeConnection` replaces it, and `FakeShadowService` and `FakeJobsService` answer the `$aws/things/...` topics. The real `awsiot` SDK still runs, so topic names and JSON payloads are tested too.
- Assertions look at the state of the fakes, for example "after `change_reported_value`, the reported value in the cloud equals the new value".
- `mqtt.init()` is tested with the real connection builder, and the tests check the attributes of the resulting connection. They never call `connect()`, so nothing goes over the network.
- Every test also checks two things automatically:
  - all DEBUG log calls can be formatted;
  - no subscriber callback raised an unexpected exception. A test that expects one takes it with `broker.take_callback_errors()`.

## Running

```bash
uv sync

# Unit tests
uv run pytest test/unit

# With coverage (fails below 90%)
uv run pytest test/unit --cov --cov-report=term-missing

# Lint and type check, as in CI
uv run black --check src test
uv run isort --check-only src test
uv run flake8 src test
uv run mypy src

# Unit tests against the lowest allowed dependencies on Python 3.8
# (uv pip leaves uv.lock alone, unlike uv sync --resolution lowest-direct)
uv venv --python 3.8 .venv-lowest
uv pip install --python .venv-lowest --resolution lowest-direct -e . --group test
.venv-lowest/bin/python -m pytest test/unit
```

Running `pytest` without arguments also collects the E2E tests, but they are skipped unless the environment variables below are set.

## E2E tests

They are not run in CI because this is a public repository. Run them locally with your own AWS credentials.

### Setup

```bash
# Create a thing
aws iot create-thing --thing-name awsiotclient-test

# Create a certificate
aws iot create-keys-and-certificate \
  --set-as-active \
  --certificate-pem-outfile ./test/e2e/certs/certificate.pem.crt \
  --public-key-outfile ./test/e2e/certs/public.pem.key \
  --private-key-outfile ./test/e2e/certs/private.pem.key > ./test/e2e/certs/cert.json

# Attach the thing to the certificate
aws iot attach-thing-principal \
  --principal "$(jq -r .certificateArn < ./test/e2e/certs/cert.json)" \
  --thing-name awsiotclient-test

# Attach a policy to the certificate
aws iot attach-policy \
    --target "$(jq -r .certificateArn < ./test/e2e/certs/cert.json)" \
    --policy-name <policy>
```

Do not commit anything in `test/e2e/certs/` other than `AmazonRootCA1.pem`; `.gitignore` excludes the rest.

### Running

```bash
source ./test/env.sh   # AWSIOT_ENDPOINT, AWS_REGION, AWS_ACCOUNT_ID
uv run pytest test/e2e -v
```

## Running inside a ROS environment

When a ROS 2 environment is sourced, its pytest plugins get loaded and interfere with the tests. `addopts` in `pyproject.toml` disables the common ones.
