import logging

from amqp.exceptions import AccessRefused
from django.conf import settings
from kombu import Connection

from health_check.backends import BaseHealthCheckBackend
from health_check.exceptions import ServiceUnavailable

_logger = logging.getLogger("django_health_check_full_of_juice")


class RabbitMQHealthCheck(BaseHealthCheckBackend):
    """Health check for RabbitMQ."""

    namespace = None

    def check_status(self):
        """Check RabbitMQ service by opening and closing a broker channel."""
        _logger.debug("Checking for a broker_url on django settings...")

        broker_url_setting_key = f"{self.namespace}_BROKER_URL" if self.namespace else "BROKER_URL"
        broker_url = getattr(settings, broker_url_setting_key, None)

        _logger.debug("Got %s as the broker_url. Connecting to rabbit...", broker_url)

        _logger.debug("Attempting to connect to rabbit...")
        try:
            # conn is used as a context to release opened resources later
            with Connection(broker_url) as conn:
                conn.connect()  # exceptions may be raised upon calling connect
        except ConnectionRefusedError as e:
            self.add_error(
                ServiceUnavailable("Unable to connect to RabbitMQ: Connection was refused."),
                e,
            )

        except AccessRefused as e:
            self.add_error(
                ServiceUnavailable("Unable to connect to RabbitMQ: Authentication error."),
                e,
            )

        except OSError as e:
            self.add_error(ServiceUnavailable("IOError"), e)

        except Exception as e:
            self.add_error(ServiceUnavailable("Unknown error"), e)
        else:
            _logger.debug("Connection established. RabbitMQ is healthy.")
