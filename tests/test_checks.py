from django.test import SimpleTestCase

from health_check.checks import LIVENESS_MIDDLEWARE_DOTTED, liveness_middleware_first


class TestLivenessMiddlewareFirst(SimpleTestCase):
    def test_no_warning_when_middleware_absent(self):
        with self.settings(MIDDLEWARE=["django.middleware.security.SecurityMiddleware"]):
            self.assertEqual(liveness_middleware_first(None), [])

    def test_no_warning_when_middleware_is_first(self):
        with self.settings(
            MIDDLEWARE=[
                LIVENESS_MIDDLEWARE_DOTTED,
                "django.middleware.security.SecurityMiddleware",
            ]
        ):
            self.assertEqual(liveness_middleware_first(None), [])

    def test_warns_when_middleware_is_not_first(self):
        with self.settings(
            MIDDLEWARE=[
                "django.middleware.security.SecurityMiddleware",
                LIVENESS_MIDDLEWARE_DOTTED,
            ]
        ):
            warnings = liveness_middleware_first(None)
            self.assertEqual(len(warnings), 1)
            self.assertEqual(warnings[0].id, "health_check.W001")

    def test_no_warning_when_middleware_setting_missing(self):
        with self.settings(MIDDLEWARE=None):
            self.assertEqual(liveness_middleware_first(None), [])
