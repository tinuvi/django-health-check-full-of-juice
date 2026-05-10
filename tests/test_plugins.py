from unittest import TestCase

from health_check.backends import BaseHealthCheckBackend
from health_check.plugins import plugin_dir


class FakePlugin(BaseHealthCheckBackend):
    def check_status(self):
        pass


class Plugin(BaseHealthCheckBackend):
    def check_status(self):
        pass


class TestPlugin(TestCase):
    def setUp(self):
        plugin_dir.reset()
        plugin_dir.register(FakePlugin)
        self.addCleanup(plugin_dir.reset)

    def test_register_plugin(self):
        self.assertEqual(len(plugin_dir._registry), 1)
