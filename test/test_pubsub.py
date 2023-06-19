import unittest
from time import sleep

from awsiotclient import pubsub

from .common import init_connection


class TestPubSub(unittest.TestCase):
    def setUp(self):
        self.pub_conn = init_connection("pub")
        self.sub_conn = init_connection("sub")

    def test_pubsub(self):
        count = 0

        def callback(topic, payload):
            self.assertEqual(topic, "test/topic")
            self.assertEqual(payload, {"hoge": "fuga"})

            nonlocal count
            count += 1

        _sub = pubsub.Subscriber(self.sub_conn, "test/topic", callback=callback)

        pub = pubsub.Publisher(self.pub_conn, "test/topic")
        pub.publish({"hoge": "fuga"}).result()

        while True:
            if count > 0:
                break
            sleep(0.1)

        self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
