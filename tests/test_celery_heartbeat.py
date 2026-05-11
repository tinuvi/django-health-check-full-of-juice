import os
import tempfile
import time
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from health_check.contrib.celery_heartbeat import (
    DEFAULT_HEARTBEAT_FILE,
    DEFAULT_HEARTBEAT_INTERVAL,
    DEFAULT_HEARTBEAT_MAX_AGE,
)
from health_check.contrib.celery_heartbeat.backends import CeleryHeartbeatHealthCheck
from health_check.contrib.celery_heartbeat.bootsteps import LivenessProbe


class TestCeleryHeartbeatHealthCheck(SimpleTestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.heartbeat_path = os.path.join(self._tmpdir.name, "celery_worker_heartbeat")

    def _settings(self, **overrides):
        payload = {"CELERY_HEARTBEAT_FILE": self.heartbeat_path}
        payload.update(overrides)
        return self.settings(HEALTH_CHECK=payload)

    def _write_heartbeat(self, age_seconds=0):
        with open(self.heartbeat_path, "ab"):
            pass
        if age_seconds:
            mtime = time.time() - age_seconds
            os.utime(self.heartbeat_path, (mtime, mtime))

    def test_passes_when_heartbeat_file_is_fresh(self):
        self._write_heartbeat()
        check = CeleryHeartbeatHealthCheck()
        with self._settings():
            check.check_status()

        self.assertEqual(check.errors, [])

    def test_fails_when_heartbeat_file_is_missing(self):
        check = CeleryHeartbeatHealthCheck()
        with self._settings():
            check.check_status()

        self.assertEqual(len(check.errors), 1)
        self.assertIn("missing", check.errors[0].message.lower())
        self.assertIn(self.heartbeat_path, check.errors[0].message)

    def test_fails_when_heartbeat_file_is_stale(self):
        self._write_heartbeat(age_seconds=120)
        check = CeleryHeartbeatHealthCheck()
        with self._settings(CELERY_HEARTBEAT_MAX_AGE=60):
            check.check_status()

        self.assertEqual(len(check.errors), 1)
        self.assertIn("stale", check.errors[0].message.lower())

    def test_passes_when_max_age_override_is_generous(self):
        self._write_heartbeat(age_seconds=120)
        check = CeleryHeartbeatHealthCheck()
        with self._settings(CELERY_HEARTBEAT_MAX_AGE=600):
            check.check_status()

        self.assertEqual(check.errors, [])

    def test_fails_on_unexpected_oserror(self):
        check = CeleryHeartbeatHealthCheck()
        with (
            self._settings(),
            patch(
                "health_check.contrib.celery_heartbeat.backends.os.path.getmtime",
                side_effect=PermissionError("denied"),
            ),
        ):
            check.check_status()

        self.assertEqual(len(check.errors), 1)
        self.assertIn("unable to stat", check.errors[0].message.lower())

    def test_uses_module_defaults_when_no_setting_supplied(self):
        # No HEALTH_CHECK setting at all → backend should fall back to the
        # module-level DEFAULT_HEARTBEAT_FILE constant.
        check = CeleryHeartbeatHealthCheck()
        with self.settings():
            check.check_status()

        self.assertEqual(len(check.errors), 1)
        self.assertIn(DEFAULT_HEARTBEAT_FILE, check.errors[0].message)


class TestLivenessProbeBootstep(SimpleTestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.heartbeat_path = os.path.join(self._tmpdir.name, "subdir", "celery_worker_heartbeat")
        self.worker = MagicMock(name="worker")

    def _build(self):
        return LivenessProbe(self.worker)

    def test_init_state(self):
        probe = self._build()
        self.assertEqual(probe.requests, [])
        self.assertIsNone(probe.tref)

    def test_start_creates_file_and_schedules_timer(self):
        probe = self._build()
        with self.settings(
            HEALTH_CHECK={
                "CELERY_HEARTBEAT_FILE": self.heartbeat_path,
                "CELERY_HEARTBEAT_INTERVAL": 2.5,
            }
        ):
            probe.start(self.worker)

        self.assertTrue(os.path.exists(self.heartbeat_path))
        self.worker.timer.call_repeatedly.assert_called_once()
        args, kwargs = self.worker.timer.call_repeatedly.call_args
        self.assertEqual(args[0], 2.5)
        self.assertEqual(args[1], probe._touch)
        self.assertEqual(args[2], (self.heartbeat_path,))
        self.assertEqual(kwargs, {"priority": 10})
        self.assertIs(probe.tref, self.worker.timer.call_repeatedly.return_value)

    def test_start_uses_module_defaults_when_settings_absent(self):
        probe = self._build()
        with (
            self.settings(),
            patch.object(LivenessProbe, "_ensure_file") as ensure_file,
        ):
            probe.start(self.worker)

        ensure_file.assert_called_once_with(DEFAULT_HEARTBEAT_FILE)
        args, _ = self.worker.timer.call_repeatedly.call_args
        self.assertEqual(args[0], DEFAULT_HEARTBEAT_INTERVAL)
        self.assertEqual(args[2], (DEFAULT_HEARTBEAT_FILE,))

    def test_stop_cancels_timer(self):
        probe = self._build()
        tref = MagicMock(name="tref")
        probe.tref = tref

        probe.stop(self.worker)

        tref.cancel.assert_called_once()
        self.assertIsNone(probe.tref)

    def test_stop_is_a_noop_when_no_timer_was_started(self):
        probe = self._build()
        probe.tref = None

        probe.stop(self.worker)  # Must not raise.

        self.assertIsNone(probe.tref)

    def test_touch_updates_mtime(self):
        with open(self.heartbeat_path.replace("/subdir", ""), "wb"):
            pass
        path = self.heartbeat_path.replace("/subdir", "")
        old_mtime = time.time() - 300
        os.utime(path, (old_mtime, old_mtime))

        LivenessProbe._touch(path)

        self.assertGreater(os.path.getmtime(path), old_mtime)

    def test_touch_recreates_missing_file(self):
        path = os.path.join(self._tmpdir.name, "missing-heartbeat")
        self.assertFalse(os.path.exists(path))

        LivenessProbe._touch(path)

        self.assertTrue(os.path.exists(path))

    def test_ensure_file_creates_parent_directories(self):
        nested = os.path.join(self._tmpdir.name, "a", "b", "heartbeat")

        LivenessProbe._ensure_file(nested)

        self.assertTrue(os.path.exists(nested))


class TestCeleryHeartbeatModuleDefaults(SimpleTestCase):
    def test_module_defaults_are_sensible(self):
        # These constants are part of the public API (referenced in CHANGELOG
        # and README); pin them so accidental edits show up in code review.
        self.assertEqual(DEFAULT_HEARTBEAT_FILE, "/tmp/celery_worker_heartbeat")  # noqa: S108
        self.assertEqual(DEFAULT_HEARTBEAT_INTERVAL, 1.0)
        self.assertEqual(DEFAULT_HEARTBEAT_MAX_AGE, 60)
