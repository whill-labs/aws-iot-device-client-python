import threading
from concurrent.futures import Future
from typing import Any, Callable, Dict, Optional

from awscrt import mqtt
from awsiot import iotjobs

from . import ExceptionAwsIotClient, get_module_logger

logger = get_module_logger(__name__)
JobDocument = Optional[Dict[str, Any]]


class ExceptionAwsIotJobs(ExceptionAwsIotClient):
    def __init__(self, *args: object) -> None:
        super().__init__(*args)


class ExceptionAwsIotJobsUserDefinedFailure(ExceptionAwsIotJobs):
    def __init__(self, *args: object) -> None:
        super().__init__(*args)


def empty_func(id: str, document: JobDocument) -> None:
    logger.debug(f"empty_job. id: {id}, document: {document}")


class LockedData:
    def __init__(self) -> None:
        self.lock: threading.Lock = threading.Lock()
        self.disconnect_called: bool = False
        self.is_working_on_job: bool = False
        self.is_next_job_waiting: bool = False


class client:
    def __init__(
        self,
        connection: mqtt.Connection,
        thing_name: str,
        qos: mqtt.QoS = mqtt.QoS.AT_LEAST_ONCE,
        job_func: Callable[[str, JobDocument], None] = empty_func,
    ) -> None:
        self.client = iotjobs.IotJobsClient(connection)
        self.thing_name = thing_name
        self.qos = qos
        self.locked_data = LockedData()
        self.job_func = job_func

        try:
            self.client.subscribe_to_next_job_execution_changed_events(
                request=iotjobs.NextJobExecutionChangedSubscriptionRequest(
                    thing_name=thing_name
                ),
                qos=qos,
                callback=self.on_next_job_execution_changed,
            )[0].result()

            self.__subscribe_start_next_pending_job()
            self.__subscribe_update_job()

            # Make initial attempt to start next job. The service should reply with
            # an "accepted" response, even if no jobs are pending. The response
            # will contain data about the next job, if there is one.
            self.try_start_next_job()

        except Exception as e:
            raise ExceptionAwsIotJobs(e)

    def __subscribe_start_next_pending_job(self) -> None:
        logger.debug("Subscribing to Start responses...")
        request = iotjobs.StartNextPendingJobExecutionSubscriptionRequest(
            thing_name=self.thing_name
        )

        (
            accepted_future,
            _,
        ) = self.client.subscribe_to_start_next_pending_job_execution_accepted(
            request=request,
            qos=self.qos,
            callback=self.on_start_next_pending_job_execution_accepted,
        )

        (
            rejected_future,
            _,
        ) = self.client.subscribe_to_start_next_pending_job_execution_rejected(
            request=request,
            qos=self.qos,
            callback=self.on_start_next_pending_job_execution_rejected,
        )

        # Wait for subscriptions to succeed
        accepted_future.result()
        rejected_future.result()

    def __subscribe_update_job(self) -> None:
        logger.debug("Subscribing to Update responses...")
        # Note that we subscribe to "+", the MQTT wildcard, to receive
        # responses about any job-ID.
        request = iotjobs.UpdateJobExecutionSubscriptionRequest(
            thing_name=self.thing_name, job_id="+"
        )

        accepted_future, _ = self.client.subscribe_to_update_job_execution_accepted(
            request=request,
            qos=self.qos,
            callback=self.on_update_job_execution_accepted,
        )

        rejected_future, _ = self.client.subscribe_to_update_job_execution_rejected(
            request=request,
            qos=self.qos,
            callback=self.on_update_job_execution_rejected,
        )

        # Wait for subscriptions to succeed
        accepted_future.result()
        rejected_future.result()

    def try_start_next_job(self) -> None:
        logger.debug("Trying to start the next job...")
        with self.locked_data.lock:
            if self.locked_data.is_working_on_job:
                logger.debug("Nevermind, already working on a job.")
                return

            if self.locked_data.disconnect_called:
                logger.debug("Nevermind, sample is disconnecting.")
                return

            self.locked_data.is_working_on_job = True
            self.locked_data.is_next_job_waiting = False

        logger.debug("Publishing request to start next job...")
        request = iotjobs.StartNextPendingJobExecutionRequest(
            thing_name=self.thing_name
        )
        publish_future = self.client.publish_start_next_pending_job_execution(
            request, self.qos
        )
        publish_future.add_done_callback(
            self.on_publish_start_next_pending_job_execution
        )

    def done_working_on_job(self) -> None:
        with self.locked_data.lock:
            self.locked_data.is_working_on_job = False
            try_again = self.locked_data.is_next_job_waiting

        if try_again:
            self.try_start_next_job()

    def on_next_job_execution_changed(
        self, event: iotjobs.NextJobExecutionChangedEvent
    ) -> None:
        try:
            execution = event.execution
            if execution:
                logger.debug(
                    "Received Next Job Execution Changed event. ",
                    f"job_id:{execution.job_id} job_document:{execution.job_document}",
                )

                # Start job now, or remember to start it when current job is done
                start_job_now = False
                with self.locked_data.lock:
                    if self.locked_data.is_working_on_job:
                        self.locked_data.is_next_job_waiting = True
                    else:
                        start_job_now = True

                if start_job_now:
                    self.try_start_next_job()

            else:
                logger.debug(
                    "Received Next Job Execution Changed event: ",
                    "None. Waiting for further jobs...",
                )

        except Exception as e:
            raise ExceptionAwsIotJobs(e)

    def on_publish_start_next_pending_job_execution(self, future: Future) -> None:  # type: ignore
        try:
            future.result()  # raises exception if publish failed

            logger.debug("Published request to start the next job.")

        except Exception as e:
            raise ExceptionAwsIotJobs(e)

    def on_start_next_pending_job_execution_accepted(
        self, response: iotjobs.StartNextJobExecutionResponse
    ):
        try:
            if response.execution:
                execution = response.execution
                logger.debug(
                    f"Request to start next job was accepted. job_id:{execution.job_id} job_document:{execution.job_document}"
                )

                # To emulate working on a job, spawn a thread that sleeps for a few seconds
                job_thread = threading.Thread(
                    target=lambda: self.job_thread_fn(
                        execution.job_id, execution.job_document
                    ),
                    name="job_thread",
                )
                job_thread.start()
            else:
                logger.debug(
                    "Request to start next job was accepted, but there are no jobs to be done.",
                    " Waiting for further jobs...",
                )
                self.done_working_on_job()

        except Exception as e:
            raise ExceptionAwsIotJobs(e)

    def on_start_next_pending_job_execution_rejected(
        self, rejected: iotjobs.RejectedError
    ) -> None:
        raise ExceptionAwsIotJobs(
            f"Request to start next pending job rejected with code:'{rejected.code}' message:'{rejected.message}'"
        )

    def job_thread_fn(self, job_id: str, job_document: JobDocument) -> None:
        try:
            logger.debug("Starting local work on job...")
            self.job_func(job_id, job_document)
            logger.debug("Done working on job.")
        except ExceptionAwsIotJobsUserDefinedFailure as e:
            logger.debug(
                "Report that job excecution failed due to user-defined reason..."
            )
            request = iotjobs.UpdateJobExecutionRequest(
                thing_name=self.thing_name,
                job_id=job_id,
                status_details=dict(failure_type="user_defined", failure_detail=str(e)),
                status=iotjobs.JobStatus.FAILED,
            )
        except Exception as e:
            logger.debug("Report that job excecution failed due to unknown reason...")
            request = iotjobs.UpdateJobExecutionRequest(
                thing_name=self.thing_name,
                job_id=job_id,
                status_details=dict(failure_type="unknown", failure_detail=str(e)),
                status=iotjobs.JobStatus.FAILED,
            )
        else:
            logger.debug("Publishing request to update job status to SUCCEEDED...")
            request = iotjobs.UpdateJobExecutionRequest(
                thing_name=self.thing_name,
                job_id=job_id,
                status=iotjobs.JobStatus.SUCCEEDED,
            )
        finally:
            publish_future = self.client.publish_update_job_execution(request, self.qos)
            publish_future.add_done_callback(self.on_publish_update_job_execution)

    def on_publish_update_job_execution(self, future: Future) -> None:  # type: ignore
        try:
            future.result()  # raises exception if publish failed
            logger.debug("Published request to update job.")

        except Exception as e:
            raise ExceptionAwsIotJobs(e)

    def on_update_job_execution_accepted(
        self, response: iotjobs.UpdateJobExecutionResponse
    ) -> None:
        try:
            logger.debug("Request to update job was accepted.")
            self.done_working_on_job()
        except Exception as e:
            raise ExceptionAwsIotJobs(e)

    def on_update_job_execution_rejected(self, rejected: iotjobs.RejectedError) -> None:
        raise ExceptionAwsIotJobs(
            f"Request to update job status was rejected. code:'{rejected.code}' message:'{rejected.message}'."
        )
