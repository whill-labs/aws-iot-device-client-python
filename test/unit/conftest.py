import logging
from typing import Iterator

import pytest

from .fakes import FakeBroker, FakeConnection, FakeJobsService, FakeShadowService


@pytest.fixture(autouse=True)
def log_records_are_well_formed(caplog: pytest.LogCaptureFixture) -> Iterator[None]:
    """Every log call made by the library must be formattable at DEBUG level."""
    caplog.set_level(logging.DEBUG, logger="awsiotclient")
    yield
    for record in caplog.records:
        if record.name.startswith("awsiotclient"):
            record.getMessage()


@pytest.fixture
def broker() -> Iterator[FakeBroker]:
    broker = FakeBroker()
    yield broker
    # Exceptions raised in subscriber callbacks are swallowed by the CRT event
    # loop in production. A test that expects one must take it explicitly.
    assert broker.take_callback_errors() == []


@pytest.fixture
def shadow_service(broker: FakeBroker) -> FakeShadowService:
    service = FakeShadowService()
    broker.add_service(service)
    return service


@pytest.fixture
def jobs_service(broker: FakeBroker) -> FakeJobsService:
    service = FakeJobsService()
    broker.add_service(service)
    return service


@pytest.fixture
def connection(broker: FakeBroker) -> FakeConnection:
    return broker.connect()
