from concurrent.futures import Future
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from awscrt import mqtt
from awsiot import iotjobs

import awsiotclient.jobs as jobs


class TestJobsCallbacks:
    @patch("awsiotclient.jobs.iotjobs.IotJobsClient")
    def test_init_wraps_subscription_failure(self, MockJobsClient, make_jobs_client):
        mock_client = make_jobs_client()
        failed = Future()
        failed.set_exception(RuntimeError("subscribe failed"))
        mock_client.subscribe_to_next_job_execution_changed_events.return_value = (
            failed,
            1,
        )
        MockJobsClient.return_value = mock_client

        conn = MagicMock(spec=mqtt.Connection)
        with pytest.raises(jobs.ExceptionAwsIotJobs):
            jobs.client(conn, "thing1")

    @patch("awsiotclient.jobs.iotjobs.IotJobsClient")
    def test_try_start_next_job_skips_when_disconnect_called(
        self, MockJobsClient, make_jobs_client
    ):
        mock_client = make_jobs_client()
        MockJobsClient.return_value = mock_client

        conn = MagicMock(spec=mqtt.Connection)
        c = jobs.client(conn, "thing1")

        mock_client.publish_start_next_pending_job_execution.reset_mock()
        c.locked_data.is_working_on_job = False
        c.locked_data.disconnect_called = True

        c.try_start_next_job()

        mock_client.publish_start_next_pending_job_execution.assert_not_called()

    @patch("awsiotclient.jobs.iotjobs.IotJobsClient")
    def test_done_working_on_job_retries_when_waiting(self, MockJobsClient, make_jobs_client):
        mock_client = make_jobs_client()
        MockJobsClient.return_value = mock_client

        conn = MagicMock(spec=mqtt.Connection)
        c = jobs.client(conn, "thing1")

        c.try_start_next_job = MagicMock()
        c.locked_data.is_working_on_job = True
        c.locked_data.is_next_job_waiting = True

        c.done_working_on_job()

        assert c.locked_data.is_working_on_job is False
        c.try_start_next_job.assert_called_once()

    @patch("awsiotclient.jobs.iotjobs.IotJobsClient")
    def test_on_next_job_execution_changed_none(self, MockJobsClient, make_jobs_client):
        mock_client = make_jobs_client()
        MockJobsClient.return_value = mock_client

        conn = MagicMock(spec=mqtt.Connection)
        c = jobs.client(conn, "thing1")

        c.on_next_job_execution_changed(SimpleNamespace(execution=None))

    @patch("awsiotclient.jobs.iotjobs.IotJobsClient")
    def test_on_next_job_execution_changed_sets_wait_flag_while_working(
        self, MockJobsClient, make_jobs_client
    ):
        mock_client = make_jobs_client()
        MockJobsClient.return_value = mock_client

        conn = MagicMock(spec=mqtt.Connection)
        c = jobs.client(conn, "thing1")

        c.try_start_next_job = MagicMock()
        c.locked_data.is_working_on_job = True

        event = SimpleNamespace(
            execution=SimpleNamespace(job_id="job-1", job_document={"cmd": "reboot"})
        )
        c.on_next_job_execution_changed(event)

        assert c.locked_data.is_next_job_waiting is True
        c.try_start_next_job.assert_not_called()

    @patch("awsiotclient.jobs.iotjobs.IotJobsClient")
    def test_on_next_job_execution_changed_starts_now_when_idle(
        self, MockJobsClient, make_jobs_client
    ):
        mock_client = make_jobs_client()
        MockJobsClient.return_value = mock_client

        conn = MagicMock(spec=mqtt.Connection)
        c = jobs.client(conn, "thing1")

        c.locked_data.is_working_on_job = False
        c.try_start_next_job = MagicMock()

        event = SimpleNamespace(
            execution=SimpleNamespace(job_id="job-2", job_document={"cmd": "sync"})
        )
        c.on_next_job_execution_changed(event)

        c.try_start_next_job.assert_called_once()

    @patch("awsiotclient.jobs.iotjobs.IotJobsClient")
    def test_on_next_job_execution_changed_wraps_unexpected_error(
        self, MockJobsClient, make_jobs_client
    ):
        mock_client = make_jobs_client()
        MockJobsClient.return_value = mock_client

        class BrokenEvent:
            @property
            def execution(self):
                raise RuntimeError("cannot access execution")

        conn = MagicMock(spec=mqtt.Connection)
        c = jobs.client(conn, "thing1")

        with pytest.raises(jobs.ExceptionAwsIotJobs):
            c.on_next_job_execution_changed(BrokenEvent())

    @patch("awsiotclient.jobs.iotjobs.IotJobsClient")
    def test_on_publish_start_next_pending_job_execution_raises(
        self, MockJobsClient, make_jobs_client
    ):
        mock_client = make_jobs_client()
        MockJobsClient.return_value = mock_client

        conn = MagicMock(spec=mqtt.Connection)
        c = jobs.client(conn, "thing1")

        failed = Future()
        failed.set_exception(RuntimeError("publish failed"))

        with pytest.raises(jobs.ExceptionAwsIotJobs):
            c.on_publish_start_next_pending_job_execution(failed)

    @patch("awsiotclient.jobs.threading.Thread")
    @patch("awsiotclient.jobs.iotjobs.IotJobsClient")
    def test_start_next_pending_job_accepted_spawns_thread(
        self, MockJobsClient, MockThread, make_jobs_client
    ):
        mock_client = make_jobs_client()
        MockJobsClient.return_value = mock_client

        thread_instance = MagicMock()
        MockThread.return_value = thread_instance

        conn = MagicMock(spec=mqtt.Connection)
        c = jobs.client(conn, "thing1")

        response = SimpleNamespace(
            execution=SimpleNamespace(job_id="job-3", job_document={"cmd": "update"})
        )
        c.on_start_next_pending_job_execution_accepted(response)

        MockThread.assert_called_once()
        assert MockThread.call_args.kwargs["name"] == "job_thread"
        thread_instance.start.assert_called_once()

    @patch("awsiotclient.jobs.threading.Thread")
    @patch("awsiotclient.jobs.iotjobs.IotJobsClient")
    def test_start_next_pending_job_accepted_wraps_thread_creation_error(
        self, MockJobsClient, MockThread, make_jobs_client
    ):
        mock_client = make_jobs_client()
        MockJobsClient.return_value = mock_client

        MockThread.side_effect = RuntimeError("thread creation failed")

        conn = MagicMock(spec=mqtt.Connection)
        c = jobs.client(conn, "thing1")

        response = SimpleNamespace(
            execution=SimpleNamespace(job_id="job-err", job_document={"cmd": "update"})
        )
        with pytest.raises(jobs.ExceptionAwsIotJobs):
            c.on_start_next_pending_job_execution_accepted(response)

    @patch("awsiotclient.jobs.iotjobs.IotJobsClient")
    def test_start_next_pending_job_accepted_without_execution_marks_done(
        self, MockJobsClient, make_jobs_client
    ):
        mock_client = make_jobs_client()
        MockJobsClient.return_value = mock_client

        conn = MagicMock(spec=mqtt.Connection)
        c = jobs.client(conn, "thing1")

        c.done_working_on_job = MagicMock()
        c.on_start_next_pending_job_execution_accepted(SimpleNamespace(execution=None))

        c.done_working_on_job.assert_called_once()

    @patch("awsiotclient.jobs.iotjobs.IotJobsClient")
    def test_start_next_pending_job_rejected_raises(self, MockJobsClient, make_jobs_client):
        mock_client = make_jobs_client()
        MockJobsClient.return_value = mock_client

        conn = MagicMock(spec=mqtt.Connection)
        c = jobs.client(conn, "thing1")

        with pytest.raises(jobs.ExceptionAwsIotJobs):
            c.on_start_next_pending_job_execution_rejected(
                SimpleNamespace(code="Rejected", message="bad request")
            )

    @patch("awsiotclient.jobs.iotjobs.IotJobsClient")
    def test_job_thread_user_defined_failure_sets_status_details(
        self, MockJobsClient, make_jobs_client
    ):
        mock_client = make_jobs_client()
        MockJobsClient.return_value = mock_client

        def fail_user_defined(*args, **kwargs):
            raise jobs.ExceptionAwsIotJobsUserDefinedFailure("manual failure")

        conn = MagicMock(spec=mqtt.Connection)
        c = jobs.client(conn, "thing1", job_func=fail_user_defined)

        mock_client.publish_update_job_execution.reset_mock()
        c.job_thread_fn("job-4", {"cmd": "noop"})

        mock_client.publish_update_job_execution.assert_called_once()
        request = mock_client.publish_update_job_execution.call_args[0][0]
        assert request.status == iotjobs.JobStatus.FAILED
        assert request.status_details["failure_type"] == "user_defined"

    @patch("awsiotclient.jobs.iotjobs.IotJobsClient")
    def test_on_publish_update_job_execution_raises(self, MockJobsClient, make_jobs_client):
        mock_client = make_jobs_client()
        MockJobsClient.return_value = mock_client

        conn = MagicMock(spec=mqtt.Connection)
        c = jobs.client(conn, "thing1")

        failed = Future()
        failed.set_exception(RuntimeError("publish failed"))

        with pytest.raises(jobs.ExceptionAwsIotJobs):
            c.on_publish_update_job_execution(failed)

    @patch("awsiotclient.jobs.iotjobs.IotJobsClient")
    def test_on_update_job_execution_accepted_calls_done(
        self, MockJobsClient, make_jobs_client
    ):
        mock_client = make_jobs_client()
        MockJobsClient.return_value = mock_client

        conn = MagicMock(spec=mqtt.Connection)
        c = jobs.client(conn, "thing1")

        c.done_working_on_job = MagicMock()
        c.on_update_job_execution_accepted(SimpleNamespace())

        c.done_working_on_job.assert_called_once()

    @patch("awsiotclient.jobs.iotjobs.IotJobsClient")
    def test_on_update_job_execution_accepted_wraps_done_error(
        self, MockJobsClient, make_jobs_client
    ):
        mock_client = make_jobs_client()
        MockJobsClient.return_value = mock_client

        conn = MagicMock(spec=mqtt.Connection)
        c = jobs.client(conn, "thing1")

        c.done_working_on_job = MagicMock(side_effect=RuntimeError("done failed"))
        with pytest.raises(jobs.ExceptionAwsIotJobs):
            c.on_update_job_execution_accepted(SimpleNamespace())

    @patch("awsiotclient.jobs.iotjobs.IotJobsClient")
    def test_on_update_job_execution_rejected_raises(self, MockJobsClient, make_jobs_client):
        mock_client = make_jobs_client()
        MockJobsClient.return_value = mock_client

        conn = MagicMock(spec=mqtt.Connection)
        c = jobs.client(conn, "thing1")

        with pytest.raises(jobs.ExceptionAwsIotJobs):
            c.on_update_job_execution_rejected(
                SimpleNamespace(code="Rejected", message="forbidden")
            )
