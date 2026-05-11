from django.test import SimpleTestCase

from health_check.backends import BaseHealthCheckBackend
from health_check.checks import LIVENESS_MIDDLEWARE_DOTTED, liveness_middleware_first, subsets_resolve


class _OkBackend(BaseHealthCheckBackend):
    def check_status(self):
        pass


class _NotABackend:
    pass


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


class TestSubsetsResolve(SimpleTestCase):
    def test_no_errors_when_no_subsets_configured(self):
        with self.settings(HEALTH_CHECK={}):
            self.assertEqual(subsets_resolve(None), [])

    def test_no_errors_for_valid_dotted_paths(self):
        with self.settings(HEALTH_CHECK={"SUBSETS": {"probe": ["tests.test_checks._OkBackend"]}}):
            self.assertEqual(subsets_resolve(None), [])

    def test_error_on_unimportable_path(self):
        with self.settings(HEALTH_CHECK={"SUBSETS": {"probe": ["tests.test_checks.does_not_exist"]}}):
            errors = subsets_resolve(None)
            self.assertEqual(len(errors), 1)
            self.assertEqual(errors[0].id, "health_check.E004")
            self.assertIn("does_not_exist", errors[0].msg)

    def test_error_on_non_backend_subclass(self):
        with self.settings(HEALTH_CHECK={"SUBSETS": {"probe": ["tests.test_checks._NotABackend"]}}):
            errors = subsets_resolve(None)
            self.assertEqual(len(errors), 1)
            self.assertEqual(errors[0].id, "health_check.E004")

    def test_error_on_non_list_subset_value(self):
        with self.settings(HEALTH_CHECK={"SUBSETS": {"probe": "tests.test_checks._OkBackend"}}):
            errors = subsets_resolve(None)
            self.assertEqual(len(errors), 1)
            self.assertEqual(errors[0].id, "health_check.E002")

    def test_error_on_non_string_non_sequence_entry(self):
        with self.settings(HEALTH_CHECK={"SUBSETS": {"probe": [_OkBackend]}}):
            errors = subsets_resolve(None)
            self.assertEqual(len(errors), 1)
            self.assertEqual(errors[0].id, "health_check.E005")

    def test_error_on_tuple_with_wrong_arity(self):
        with self.settings(HEALTH_CHECK={"SUBSETS": {"probe": [("tests.test_checks._OkBackend",)]}}):
            errors = subsets_resolve(None)
            self.assertEqual(len(errors), 1)
            self.assertEqual(errors[0].id, "health_check.E005")

    def test_error_on_tuple_with_non_string_path(self):
        with self.settings(HEALTH_CHECK={"SUBSETS": {"probe": [(_OkBackend, {})]}}):
            errors = subsets_resolve(None)
            self.assertEqual(len(errors), 1)
            self.assertEqual(errors[0].id, "health_check.E005")

    def test_error_on_tuple_with_non_dict_kwargs(self):
        with self.settings(HEALTH_CHECK={"SUBSETS": {"probe": [("tests.test_checks._OkBackend", "not a dict")]}}):
            errors = subsets_resolve(None)
            self.assertEqual(len(errors), 1)
            self.assertEqual(errors[0].id, "health_check.E005")

    def test_no_errors_for_well_formed_tuple_entry(self):
        with self.settings(
            HEALTH_CHECK={"SUBSETS": {"probe": [("tests.test_checks._OkBackend", {"foo": 1})]}},
        ):
            self.assertEqual(subsets_resolve(None), [])

    def test_no_errors_for_list_form_kwargs_entry(self):
        # Settings deserialized from YAML/JSON arrive as lists, not tuples — both must work.
        with self.settings(
            HEALTH_CHECK={"SUBSETS": {"probe": [["tests.test_checks._OkBackend", {"foo": 1}]]}},
        ):
            self.assertEqual(subsets_resolve(None), [])

    def test_caches_resolution_across_subsets(self):
        # The same broken dotted path appearing in two subsets should still
        # surface a separate error per occurrence (so the operator sees both
        # subsets) without re-importing the module twice.
        with self.settings(
            HEALTH_CHECK={
                "SUBSETS": {
                    "a": ["tests.test_checks.missing"],
                    "b": ["tests.test_checks.missing"],
                }
            }
        ):
            errors = subsets_resolve(None)
            self.assertEqual(len(errors), 2)
            self.assertEqual({e.id for e in errors}, {"health_check.E004"})
