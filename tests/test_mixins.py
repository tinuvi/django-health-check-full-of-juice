from unittest import TestCase
from unittest.mock import patch

from django.test import override_settings

from health_check.backends import BaseHealthCheckBackend
from health_check.mixins import CheckMixin
from health_check.plugins import plugin_dir


class FailPlugin(BaseHealthCheckBackend):
    def check_status(self):
        self.add_error("Oops")


class OkPlugin(BaseHealthCheckBackend):
    def check_status(self):
        pass


class Checker(CheckMixin):
    pass


class TestCheckMixin(TestCase):
    def setUp(self):
        plugin_dir.reset()
        plugin_dir.register(FailPlugin)
        plugin_dir.register(OkPlugin)
        self.addCleanup(plugin_dir.reset)

    def test_plugins(self):
        for disable_threading in [True, False]:
            with self.subTest(disable_threading=disable_threading):
                with override_settings(HEALTH_CHECK={"DISABLE_THREADING": disable_threading}):
                    self.assertEqual(len(Checker().plugins), 2)

    def test_errors(self):
        for disable_threading in [True, False]:
            with self.subTest(disable_threading=disable_threading):
                with override_settings(HEALTH_CHECK={"DISABLE_THREADING": disable_threading}):
                    self.assertEqual(len(Checker().errors), 1)

    def test_run_check(self):
        for disable_threading in [True, False]:
            with self.subTest(disable_threading=disable_threading):
                with override_settings(HEALTH_CHECK={"DISABLE_THREADING": disable_threading}):
                    self.assertEqual(len(Checker().run_check()), 1)

    def test_run_check_threading_enabled(self):
        """Ensure threading used when not disabled."""
        with override_settings(HEALTH_CHECK={"DISABLE_THREADING": False}):
            # Ensure ThreadPoolExecutor is used
            with patch("health_check.mixins.ThreadPoolExecutor") as tpe:
                Checker().run_check()
                tpe.assert_called()

            # Ensure ThreadPoolExecutor is used
            with patch(
                "django.db.connections.close_all",
            ) as close_all:
                Checker().run_check()
                close_all.assert_called()

    def test_run_check_threading_disabled(self):
        """Ensure threading not used when disabled."""
        with override_settings(HEALTH_CHECK={"DISABLE_THREADING": True}):
            # Ensure ThreadPoolExecutor is not used
            with patch("health_check.mixins.ThreadPoolExecutor") as tpe:
                Checker().run_check()
                tpe.assert_not_called()

                # Ensure ThreadPoolExecutor is used
                with patch(
                    "django.db.connections.close_all",
                ) as close_all:
                    Checker().run_check()
                    close_all.assert_not_called()
