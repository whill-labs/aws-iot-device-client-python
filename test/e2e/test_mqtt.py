import unittest


from .common import init_connection


class TestMqtt(unittest.TestCase):
    def test_mqtt_setup(self):
        init_connection("test")


if __name__ == "__main__":
    unittest.main()
