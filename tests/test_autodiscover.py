from celery import current_app
from django.conf import settings
from django.test import SimpleTestCase

from health_check.contrib.celery.backends import CeleryHealthCheck
from health_check.contrib.celery_ping.backends import CeleryPingHealthCheck
from health_check.plugins import plugin_dir

# These apps are validated separately by ``test_discover_celery_queues``: they
# don't follow the one-app/one-plugin shape (``celery`` registers a class per
# AMQP queue, ``celery_ping`` registers a single broker-ping backend).
_BROKER_CELERY_APPS = frozenset(
    {
        "health_check.contrib.celery",
        "health_check.contrib.celery_ping",
    }
)


class TestAutoDiscover(SimpleTestCase):
    def test_autodiscover(self):
        expected_apps = {
            app for app in settings.INSTALLED_APPS if app.startswith("health_check.") and app not in _BROKER_CELERY_APPS
        }

        discovered_apps = {
            plugin.__module__.rsplit(".", 1)[0]
            for plugin, _ in plugin_dir._registry
            if not issubclass(plugin, (CeleryHealthCheck, CeleryPingHealthCheck))
        }

        # Every non-broker-celery health_check.* app should contribute at least
        # one auto-registered plugin and vice versa, regardless of how many
        # plugins each app registers.
        self.assertEqual(expected_apps, discovered_apps)

    def test_discover_celery_queues(self):
        celery_plugins = [x for x in plugin_dir._registry if issubclass(x[0], CeleryHealthCheck)]
        self.assertEqual(len(celery_plugins), len(current_app.amqp.queues))
