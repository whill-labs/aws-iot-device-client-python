import unittest
from time import sleep

from awsiotclient import classic_shadow

from .common import init_connection


class TestClassicShadow(unittest.TestCase):
    THING_NAME = "awsiotclient-test"

    def setUp(self):
        self.device_conn = init_connection("device")
        self.app_conn = init_connection("app")

    def test_classic_shadow_reported(self):
        client = classic_shadow.client(
            connection=self.device_conn,
            thing_name=self.THING_NAME,
            shadow_property="test-shadow",
        )

        client.change_reported_value({"hoge": "piyo"}).result()

    def test_classic_shadow_reported_value_delta(self):
        SHADOW_PROPERTY = "test-shadow-reported-delta-1"

        incoming = False

        def callback(thing_name: str, shadow_property: str, value):
            self.assertEqual(thing_name, self.THING_NAME)
            self.assertEqual(shadow_property, SHADOW_PROPERTY)
            self.assertEqual(value, {"hoge": "piyo"})

            nonlocal incoming
            incoming = True

        device_client = classic_shadow.client(
            connection=self.device_conn,
            thing_name=self.THING_NAME,
            shadow_property=SHADOW_PROPERTY,
            delta_func=callback,
        )

        app_client = classic_shadow.client(
            connection=self.app_conn,
            thing_name=self.THING_NAME,
            shadow_property=SHADOW_PROPERTY,
        )

        app_client.change_desired_value({"hoge": "piyo"}).result()

        while not incoming:
            sleep(0.1)

    def test_classic_shadow_desired_matches_with_reported(self):
        SHADOW_PROPERTY = "test-shadow-reported-delta-2"

        incoming = False

        def callback(thing_name: str, shadow_property: str, value):
            nonlocal incoming
            incoming = True

        device_client = classic_shadow.client(
            connection=self.device_conn,
            thing_name=self.THING_NAME,
            shadow_property=SHADOW_PROPERTY,
            delta_func=callback,
        )

        device_client.change_reported_value({"hoge": "fuga"}).result()

        sleep(0.5)

        app_client = classic_shadow.client(
            connection=self.app_conn,
            thing_name=self.THING_NAME,
            shadow_property=SHADOW_PROPERTY,
        )

        app_client.change_desired_value({"hoge": "fuga"}).result()

        sleep(0.5)

        self.assertFalse(incoming)


if __name__ == "__main__":
    unittest.main()
