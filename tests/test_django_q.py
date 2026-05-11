from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from health_check.contrib.django_q.backends import (
    DjangoQClusterHealthCheck,
    DjangoQLocalHealthCheck,
)


def _stat(host="local-host", status="Idle"):
    return SimpleNamespace(host=host, status=status)


class TestDjangoQClusterHealthCheck(SimpleTestCase):
    STAT_GET_ALL = "health_check.contrib.django_q.backends.Stat.get_all"

    def test_passes_when_a_healthy_stat_is_present(self):
        check = DjangoQClusterHealthCheck()
        with patch(self.STAT_GET_ALL, return_value=[_stat(status="Idle")]):
            check.check_status()

        self.assertEqual(check.errors, [])

    def test_passes_when_multiple_healthy_stats_are_present(self):
        check = DjangoQClusterHealthCheck()
        stats = [_stat(host="host-a", status="Idle"), _stat(host="host-b", status="Working")]
        with patch(self.STAT_GET_ALL, return_value=stats):
            check.check_status()

        self.assertEqual(check.errors, [])

    def test_fails_when_no_heartbeats_are_published(self):
        check = DjangoQClusterHealthCheck()
        with patch(self.STAT_GET_ALL, return_value=[]):
            check.check_status()

        self.assertEqual(len(check.errors), 1)
        self.assertIn("no django-q fleet heartbeats", check.errors[0].message.lower())

    def test_fails_when_broker_read_raises(self):
        check = DjangoQClusterHealthCheck()
        with patch(self.STAT_GET_ALL, side_effect=ConnectionError("redis is down")):
            check.check_status()

        self.assertEqual(len(check.errors), 1)
        self.assertIn("unable to read django-q cluster heartbeats", check.errors[0].message.lower())

    def test_base_exceptions_propagate(self):
        """
        Broker-read catch-all is scoped to ``Exception``.

        Worker-shutdown signals (``KeyboardInterrupt``, ``SystemExit``) must not be
        converted into a routine health-check error.
        """
        check = DjangoQClusterHealthCheck()
        with patch(self.STAT_GET_ALL, side_effect=KeyboardInterrupt("ctrl-c")):
            with self.assertRaises(KeyboardInterrupt):
                check.check_status()

    def test_fails_when_status_is_stopped(self):
        check = DjangoQClusterHealthCheck()
        with patch(self.STAT_GET_ALL, return_value=[_stat(status="Stopped")]):
            check.check_status()

        self.assertEqual(len(check.errors), 1)
        self.assertIn("'stopped'", check.errors[0].message.lower())

    def test_fails_when_status_is_stopping(self):
        check = DjangoQClusterHealthCheck()
        with patch(self.STAT_GET_ALL, return_value=[_stat(status="Stopping")]):
            check.check_status()

        self.assertEqual(len(check.errors), 1)
        self.assertIn("'stopping'", check.errors[0].message.lower())

    def test_reports_one_error_per_unhealthy_stat(self):
        check = DjangoQClusterHealthCheck()
        stats = [
            _stat(host="host-a", status="Stopped"),
            _stat(host="host-b", status="Idle"),
            _stat(host="host-c", status="Stopping"),
        ]
        with patch(self.STAT_GET_ALL, return_value=stats):
            check.check_status()

        self.assertEqual(len(check.errors), 2)

    def test_unhealthy_status_set_is_overridable(self):
        check = DjangoQClusterHealthCheck()
        with (
            self.settings(HEALTH_CHECK={"DJANGO_Q_UNHEALTHY_STATUSES": {"Idle"}}),
            patch(self.STAT_GET_ALL, return_value=[_stat(status="Idle")]),
        ):
            check.check_status()

        self.assertEqual(len(check.errors), 1)
        self.assertIn("'idle'", check.errors[0].message.lower())

    def test_cluster_name_defaults_to_q_cluster_setting(self):
        check = DjangoQClusterHealthCheck()
        with patch(self.STAT_GET_ALL, return_value=[]):
            check.check_status()

        # Q_CLUSTER["name"] in tests/testapp/settings.py is "test-cluster".
        self.assertIn("test-cluster", check.errors[0].message)

    def test_cluster_name_setting_overrides_default(self):
        check = DjangoQClusterHealthCheck()
        with (
            self.settings(HEALTH_CHECK={"DJANGO_Q_CLUSTER_NAME": "custom-cluster"}),
            patch(self.STAT_GET_ALL, return_value=[]),
        ):
            check.check_status()

        self.assertIn("custom-cluster", check.errors[0].message)


class TestDjangoQLocalHealthCheck(SimpleTestCase):
    STAT_GET_ALL = "health_check.contrib.django_q.backends.Stat.get_all"
    GETHOSTNAME = "health_check.contrib.django_q.backends.socket.gethostname"

    def test_passes_when_a_local_stat_is_fresh_and_healthy(self):
        check = DjangoQLocalHealthCheck()
        stats = [_stat(host="other-host", status="Idle"), _stat(host="me", status="Idle")]
        with patch(self.GETHOSTNAME, return_value="me"), patch(self.STAT_GET_ALL, return_value=stats):
            check.check_status()

        self.assertEqual(check.errors, [])

    def test_fails_when_no_stat_for_local_host(self):
        check = DjangoQLocalHealthCheck()
        stats = [_stat(host="other-host", status="Idle")]
        with patch(self.GETHOSTNAME, return_value="me"), patch(self.STAT_GET_ALL, return_value=stats):
            check.check_status()

        self.assertEqual(len(check.errors), 1)
        message = check.errors[0].message.lower()
        self.assertIn("no django-q local heartbeats", message)
        self.assertIn("on host me", message)

    def test_fails_when_local_stat_is_unhealthy(self):
        check = DjangoQLocalHealthCheck()
        stats = [_stat(host="me", status="Stopped"), _stat(host="other-host", status="Idle")]
        with patch(self.GETHOSTNAME, return_value="me"), patch(self.STAT_GET_ALL, return_value=stats):
            check.check_status()

        self.assertEqual(len(check.errors), 1)
        self.assertIn("'stopped'", check.errors[0].message.lower())

    def test_remote_unhealthy_stats_do_not_affect_local_check(self):
        check = DjangoQLocalHealthCheck()
        stats = [_stat(host="me", status="Idle"), _stat(host="other-host", status="Stopped")]
        with patch(self.GETHOSTNAME, return_value="me"), patch(self.STAT_GET_ALL, return_value=stats):
            check.check_status()

        self.assertEqual(check.errors, [])
