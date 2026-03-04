from concurrent.futures import Future
from unittest.mock import MagicMock

import pytest


def _done_future(value=None):
    future = Future()
    future.set_result(value)
    return future


@pytest.fixture
def make_done_future():
    return _done_future


@pytest.fixture
def make_classic_shadow_client(make_done_future):
    def factory():
        mock_client = MagicMock()
        for method_name in [
            "subscribe_to_shadow_delta_updated_events",
            "subscribe_to_update_shadow_accepted",
            "subscribe_to_update_shadow_rejected",
            "subscribe_to_get_shadow_accepted",
            "subscribe_to_get_shadow_rejected",
        ]:
            getattr(mock_client, method_name).return_value = (make_done_future(), 1)

        mock_client.publish_get_shadow.return_value = make_done_future()
        mock_client.publish_update_shadow.return_value = make_done_future()
        return mock_client

    return factory


@pytest.fixture
def make_named_shadow_client(make_done_future):
    def factory():
        mock_client = MagicMock()
        for method_name in [
            "subscribe_to_named_shadow_delta_updated_events",
            "subscribe_to_update_named_shadow_accepted",
            "subscribe_to_update_named_shadow_rejected",
            "subscribe_to_get_named_shadow_accepted",
            "subscribe_to_get_named_shadow_rejected",
        ]:
            getattr(mock_client, method_name).return_value = (make_done_future(), 1)

        mock_client.publish_get_named_shadow.return_value = make_done_future()
        mock_client.publish_update_named_shadow.return_value = make_done_future()
        return mock_client

    return factory


@pytest.fixture
def make_jobs_client(make_done_future):
    def factory():
        mock_client = MagicMock()
        for method_name in [
            "subscribe_to_next_job_execution_changed_events",
            "subscribe_to_start_next_pending_job_execution_accepted",
            "subscribe_to_start_next_pending_job_execution_rejected",
            "subscribe_to_update_job_execution_accepted",
            "subscribe_to_update_job_execution_rejected",
        ]:
            getattr(mock_client, method_name).return_value = (make_done_future(), 1)

        mock_client.publish_start_next_pending_job_execution.return_value = (
            make_done_future()
        )
        mock_client.publish_update_job_execution.return_value = make_done_future()
        return mock_client

    return factory


@pytest.fixture
def make_pubsub_connection(make_done_future):
    def factory(qos):
        connection = MagicMock()
        connection.subscribe.return_value = (make_done_future({"qos": qos}), 1)
        connection.publish.return_value = (make_done_future(None), 1)
        return connection

    return factory
