import logging
import os
from pathlib import Path

from celery import bootsteps

from health_check.conf import get_setting
from health_check.contrib.celery_heartbeat import DEFAULT_HEARTBEAT_FILE, DEFAULT_HEARTBEAT_INTERVAL

_logger = logging.getLogger("django_health_check_full_of_juice")


class LivenessProbe(bootsteps.StartStopStep):
    """
    Celery worker bootstep that refreshes a heartbeat file on a timer.

    Install this in the user's Celery app definition, e.g.::

        from health_check.contrib.celery_heartbeat.bootsteps import LivenessProbe

        app = Celery("myproject")
        app.steps["worker"].add(LivenessProbe)

    Pair it with :class:`health_check.contrib.celery_heartbeat.backends.CeleryHeartbeatHealthCheck`
    on the worker's ``liveness`` subset.
    """

    requires = ("celery.worker.components:Timer",)

    def __init__(self, worker, **kwargs):
        self.requests = []
        self.tref = None

    def start(self, worker):
        path = get_setting("CELERY_HEARTBEAT_FILE", default_value=DEFAULT_HEARTBEAT_FILE)
        interval = get_setting("CELERY_HEARTBEAT_INTERVAL", default_value=DEFAULT_HEARTBEAT_INTERVAL)
        self._ensure_file(path)
        _logger.info(
            "Starting Celery LivenessProbe heartbeat at %s (interval=%ss)",
            path,
            interval,
        )
        self.tref = worker.timer.call_repeatedly(
            interval,
            self._touch,
            (path,),
            priority=10,
        )

    def stop(self, worker):
        if self.tref is not None:
            try:
                self.tref.cancel()
            except Exception:  # pragma: no cover - defensive
                _logger.exception("Failed to cancel Celery LivenessProbe timer")
            self.tref = None

    @staticmethod
    def _ensure_file(path):
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        # Create the file once so the very first probe immediately after
        # worker start has a fresh mtime to inspect.
        Path(path).touch()

    @staticmethod
    def _touch(path):
        try:
            os.utime(path, None)
        except FileNotFoundError:
            # File was removed (e.g. tmp cleaner); recreate it so the next
            # probe sees a fresh mtime instead of a hard failure.
            Path(path).touch()
