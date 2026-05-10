from django.test import SimpleTestCase

from health_check.contrib.psutil.apps import HealthCheckConfig
from health_check.contrib.psutil.backends import DiskUsage, MemoryUsage
from health_check.plugins import plugin_dir


class TestPsutilHealthCheckConfigRegistration(SimpleTestCase):
    """
    Pin which plugins ``HealthCheckConfig.ready()`` registers.

    Each ``HEALTH_CHECK`` key (``DISK_USAGE_MAX``, ``MEMORY_MIN``) controls its
    matching plugin independently: an explicit ``None`` disables the plugin;
    any other value (or an absent key) keeps it enabled.
    """

    def setUp(self):
        plugin_dir.reset()
        self.addCleanup(plugin_dir.reset)

    def _invoke_ready(self):
        # ``ready()`` only uses ``self`` as the receiver, never reading
        # any attribute, so we can construct a bare instance and call it
        # directly instead of going through ``django.apps`` machinery.
        config = HealthCheckConfig.__new__(HealthCheckConfig)
        config.ready()

    def _registered_classes(self):
        return [cls for cls, _options in plugin_dir._registry]

    def test_both_registered_when_no_health_check_setting(self):
        with self.settings():
            self._invoke_ready()

        self.assertIn(DiskUsage, self._registered_classes())
        self.assertIn(MemoryUsage, self._registered_classes())

    def test_both_registered_when_health_check_setting_is_empty(self):
        with self.settings(HEALTH_CHECK={}):
            self._invoke_ready()

        self.assertIn(DiskUsage, self._registered_classes())
        self.assertIn(MemoryUsage, self._registered_classes())

    def test_disk_usage_skipped_when_disk_usage_max_is_none(self):
        with self.settings(HEALTH_CHECK={"DISK_USAGE_MAX": None}):
            self._invoke_ready()

        self.assertNotIn(DiskUsage, self._registered_classes())
        self.assertIn(MemoryUsage, self._registered_classes())

    def test_memory_usage_skipped_when_memory_min_is_none(self):
        with self.settings(HEALTH_CHECK={"MEMORY_MIN": None}):
            self._invoke_ready()

        self.assertIn(DiskUsage, self._registered_classes())
        self.assertNotIn(MemoryUsage, self._registered_classes())

    def test_neither_registered_when_both_keys_are_none(self):
        with self.settings(HEALTH_CHECK={"DISK_USAGE_MAX": None, "MEMORY_MIN": None}):
            self._invoke_ready()

        self.assertNotIn(DiskUsage, self._registered_classes())
        self.assertNotIn(MemoryUsage, self._registered_classes())

    def test_both_registered_with_non_none_values(self):
        with self.settings(HEALTH_CHECK={"DISK_USAGE_MAX": 90, "MEMORY_MIN": 100}):
            self._invoke_ready()

        self.assertIn(DiskUsage, self._registered_classes())
        self.assertIn(MemoryUsage, self._registered_classes())

    def test_memory_min_absent_does_not_disable_memory_usage(self):
        # Regression: a previous bug short-circuited the MemoryUsage gate on
        # ``DISK_USAGE_MAX`` membership, so leaving ``MEMORY_MIN`` out and
        # setting ``DISK_USAGE_MAX`` to a non-None value would mistakenly raise
        # a ``KeyError`` when looking up ``MEMORY_MIN``.
        with self.settings(HEALTH_CHECK={"DISK_USAGE_MAX": 90}):
            self._invoke_ready()

        self.assertIn(DiskUsage, self._registered_classes())
        self.assertIn(MemoryUsage, self._registered_classes())

    def test_disk_usage_max_absent_does_not_disable_disk_usage(self):
        # Symmetric guard: with only ``MEMORY_MIN`` set, both plugins should
        # still register.
        with self.settings(HEALTH_CHECK={"MEMORY_MIN": 100}):
            self._invoke_ready()

        self.assertIn(DiskUsage, self._registered_classes())
        self.assertIn(MemoryUsage, self._registered_classes())
