from unittest import TestCase
from unittest.mock import patch

from django.apps import apps
from django.conf import settings
from django.test import SimpleTestCase

from health_check.contrib.celery_ping.apps import HealthCheckConfig
from health_check.contrib.celery_ping.backends import CeleryPingHealthCheck


class TestCeleryPingHealthCheck(TestCase):
    CELERY_APP_CONTROL_PING = "health_check.contrib.celery_ping.backends.app.control.ping"
    CELERY_APP_CONTROL_INSPECT_ACTIVE_QUEUES = (
        "health_check.contrib.celery_ping.backends.app.control.inspect.active_queues"
    )

    def setUp(self):
        self.health_check = CeleryPingHealthCheck()

    def test_check_status_doesnt_add_errors_when_ping_successful(self):
        celery_worker = "celery@4cc150a7b49b"

        with (
            patch(
                self.CELERY_APP_CONTROL_PING,
                return_value=[
                    {celery_worker: CeleryPingHealthCheck.CORRECT_PING_RESPONSE},
                    {f"{celery_worker}-2": CeleryPingHealthCheck.CORRECT_PING_RESPONSE},
                ],
            ),
            patch(
                self.CELERY_APP_CONTROL_INSPECT_ACTIVE_QUEUES,
                return_value={celery_worker: [{"name": queue.name} for queue in settings.CELERY_QUEUES]},
            ),
        ):
            self.health_check.check_status()

            self.assertEqual(self.health_check.errors, [])

    def test_check_status_reports_errors_if_ping_responses_are_incorrect(self):
        with patch(
            self.CELERY_APP_CONTROL_PING,
            return_value=[
                {"celery1@4cc150a7b49b": CeleryPingHealthCheck.CORRECT_PING_RESPONSE},
                {"celery2@4cc150a7b49b": {}},
                {"celery3@4cc150a7b49b": {"error": "pong"}},
            ],
        ):
            self.health_check.check_status()

            self.assertEqual(len(self.health_check.errors), 2)

    def test_check_status_adds_errors_when_ping_successfull_but_not_all_defined_queues_have_consumers(self):
        celery_worker = "celery@4cc150a7b49b"
        queues = list(settings.CELERY_QUEUES)

        with (
            patch(
                self.CELERY_APP_CONTROL_PING,
                return_value=[{celery_worker: CeleryPingHealthCheck.CORRECT_PING_RESPONSE}],
            ),
            patch(
                self.CELERY_APP_CONTROL_INSPECT_ACTIVE_QUEUES,
                return_value={celery_worker: [{"name": queues.pop().name}]},
            ),
        ):
            self.health_check.check_status()

            self.assertEqual(len(self.health_check.errors), len(queues))

    def test_check_status_add_error_when_io_error_raised_from_ping(self):
        for exception_to_raise in [IOError, TimeoutError]:
            with self.subTest(exception_to_raise=exception_to_raise):
                health_check = CeleryPingHealthCheck()
                with patch(self.CELERY_APP_CONTROL_PING, side_effect=exception_to_raise):
                    health_check.check_status()

                    self.assertEqual(len(health_check.errors), 1)
                    self.assertIn("ioerror", health_check.errors[0].message.lower())

    def test_check_status_add_error_when_any_exception_raised_from_ping(self):
        for exception_to_raise in [ValueError, SystemError, IndexError, MemoryError]:
            with self.subTest(exception_to_raise=exception_to_raise):
                health_check = CeleryPingHealthCheck()
                with patch(self.CELERY_APP_CONTROL_PING, side_effect=exception_to_raise):
                    health_check.check_status()

                    self.assertEqual(len(health_check.errors), 1)
                    self.assertEqual(health_check.errors[0].message.lower(), "unknown error")

    def test_check_status_base_exceptions_propagate(self):
        """
        ``BaseException`` subclasses outside ``Exception`` must not be swallowed.

        After narrowing the catch-all to ``Exception``, ``KeyboardInterrupt`` and
        ``SystemExit`` propagate so a worker shutdown signal is not converted into
        a routine health-check error.
        """
        with patch(self.CELERY_APP_CONTROL_PING, side_effect=KeyboardInterrupt("ctrl-c")):
            with self.assertRaises(KeyboardInterrupt):
                self.health_check.check_status()

    def test_check_status_when_raised_exception_notimplementederror(self):
        expected_error_message = "notimplementederror: make sure celery_result_backend is set"

        with patch(self.CELERY_APP_CONTROL_PING, side_effect=NotImplementedError):
            self.health_check.check_status()

            self.assertEqual(len(self.health_check.errors), 1)
            self.assertEqual(self.health_check.errors[0].message.lower(), expected_error_message)

    def test_check_status_add_error_when_ping_result_failed(self):
        for ping_result in [None, list()]:
            with self.subTest(ping_result=ping_result):
                health_check = CeleryPingHealthCheck()
                with patch(self.CELERY_APP_CONTROL_PING, return_value=ping_result):
                    health_check.check_status()

                    self.assertEqual(len(health_check.errors), 1)
                    self.assertIn("workers unavailable", health_check.errors[0].message.lower())


class TestCeleryPingHealthCheckApps(SimpleTestCase):
    def test_apps(self):
        self.assertEqual(HealthCheckConfig.name, "health_check.contrib.celery_ping")

        celery_ping = apps.get_app_config("celery_ping")
        self.assertEqual(celery_ping.name, "health_check.contrib.celery_ping")
