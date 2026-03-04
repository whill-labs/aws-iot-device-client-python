from unittest.mock import MagicMock, patch

from awscrt import mqtt
from awsiot import iotjobs

import awsiotclient.jobs as jobs


class TestJobsClient:
    @patch("awsiotclient.jobs.iotjobs.IotJobsClient")
    def test_subscribes_on_init(self, MockJobsClient, make_jobs_client):
        mock_client = make_jobs_client()
        MockJobsClient.return_value = mock_client

        conn = MagicMock(spec=mqtt.Connection)
        jobs.client(conn, "thing1")

        mock_client.subscribe_to_next_job_execution_changed_events.assert_called_once()
        mock_client.subscribe_to_start_next_pending_job_execution_accepted.assert_called_once()
        mock_client.subscribe_to_start_next_pending_job_execution_rejected.assert_called_once()
        mock_client.subscribe_to_update_job_execution_accepted.assert_called_once()
        mock_client.subscribe_to_update_job_execution_rejected.assert_called_once()

    @patch("awsiotclient.jobs.iotjobs.IotJobsClient")
    def test_try_start_next_job_publishes(self, MockJobsClient, make_jobs_client):
        mock_client = make_jobs_client()
        MockJobsClient.return_value = mock_client

        conn = MagicMock(spec=mqtt.Connection)
        jobs.client(conn, "thing1")

        assert mock_client.publish_start_next_pending_job_execution.call_count == 1

    @patch("awsiotclient.jobs.iotjobs.IotJobsClient")
    def test_try_start_next_job_skips_when_already_working(
        self, MockJobsClient, make_jobs_client
    ):
        mock_client = make_jobs_client()
        MockJobsClient.return_value = mock_client

        conn = MagicMock(spec=mqtt.Connection)
        c = jobs.client(conn, "thing1")

        call_count_before = mock_client.publish_start_next_pending_job_execution.call_count
        c.try_start_next_job()
        assert mock_client.publish_start_next_pending_job_execution.call_count == call_count_before

    @patch("awsiotclient.jobs.iotjobs.IotJobsClient")
    def test_job_thread_fn_calls_job_func_and_reports_succeeded(
        self, MockJobsClient, make_jobs_client
    ):
        mock_client = make_jobs_client()
        MockJobsClient.return_value = mock_client

        received = []
        conn = MagicMock(spec=mqtt.Connection)
        c = jobs.client(conn, "thing1", job_func=lambda jid, jdoc: received.append((jid, jdoc)))

        mock_client.publish_update_job_execution.reset_mock()
        c.job_thread_fn("job-123", {"command": "reboot"})

        assert received == [("job-123", {"command": "reboot"})]
        mock_client.publish_update_job_execution.assert_called_once()
        request = mock_client.publish_update_job_execution.call_args[0][0]
        assert request.status == iotjobs.JobStatus.SUCCEEDED

    @patch("awsiotclient.jobs.iotjobs.IotJobsClient")
    def test_job_thread_fn_reports_failed_on_exception(self, MockJobsClient, make_jobs_client):
        mock_client = make_jobs_client()
        MockJobsClient.return_value = mock_client

        def failing_func(jid, jdoc):
            raise RuntimeError("something broke")

        conn = MagicMock(spec=mqtt.Connection)
        c = jobs.client(conn, "thing1", job_func=failing_func)

        mock_client.publish_update_job_execution.reset_mock()
        c.job_thread_fn("job-456", {})

        mock_client.publish_update_job_execution.assert_called_once()
        request = mock_client.publish_update_job_execution.call_args[0][0]
        assert request.status == iotjobs.JobStatus.FAILED
