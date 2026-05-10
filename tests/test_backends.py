import logging
from io import StringIO
from unittest import TestCase

from health_check.backends import BaseHealthCheckBackend
from health_check.exceptions import HealthCheckException


class TestBaseHealthCheckBackend(TestCase):
    def test_run_check(self):
        with self.assertRaises(NotImplementedError):
            BaseHealthCheckBackend().run_check()

    def test_identifier(self):
        self.assertEqual(BaseHealthCheckBackend().identifier(), "BaseHealthCheckBackend")

        class MyHeathCheck(BaseHealthCheckBackend):
            pass

        self.assertEqual(MyHeathCheck().identifier(), "MyHeathCheck")

        class MyHeathCheck(BaseHealthCheckBackend):
            foo = "bar"

            def identifier(self):
                return self.foo

        self.assertEqual(MyHeathCheck().identifier(), "bar")

    def test_status(self):
        ht = BaseHealthCheckBackend()
        self.assertEqual(ht.status, 1)
        ht.errors = [1]
        self.assertEqual(ht.status, 0)

    def test_pretty_status(self):
        ht = BaseHealthCheckBackend()
        self.assertEqual(ht.pretty_status(), "working")
        ht.errors = ["foo"]
        self.assertEqual(ht.pretty_status(), "foo")
        ht.errors.append("bar")
        self.assertEqual(ht.pretty_status(), "foo\nbar")
        ht.errors.append(123)
        self.assertEqual(ht.pretty_status(), "foo\nbar\n123")

    def test_add_error(self):
        ht = BaseHealthCheckBackend()
        e = HealthCheckException("foo")
        ht.add_error(e)
        self.assertIs(ht.errors[0], e)

        ht = BaseHealthCheckBackend()
        ht.add_error("bar")
        self.assertIsInstance(ht.errors[0], HealthCheckException)
        self.assertEqual(str(ht.errors[0]), "unknown error: bar")

        ht = BaseHealthCheckBackend()
        ht.add_error(type)
        self.assertIsInstance(ht.errors[0], HealthCheckException)
        self.assertEqual(str(ht.errors[0]), "unknown error: unknown error")

    def test_add_error_cause(self):
        ht = BaseHealthCheckBackend()
        _logger = logging.getLogger("health-check")
        with StringIO() as stream:
            stream_handler = logging.StreamHandler(stream)
            _logger.addHandler(stream_handler)
            try:
                raise Exception("bar")
            except Exception as e:
                ht.add_error("foo", e)

            stream.seek(0)
            log = stream.read()
            self.assertIn("foo", log)
            self.assertIn("bar", log)
            self.assertIn("Traceback", log)
            self.assertIn("Exception: bar", log)
            _logger.removeHandler(stream_handler)

        with StringIO() as stream:
            stream_handler = logging.StreamHandler(stream)
            _logger.addHandler(stream_handler)
            try:
                raise Exception("bar")
            except Exception:
                ht.add_error("foo")

            stream.seek(0)
            log = stream.read()
            self.assertIn("foo", log)
            self.assertNotIn("bar", log)
            self.assertNotIn("Traceback", log)
            self.assertNotIn("Exception: bar", log)
            _logger.removeHandler(stream_handler)
