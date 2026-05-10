from unittest import TestCase, mock

from redis.exceptions import ConnectionError, TimeoutError

from health_check.contrib.redis.backends import RedisHealthCheck
from health_check.exceptions import ServiceUnavailable


class TestRedisHealthCheck(TestCase):
    """Test Redis health check."""

    @mock.patch("health_check.contrib.redis.backends.getattr")
    @mock.patch("health_check.contrib.redis.backends.from_url", autospec=True)
    def test_redis_refused_connection(self, mocked_connection, mocked_getattr):
        """Test when the connection to Redis is refused."""
        mocked_getattr.return_value = "redis_url"

        # mock returns
        mocked_connection.return_value = mock.MagicMock()
        mocked_connection.return_value.__enter__.side_effect = ConnectionRefusedError("Refused connection")

        # instantiates the class
        redis_healthchecker = RedisHealthCheck()

        # invokes the method check_status()
        redis_healthchecker.check_status()
        self.assertEqual(len(redis_healthchecker.errors), 1)
        self.assertIsInstance(redis_healthchecker.errors[0], ServiceUnavailable)
        self.assertEqual(
            redis_healthchecker.errors[0].message,
            "Unable to connect to Redis: Connection was refused.",
        )

        # mock assertions
        mocked_connection.assert_called_once_with("redis://localhost/1", **{})

    @mock.patch("health_check.contrib.redis.backends.getattr")
    @mock.patch("health_check.contrib.redis.backends.from_url")
    def test_redis_timeout_error(self, mocked_connection, mocked_getattr):
        """Test Redis TimeoutError."""
        mocked_getattr.return_value = "redis_url"

        # mock returns
        mocked_connection.return_value = mock.MagicMock()
        mocked_connection.return_value.__enter__.side_effect = TimeoutError("Timeout Error")

        # instantiates the class
        redis_healthchecker = RedisHealthCheck()

        # invokes the method check_status()
        redis_healthchecker.check_status()
        self.assertEqual(len(redis_healthchecker.errors), 1)
        self.assertIsInstance(redis_healthchecker.errors[0], ServiceUnavailable)
        self.assertEqual(redis_healthchecker.errors[0].message, "Unable to connect to Redis: Timeout.")

        # mock assertions
        mocked_connection.assert_called_once_with("redis://localhost/1", **{})

    @mock.patch("health_check.contrib.redis.backends.getattr")
    @mock.patch("health_check.contrib.redis.backends.from_url")
    def test_redis_con_limit_exceeded(self, mocked_connection, mocked_getattr):
        """Test Connection Limit Exceeded error."""
        mocked_getattr.return_value = "redis_url"

        # mock returns
        mocked_connection.return_value = mock.MagicMock()
        mocked_connection.return_value.__enter__.side_effect = ConnectionError("Connection Error")

        # instantiates the class
        redis_healthchecker = RedisHealthCheck()

        # invokes the method check_status()
        redis_healthchecker.check_status()
        self.assertEqual(len(redis_healthchecker.errors), 1)
        self.assertIsInstance(redis_healthchecker.errors[0], ServiceUnavailable)
        self.assertEqual(redis_healthchecker.errors[0].message, "Unable to connect to Redis: Connection Error")

        # mock assertions
        mocked_connection.assert_called_once_with("redis://localhost/1", **{})

    @mock.patch("health_check.contrib.redis.backends.getattr")
    @mock.patch("health_check.contrib.redis.backends.from_url")
    def test_redis_conn_ok(self, mocked_connection, mocked_getattr):
        """Test the success path: ping returns without raising and no error is recorded."""
        mocked_getattr.return_value = "redis_url"

        # mock returns: default MagicMock chain so ``with from_url(...) as conn: conn.ping()`` succeeds
        mocked_connection.return_value = mock.MagicMock()

        # instantiates the class
        redis_healthchecker = RedisHealthCheck()

        # invokes the method check_status()
        redis_healthchecker.check_status()
        self.assertEqual(redis_healthchecker.errors, [])

        # mock assertions
        mocked_connection.assert_called_once_with("redis://localhost/1", **{})
        mocked_connection.return_value.__enter__.return_value.ping.assert_called_once_with()

    @mock.patch("health_check.contrib.redis.backends.getattr")
    @mock.patch("health_check.contrib.redis.backends.from_url")
    def test_redis_base_exceptions_propagate(self, mocked_connection, mocked_getattr):
        """
        ``BaseException`` subclasses outside the ``Exception`` hierarchy must propagate.

        The unknown-error handler is intentionally narrowed to ``Exception`` so a
        ``KeyboardInterrupt`` (or ``SystemExit``) shutting a worker down is not silently
        swallowed and re-reported as a routine health-check error.
        """
        mocked_getattr.return_value = "redis_url"
        mocked_connection.return_value = mock.MagicMock()
        mocked_connection.return_value.__enter__.side_effect = KeyboardInterrupt("ctrl-c")

        redis_healthchecker = RedisHealthCheck()
        with self.assertRaises(KeyboardInterrupt):
            redis_healthchecker.check_status()

    @mock.patch("health_check.contrib.redis.backends.getattr")
    @mock.patch("health_check.contrib.redis.backends.from_url")
    def test_redis_unknown_error(self, mocked_connection, mocked_getattr):
        """Test the catch-all path: any unexpected exception is recorded as an Unknown error."""
        mocked_getattr.return_value = "redis_url"

        # mock returns: an unexpected exception that is not in the explicit ``except`` list
        mocked_connection.return_value = mock.MagicMock()
        mocked_connection.return_value.__enter__.side_effect = RuntimeError("boom")

        # instantiates the class
        redis_healthchecker = RedisHealthCheck()

        # invokes the method check_status()
        redis_healthchecker.check_status()
        self.assertEqual(len(redis_healthchecker.errors), 1)
        self.assertIsInstance(redis_healthchecker.errors[0], ServiceUnavailable)
        self.assertEqual(redis_healthchecker.errors[0].message, "Unknown error")

        # mock assertions
        mocked_connection.assert_called_once_with("redis://localhost/1", **{})
