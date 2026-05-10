from django.apps import AppConfig

from health_check.plugins import plugin_dir


class HealthCheckConfig(AppConfig):
    name = "health_check.contrib.django_q"

    def ready(self):
        from .backends import DjangoQClusterHealthCheck, DjangoQLocalHealthCheck

        plugin_dir.register(DjangoQClusterHealthCheck)
        plugin_dir.register(DjangoQLocalHealthCheck)
