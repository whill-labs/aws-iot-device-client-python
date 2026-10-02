"""Contract tests for jobs.client against FakeJobsService.

job_func runs on a thread of its own, so tests wait on the fake service
instead of sleeping.
"""

import threading
from typing import Any, List, Tuple

import pytest

from awsiotclient import jobs

from .fakes import FakeBroker, FakeJobsService

THING = "thing-1"
START_NEXT = f"$aws/things/{THING}/jobs/start-next"


class Runner:
    """A job_func that records calls and can hold a job until released."""

    def __init__(self, hold: bool = False) -> None:
        self.calls: List[Tuple[str, Any]] = []
        self.running = 0
        self.max_running = 0
        self._lock = threading.Lock()
        self.started = threading.Event()
        self.release = threading.Event()
        if not hold:
            self.release.set()

    def __call__(self, job_id: str, document: Any) -> None:
        with self._lock:
            self.calls.append((job_id, document))
            self.running += 1
            self.max_running = max(self.max_running, self.running)
        self.started.set()
        try:
            assert self.release.wait(timeout=2)
        finally:
            with self._lock:
                self.running -= 1


@pytest.fixture(params=[False, True], ids=["accept-then-notify", "notify-then-accept"])
def jobs_service(request: pytest.FixtureRequest, broker: FakeBroker) -> FakeJobsService:
    # AWS IoT does not order update/accepted against notify-next.
    service = FakeJobsService(notify_before_accept=request.param)
    broker.add_service(service)
    return service


class TestInitialization:
    def test_subscribes_to_every_response_topic(self, broker, jobs_service, connection):
        jobs.client(connection, THING)

        base = f"$aws/things/{THING}/jobs"
        assert set(connection.subscriptions) == {
            f"{base}/notify-next",
            f"{base}/start-next/accepted",
            f"{base}/start-next/rejected",
            f"{base}/+/update/accepted",
            f"{base}/+/update/rejected",
        }

    def test_asks_for_the_next_job(self, broker, jobs_service, connection):
        jobs.client(connection, THING)

        assert len(broker.payloads(START_NEXT)) == 1

    def test_subscription_failure_is_wrapped(self, broker, jobs_service, connection):
        connection.reject_subscription(f"$aws/things/{THING}/jobs/notify-next")

        with pytest.raises(jobs.ExceptionAwsIotJobs):
            jobs.client(connection, THING)


class TestJobExecution:
    def test_runs_a_queued_job_and_reports_success(
        self, broker, jobs_service, connection
    ):
        jobs_service.add_job(THING, "job-1", {"op": "reboot"})
        runner = Runner()

        jobs.client(connection, THING, job_func=runner)

        jobs_service.wait_for_status(THING, "job-1", "SUCCEEDED")
        assert runner.calls == [("job-1", {"op": "reboot"})]

    def test_runs_a_job_that_arrives_while_idle(self, broker, jobs_service, connection):
        runner = Runner()
        jobs.client(connection, THING, job_func=runner)

        jobs_service.add_job(THING, "job-1", {"op": "reboot"})

        jobs_service.wait_for_status(THING, "job-1", "SUCCEEDED")
        assert runner.calls == [("job-1", {"op": "reboot"})]

    def test_user_defined_failure_is_reported(self, broker, jobs_service, connection):
        def job_func(job_id: str, document: Any) -> None:
            raise jobs.ExceptionAwsIotJobsUserDefinedFailure("disk full")

        jobs_service.add_job(THING, "job-1", {})
        jobs.client(connection, THING, job_func=job_func)

        jobs_service.wait_for_status(THING, "job-1", "FAILED")
        assert jobs_service.job(THING, "job-1")["statusDetails"] == {
            "failure_type": "user_defined",
            "failure_detail": "disk full",
        }

    def test_unexpected_failure_is_reported(self, broker, jobs_service, connection):
        def job_func(job_id: str, document: Any) -> None:
            raise ValueError("boom")

        jobs_service.add_job(THING, "job-1", {})
        jobs.client(connection, THING, job_func=job_func)

        jobs_service.wait_for_status(THING, "job-1", "FAILED")
        assert jobs_service.job(THING, "job-1")["statusDetails"] == {
            "failure_type": "unknown",
            "failure_detail": "boom",
        }

    def test_runs_queued_jobs_one_at_a_time_in_order(
        self, broker, jobs_service, connection
    ):
        for i in range(3):
            jobs_service.add_job(THING, f"job-{i}", {"n": i})
        runner = Runner()

        jobs.client(connection, THING, job_func=runner)

        jobs_service.wait_for_status(THING, "job-2", "SUCCEEDED")
        assert [job_id for job_id, _ in runner.calls] == ["job-0", "job-1", "job-2"]
        assert runner.max_running == 1

    def test_job_arriving_mid_run_waits_for_the_current_one(
        self, broker, jobs_service, connection
    ):
        runner = Runner(hold=True)
        jobs.client(connection, THING, job_func=runner)
        jobs_service.add_job(THING, "job-1", {})
        assert runner.started.wait(timeout=2)

        jobs_service.add_job(THING, "job-2", {})
        assert jobs_service.job(THING, "job-2")["status"] == "QUEUED"
        runner.release.set()

        jobs_service.wait_for_status(THING, "job-2", "SUCCEEDED")
        assert [job_id for job_id, _ in runner.calls] == ["job-1", "job-2"]
        assert runner.max_running == 1


class TestRecovery:
    """A failed round trip must not leave the client unable to take new jobs."""

    def test_after_start_next_is_rejected(self, broker, jobs_service, connection):
        jobs_service.reject_next("start-next", code="Throttling", message="slow down")
        runner = Runner()
        jobs.client(connection, THING, job_func=runner)
        assert [type(e) for e in broker.take_callback_errors()] == [
            jobs.ExceptionAwsIotJobs
        ]

        jobs_service.add_job(THING, "job-1", {})

        jobs_service.wait_for_status(THING, "job-1", "SUCCEEDED")

    def test_after_start_next_fails_to_publish(self, broker, jobs_service, connection):
        connection.fail_next_publish(START_NEXT)
        runner = Runner()
        jobs.client(connection, THING, job_func=runner)

        jobs_service.add_job(THING, "job-1", {})

        jobs_service.wait_for_status(THING, "job-1", "SUCCEEDED")

    def test_after_status_update_is_rejected(self, broker, jobs_service, connection):
        jobs_service.add_job(THING, "job-1", {})
        jobs_service.reject_next("update", code="VersionMismatch", message="stale")
        runner = Runner()
        jobs.client(connection, THING, job_func=runner)
        jobs_service.wait_until(lambda: len(broker.callback_errors) == 1)
        assert [type(e) for e in broker.take_callback_errors()] == [
            jobs.ExceptionAwsIotJobs
        ]

        jobs_service.add_job(THING, "job-2", {})
        jobs_service.set_status(THING, "job-1", "TIMED_OUT")

        jobs_service.wait_for_status(THING, "job-2", "SUCCEEDED")
