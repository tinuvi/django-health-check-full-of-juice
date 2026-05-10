import logging
import socket

from django_q.conf import Conf
from django_q.status import Stat

from health_check.backends import BaseHealthCheckBackend
from health_check.conf import get_setting
from health_check.exceptions import ServiceUnavailable

_logger = logging.getLogger("django_health_check_full_of_juice")

_DEFAULT_UNHEALTHY_STATUSES = frozenset({"Stopping", "Stopped"})


class _DjangoQBaseHealthCheck(BaseHealthCheckBackend):
    """Shared base for Django-Q cluster health checks."""

    critical_service = True
    local_only = False

    def _resolve_cluster_name(self):
        return get_setting("DJANGO_Q_CLUSTER_NAME", default_value=Conf.CLUSTER_NAME)

    def _resolve_unhealthy_statuses(self):
        statuses = get_setting("DJANGO_Q_UNHEALTHY_STATUSES", default_value=_DEFAULT_UNHEALTHY_STATUSES)
        return frozenset(statuses)

    def _get_stats(self):
        return Stat.get_all()

    def check_status(self):
        cluster_name = self._resolve_cluster_name()
        unhealthy_statuses = self._resolve_unhealthy_statuses()

        try:
            stats = self._get_stats()
        except Exception as exc:
            self.add_error(
                ServiceUnavailable("Unable to read Django-Q cluster heartbeats"),
                exc,
            )
            return

        if self.local_only:
            current_host = socket.gethostname()
            stats = [stat for stat in stats if getattr(stat, "host", None) == current_host]
            scope_label = "local"
            scope_detail = f" on host {current_host}"
        else:
            scope_label = "fleet"
            scope_detail = ""

        if not stats:
            _logger.warning(
                "No Django-Q %s heartbeats found for cluster %s%s",
                scope_label,
                cluster_name,
                scope_detail,
            )
            self.add_error(
                ServiceUnavailable(
                    f"No Django-Q {scope_label} heartbeats found for cluster {cluster_name}{scope_detail}"
                ),
            )
            return

        for stat in stats:
            status = getattr(stat, "status", None)
            if status in unhealthy_statuses:
                self.add_error(
                    ServiceUnavailable(f"Django-Q cluster {cluster_name} reported unhealthy status {status!r}"),
                )


class DjangoQClusterHealthCheck(_DjangoQBaseHealthCheck):
    """
    Fleet-level Django-Q heartbeat check.

    Passes when at least one Django-Q sentinel for the configured cluster
    name has published a recent heartbeat with a healthy status. Suitable
    for the `integrations` subset on the web tier.
    """

    local_only = False


class DjangoQLocalHealthCheck(_DjangoQBaseHealthCheck):
    """
    Pod-local Django-Q heartbeat check.

    Same as :class:`DjangoQClusterHealthCheck` but additionally requires a
    fresh heartbeat from the current host. Suitable for the `liveness`
    subset on a Django-Q worker pod: the broker TTL of 3 seconds means a
    wedged or dead sentinel disappears within ~3 seconds.
    """

    local_only = True
