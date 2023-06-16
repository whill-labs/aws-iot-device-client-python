import unittest
from os import environ
from time import sleep
from uuid import uuid4

from awsiotclient import jobs
import boto3


from .common import init_connection


class TestJobs(unittest.TestCase):
    THING_NAME = "awsiotclient-test"

    def setUp(self):
        self.connection = init_connection("jobs")
        pass

    def test_jobs(self):
        client = boto3.client("iot")

        job_id = f"jobs-test-{uuid4()}"
        region = environ["AWS_REGION"]
        account = environ["AWS_ACCOUNT_ID"]
        target = f"arn:aws:iot:{region}:{account}:thing/{self.THING_NAME}"
        template = f"arn:aws:iot:{region}::jobtemplate/AWS-Run-Command:1.0"

        client.create_job(
            jobId=job_id,
            targets=[target],
            jobTemplateArn=template,
            documentParameters=dict(command="echo ok"),
        )

        incoming = False

        def callback(id, document):
            self.assertEqual(id, job_id)
            self.assertEqual(document["version"], "1.0")
            self.assertEqual(
                document["steps"][0]["action"]["input"]["command"], "echo ok"
            )

            nonlocal incoming
            incoming = True

        client = jobs.client(self.connection, self.THING_NAME, job_func=callback)

        while not incoming:
            sleep(0.1)
