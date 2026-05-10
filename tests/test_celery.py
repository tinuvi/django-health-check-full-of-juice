from unittest import TestCase
from unittest.mock import patch

from health_check.contrib.celery.backends import CeleryHealthCheck


class TestCeleryHealthCheck(TestCase):
    APPLY_ASYNC = "health_check.contrib.celery.backends.add.apply_async"

    def test_base_exceptions_propagate(self):
        """
        Unknown-error catch-all is scoped to ``Exception``.

        Worker-shutdown signals (``KeyboardInterrupt``, ``SystemExit``) must not be
        converted into a routine health-check error.
        """
        check = CeleryHealthCheck()
        check.queue = "celery"
        with patch(self.APPLY_ASYNC, side_effect=KeyboardInterrupt("ctrl-c")):
            with self.assertRaises(KeyboardInterrupt):
                check.check_status()
