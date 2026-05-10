from unittest import TestCase, mock

from amqp.exceptions import AccessRefused

from health_check.contrib.rabbitmq.backends import RabbitMQHealthCheck
from health_check.exceptions import ServiceUnavailable


class TestRabbitMQHealthCheck(TestCase):
    """Test RabbitMQ health check."""

    @mock.patch("health_check.contrib.rabbitmq.backends.getattr")
    @mock.patch("health_check.contrib.rabbitmq.backends.Connection")
    def test_broker_refused_connection(self, mocked_connection, mocked_getattr):
        """Test when the connection to RabbitMQ is refused."""
        mocked_getattr.return_value = "broker_url"

        conn_exception = ConnectionRefusedError("Refused connection")

        # mock returns
        mocked_conn = mock.MagicMock()
        mocked_connection.return_value.__enter__.return_value = mocked_conn
        mocked_conn.connect.side_effect = conn_exception

        # instantiates the class
        rabbitmq_healthchecker = RabbitMQHealthCheck()

        # invokes the method check_status()
        rabbitmq_healthchecker.check_status()
        self.assertEqual(len(rabbitmq_healthchecker.errors), 1)
        self.assertIsInstance(rabbitmq_healthchecker.errors[0], ServiceUnavailable)
        self.assertEqual(
            rabbitmq_healthchecker.errors[0].message,
            "Unable to connect to RabbitMQ: Connection was refused.",
        )

        # mock assertions
        mocked_connection.assert_called_once_with("broker_url")

    @mock.patch("health_check.contrib.rabbitmq.backends.getattr")
    @mock.patch("health_check.contrib.rabbitmq.backends.Connection")
    def test_broker_auth_error(self, mocked_connection, mocked_getattr):
        """Test that the connection to RabbitMQ has an authentication error."""
        mocked_getattr.return_value = "broker_url"

        conn_exception = AccessRefused("Refused connection")

        # mock returns
        mocked_conn = mock.MagicMock()
        mocked_connection.return_value.__enter__.return_value = mocked_conn
        mocked_conn.connect.side_effect = conn_exception

        # instantiates the class
        rabbitmq_healthchecker = RabbitMQHealthCheck()

        # invokes the method check_status()
        rabbitmq_healthchecker.check_status()
        self.assertEqual(len(rabbitmq_healthchecker.errors), 1)
        self.assertIsInstance(rabbitmq_healthchecker.errors[0], ServiceUnavailable)
        self.assertEqual(
            rabbitmq_healthchecker.errors[0].message,
            "Unable to connect to RabbitMQ: Authentication error.",
        )

        # mock assertions
        mocked_connection.assert_called_once_with("broker_url")

    @mock.patch("health_check.contrib.rabbitmq.backends.getattr")
    @mock.patch("health_check.contrib.rabbitmq.backends.Connection")
    def test_base_exceptions_propagate(self, mocked_connection, mocked_getattr):
        """
        ``BaseException`` subclasses outside the ``Exception`` hierarchy must propagate.

        Narrowing the catch-all from ``BaseException`` to ``Exception`` makes sure
        ``KeyboardInterrupt`` is not converted into a routine health-check error.
        """
        mocked_getattr.return_value = "broker_url"
        mocked_conn = mock.MagicMock()
        mocked_connection.return_value.__enter__.return_value = mocked_conn
        mocked_conn.connect.side_effect = KeyboardInterrupt("ctrl-c")

        rabbitmq_healthchecker = RabbitMQHealthCheck()
        with self.assertRaises(KeyboardInterrupt):
            rabbitmq_healthchecker.check_status()

    @mock.patch("health_check.contrib.rabbitmq.backends.getattr")
    @mock.patch("health_check.contrib.rabbitmq.backends.Connection")
    def test_broker_connection_upon_none_url(self, mocked_connection, mocked_getattr):
        """Thest when the connection to RabbitMQ has no ``broker_url``."""
        mocked_getattr.return_value = None
        # if the variable BROKER_URL is not set, AccessRefused exception is raised
        conn_exception = AccessRefused("Refused connection")

        # mock returns
        mocked_conn = mock.MagicMock()
        mocked_connection.return_value.__enter__.return_value = mocked_conn
        mocked_conn.connect.side_effect = conn_exception

        # instantiates the class
        rabbitmq_healthchecker = RabbitMQHealthCheck()

        # invokes the method check_status()
        rabbitmq_healthchecker.check_status()
        self.assertEqual(len(rabbitmq_healthchecker.errors), 1)
        self.assertIsInstance(rabbitmq_healthchecker.errors[0], ServiceUnavailable)
        self.assertEqual(
            rabbitmq_healthchecker.errors[0].message,
            "Unable to connect to RabbitMQ: Authentication error.",
        )

        # mock assertions
        mocked_connection.assert_called_once_with(None)
