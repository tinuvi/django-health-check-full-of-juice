from unittest.mock import patch

from django.core.exceptions import ImproperlyConfigured
from django.http import Http404
from django.test import SimpleTestCase, override_settings

from health_check.backends import BaseHealthCheckBackend
from health_check.mixins import CheckMixin, parse_subset_entry, resolve_backend


class FailPlugin(BaseHealthCheckBackend):
    def check_status(self):
        self.add_error("Oops")


class OkPlugin(BaseHealthCheckBackend):
    def check_status(self):
        pass


class ParameterizedPlugin(BaseHealthCheckBackend):
    """A backend with required kwargs — exercises the (path, kwargs) tuple form."""

    def __init__(self, *, alias):
        super().__init__()
        self.alias = alias

    def identifier(self):
        # Distinct identifier per kwargs so two instances don't collide in the result dict.
        return f"ParameterizedPlugin: {self.alias}"

    def check_status(self):
        pass


class Checker(CheckMixin):
    pass


_SUBSET_BOTH = {
    "all": [
        "tests.test_mixins.FailPlugin",
        "tests.test_mixins.OkPlugin",
    ],
}


class TestParseSubsetEntry(SimpleTestCase):
    def test_string_entry_yields_empty_kwargs(self):
        self.assertEqual(parse_subset_entry("tests.test_mixins.OkPlugin"), ("tests.test_mixins.OkPlugin", {}))

    def test_tuple_entry_yields_kwargs(self):
        self.assertEqual(
            parse_subset_entry(("tests.test_mixins.ParameterizedPlugin", {"alias": "primary"})),
            ("tests.test_mixins.ParameterizedPlugin", {"alias": "primary"}),
        )

    def test_list_entry_yields_kwargs(self):
        # YAML/JSON-deserialized settings arrive as lists; both shapes must work.
        self.assertEqual(
            parse_subset_entry(["tests.test_mixins.ParameterizedPlugin", {"alias": "primary"}]),
            ("tests.test_mixins.ParameterizedPlugin", {"alias": "primary"}),
        )

    def test_rejects_wrong_arity(self):
        with self.assertRaises(ImproperlyConfigured):
            parse_subset_entry(("tests.test_mixins.OkPlugin",))

    def test_rejects_non_string_path(self):
        with self.assertRaises(ImproperlyConfigured):
            parse_subset_entry((OkPlugin, {}))

    def test_rejects_non_dict_kwargs(self):
        with self.assertRaises(ImproperlyConfigured):
            parse_subset_entry(("tests.test_mixins.OkPlugin", "not a dict"))

    def test_rejects_other_types(self):
        with self.assertRaises(ImproperlyConfigured):
            parse_subset_entry(123)


class TestResolveBackend(SimpleTestCase):
    def test_resolves_a_valid_dotted_path(self):
        self.assertIs(
            resolve_backend("tests.test_mixins.OkPlugin"),
            OkPlugin,
        )

    def test_raises_improperly_configured_for_unknown_module(self):
        with self.assertRaises(ImproperlyConfigured) as ctx:
            resolve_backend("tests.does_not_exist.MissingBackend")
        self.assertIn("cannot import backend", str(ctx.exception))

    def test_raises_improperly_configured_for_non_backend(self):
        with self.assertRaises(ImproperlyConfigured) as ctx:
            resolve_backend("tests.test_mixins._SUBSET_BOTH")
        self.assertIn("not a subclass of BaseHealthCheckBackend", str(ctx.exception))


class TestCheckMixin(SimpleTestCase):
    def test_filter_plugins_requires_a_subset(self):
        with self.assertRaises(Http404):
            Checker().filter_plugins(subset=None)

    def test_filter_plugins_for_unknown_subset(self):
        with override_settings(HEALTH_CHECK={"SUBSETS": {"only-known": []}}):
            with self.assertRaises(Http404):
                Checker().filter_plugins(subset="ghost")

    def test_filter_plugins_returns_one_instance_per_dotted_path(self):
        with override_settings(HEALTH_CHECK={"SUBSETS": _SUBSET_BOTH}):
            plugins = Checker().filter_plugins(subset="all")
        self.assertEqual(len(plugins), 2)
        self.assertCountEqual(plugins.keys(), ["FailPlugin", "OkPlugin"])

    def test_filter_plugins_passes_kwargs_from_tuple_entry(self):
        with override_settings(
            HEALTH_CHECK={
                "SUBSETS": {
                    "params": [
                        ("tests.test_mixins.ParameterizedPlugin", {"alias": "primary"}),
                        ("tests.test_mixins.ParameterizedPlugin", {"alias": "replica"}),
                    ]
                }
            }
        ):
            plugins = Checker().filter_plugins(subset="params")
        self.assertCountEqual(
            plugins.keys(),
            ["ParameterizedPlugin: primary", "ParameterizedPlugin: replica"],
        )
        self.assertEqual(plugins["ParameterizedPlugin: primary"].alias, "primary")
        self.assertEqual(plugins["ParameterizedPlugin: replica"].alias, "replica")

    def test_filter_plugins_deepcopies_kwargs_so_per_request_mutation_does_not_leak(self):
        # `alias` is a list to give us a *mutable* kwarg whose identity we can compare.
        kwargs_payload = {"alias": ["primary"]}
        with override_settings(
            HEALTH_CHECK={
                "SUBSETS": {
                    "params": [("tests.test_mixins.ParameterizedPlugin", kwargs_payload)],
                }
            }
        ):
            plugins = Checker().filter_plugins(subset="params")
            instance = next(iter(plugins.values()))
            # The instance must have received a copy, not the live settings list.
            self.assertEqual(instance.alias, ["primary"])
            self.assertIsNot(instance.alias, kwargs_payload["alias"])
            # Mutating what the backend received must not change the settings payload.
            instance.alias.append("mutated")
        self.assertEqual(kwargs_payload, {"alias": ["primary"]})

    def test_run_check_collects_errors(self):
        for disable_threading in [True, False]:
            with self.subTest(disable_threading=disable_threading):
                with override_settings(
                    HEALTH_CHECK={
                        "SUBSETS": _SUBSET_BOTH,
                        "DISABLE_THREADING": disable_threading,
                    }
                ):
                    self.assertEqual(len(Checker().run_check(subset="all")), 1)

    def test_run_check_threading_enabled(self):
        with override_settings(HEALTH_CHECK={"SUBSETS": _SUBSET_BOTH, "DISABLE_THREADING": False}):
            with patch("health_check.mixins.ThreadPoolExecutor") as tpe:
                Checker().run_check(subset="all")
                tpe.assert_called()

            with patch("django.db.connections.close_all") as close_all:
                Checker().run_check(subset="all")
                close_all.assert_called()

    def test_run_check_threading_disabled(self):
        with override_settings(HEALTH_CHECK={"SUBSETS": _SUBSET_BOTH, "DISABLE_THREADING": True}):
            with patch("health_check.mixins.ThreadPoolExecutor") as tpe:
                Checker().run_check(subset="all")
                tpe.assert_not_called()

                with patch("django.db.connections.close_all") as close_all:
                    Checker().run_check(subset="all")
                    close_all.assert_not_called()
