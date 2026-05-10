from django.apps import AppConfig


class HealthCheckConfig(AppConfig):
    name = "health_check"

    def ready(self):
        from . import checks  # noqa: F401
