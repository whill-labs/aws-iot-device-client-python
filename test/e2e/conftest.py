from os import environ

import pytest

REQUIRED = ("AWSIOT_ENDPOINT", "AWS_REGION", "AWS_ACCOUNT_ID")


def pytest_collection_modifyitems(config, items):
    missing = [name for name in REQUIRED if name not in environ]
    if not missing:
        return
    skip = pytest.mark.skip(
        reason=f"E2E needs {', '.join(missing)} (source test/env.sh)"
    )
    for item in items:
        if "/e2e/" in str(item.fspath):
            item.add_marker(skip)
