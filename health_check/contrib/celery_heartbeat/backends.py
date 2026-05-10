import logging
import os
import time

from health_check.backends import BaseHealthCheckBackend
from health_check.conf import get_setting
from health_check.contrib.celery_heartbeat import DEFAULT_HEARTBEAT_FILE, DEFAULT_HEARTBEAT_MAX_AGE
from health_check.exceptions import ServiceUnavailable

_logger = logging.getLogger("django_health_check_full_of_juice")


class CeleryHeartbeatHealthCheck(BaseHealthCheckBackend):
    """
    File-mtime based Celery worker liveness check.

    Pairs with :class:`health_check.contrib.celery_heartbeat.bootsteps.LivenessProbe`,
    which refreshes the heartbeat file on a timer from inside the Celery
    worker process. The check passes when the heartbeat file's mtime is
    within ``CELERY_HEARTBEAT_MAX_AGE`` seconds of the wall clock.
    """

    critical_service = True

    def check_status(self):
        path = get_setting("CELERY_HEARTBEAT_FILE", default_value=DEFAULT_HEARTBEAT_FILE)
        max_age = get_setting("CELERY_HEARTBEAT_MAX_AGE", default_value=DEFAULT_HEARTBEAT_MAX_AGE)

        try:
            mtime = os.path.getmtime(path)
        except FileNotFoundError as exc:
            _logger.warning("Celery heartbeat file %s is missing", path)
            self.add_error(
                ServiceUnavailable(f"Celery heartbeat file {path} is missing"),
                exc,
            )
            return
        except OSError as exc:
            self.add_error(
                ServiceUnavailable(f"Unable to stat Celery heartbeat file {path}"),
                exc,
            )
            return

        age = time.time() - mtime
        if age > max_age:
            _logger.warning(
                "Celery heartbeat file %s is stale (age=%.2fs > max_age=%ss)",
                path,
                age,
                max_age,
            )
            self.add_error(
                ServiceUnavailable(f"Celery heartbeat file {path} is stale (age={age:.2f}s > max_age={max_age}s)"),
            )
