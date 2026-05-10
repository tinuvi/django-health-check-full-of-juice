import json
from unittest import TestCase
from unittest.mock import Mock, patch

from django.db import DatabaseError
from django.test import SimpleTestCase, TransactionTestCase
from django.urls import reverse

from health_check.backends import BaseHealthCheckBackend
from health_check.exceptions import ServiceWarning
from health_check.plugins import plugin_dir
from health_check.views import MediaType


class TestMediaType(TestCase):
    def test_lt(self):
        self.assertFalse(MediaType("*/*") < MediaType("*/*"))
        self.assertFalse(MediaType("*/*") < MediaType("*/*", 0.9))
        self.assertLess(MediaType("*/*", 0.9), MediaType("*/*"))

    def test_str(self):
        self.assertEqual(str(MediaType("*/*")), "*/*; q=1.0")
        self.assertEqual(str(MediaType("image/*", 0.6)), "image/*; q=0.6")

    def test_repr(self):
        self.assertEqual(repr(MediaType("*/*")), "MediaType: */*; q=1.0")

    def test_eq(self):
        self.assertEqual(MediaType("*/*"), MediaType("*/*"))
        self.assertNotEqual(MediaType("*/*", 0.9), MediaType("*/*"))

    valid_strings = [
        ("*/*", MediaType("*/*")),
        ("*/*; q=0.9", MediaType("*/*", 0.9)),
        ("*/*; q=0", MediaType("*/*", 0.0)),
        ("*/*; q=0.0", MediaType("*/*", 0.0)),
        ("*/*; q=0.1", MediaType("*/*", 0.1)),
        ("*/*; q=0.12", MediaType("*/*", 0.12)),
        ("*/*; q=0.123", MediaType("*/*", 0.123)),
        ("*/*; q=1.000", MediaType("*/*", 1.0)),
        ("*/*; q=1", MediaType("*/*", 1.0)),
        ("*/*;q=0.9", MediaType("*/*", 0.9)),
        ("*/* ;q=0.9", MediaType("*/*", 0.9)),
        ("*/* ; q=0.9", MediaType("*/*", 0.9)),
        ("*/* ;   q=0.9", MediaType("*/*", 0.9)),
        ("*/*;v=b3", MediaType("*/*")),
        ("*/*; q=0.5; v=b3", MediaType("*/*", 0.5)),
    ]

    def test_from_valid_strings(self):
        for type_, expected in self.valid_strings:
            with self.subTest(type=type_):
                self.assertEqual(MediaType.from_string(type_), expected)

    invalid_strings = [
        "*/*;0.9",
        'text/html;z=""',
        "text/html; xxx",
        "text/html;  =a",
    ]

    def test_from_invalid_strings(self):
        for type_ in self.invalid_strings:
            with self.subTest(type=type_):
                with self.assertRaises(ValueError) as cm:
                    MediaType.from_string(type_)
                expected_error = f'"{type_}" is not a valid media type'
                self.assertIn(expected_error, str(cm.exception))

    def test_parse_header(self):
        self.assertEqual(
            list(MediaType.parse_header()),
            [MediaType("*/*")],
        )
        self.assertEqual(
            list(MediaType.parse_header("text/html; q=0.1, application/xhtml+xml; q=0.1 ,application/json")),
            [
                MediaType("application/json"),
                MediaType("text/html", 0.1),
                MediaType("application/xhtml+xml", 0.1),
            ],
        )


class TestMainView(SimpleTestCase):
    url = reverse("health_check:health_check_home")

    def test_success(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200, msg=response.content.decode("utf-8"))
        self.assertEqual(response["content-type"], "text/html; charset=utf-8")

    def test_html_has_doctype_and_lang(self):
        response = self.client.get(self.url)
        body = response.content.decode("utf-8")
        self.assertTrue(
            body.lstrip().startswith("<!DOCTYPE html>"),
            msg="response body should start with an HTML5 doctype declaration",
        )
        self.assertIn('<html lang="en">', body)

    def test_error(self):
        class MyBackend(BaseHealthCheckBackend):
            def check_status(self):
                self.add_error("Super Fail!")

        plugin_dir.reset()
        plugin_dir.register(MyBackend)
        response = self.client.get(self.url)
        self.assertContains(response, "Super Fail!", status_code=500)
        self.assertEqual(response["content-type"], "text/html; charset=utf-8")

    def test_warning(self):
        class MyBackend(BaseHealthCheckBackend):
            def check_status(self):
                raise ServiceWarning("so so")

        plugin_dir.reset()
        plugin_dir.register(MyBackend)
        response = self.client.get(self.url)
        self.assertContains(response, "so so", status_code=500)

        with self.settings(HEALTH_CHECK={"WARNINGS_AS_ERRORS": False}):
            response = self.client.get(self.url)
            self.assertContains(response, "so so", status_code=200)
            self.assertEqual(response["content-type"], "text/html; charset=utf-8")

    def test_non_critical(self):
        class MyBackend(BaseHealthCheckBackend):
            critical_service = False

            def check_status(self):
                self.add_error("Super Fail!")

        plugin_dir.reset()
        plugin_dir.register(MyBackend)
        response = self.client.get(self.url)
        self.assertContains(response, "Super Fail!", status_code=200)
        self.assertEqual(response["content-type"], "text/html; charset=utf-8")

    def test_success_accept_json(self):
        class JSONSuccessBackend(BaseHealthCheckBackend):
            def run_check(self):
                pass

        plugin_dir.reset()
        plugin_dir.register(JSONSuccessBackend)
        response = self.client.get(self.url, HTTP_ACCEPT="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["content-type"], "application/json")

    def test_success_prefer_json(self):
        class JSONSuccessBackend(BaseHealthCheckBackend):
            def run_check(self):
                pass

        plugin_dir.reset()
        plugin_dir.register(JSONSuccessBackend)
        response = self.client.get(self.url, HTTP_ACCEPT="application/json; q=0.8, text/html; q=0.5")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["content-type"], "application/json")

    def test_success_accept_xhtml(self):
        class SuccessBackend(BaseHealthCheckBackend):
            def run_check(self):
                pass

        plugin_dir.reset()
        plugin_dir.register(SuccessBackend)
        response = self.client.get(self.url, HTTP_ACCEPT="application/xhtml+xml")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["content-type"], "text/html; charset=utf-8")

    def test_success_unsupported_accept(self):
        class SuccessBackend(BaseHealthCheckBackend):
            def run_check(self):
                pass

        plugin_dir.reset()
        plugin_dir.register(SuccessBackend)
        response = self.client.get(self.url, HTTP_ACCEPT="application/octet-stream")
        self.assertEqual(response.status_code, 406)
        self.assertEqual(response["content-type"], "text/plain")
        self.assertEqual(
            response.content,
            b"Not Acceptable: Supported content types: text/html, application/json",
        )

    def test_success_unsupported_and_supported_accept(self):
        class SuccessBackend(BaseHealthCheckBackend):
            def run_check(self):
                pass

        plugin_dir.reset()
        plugin_dir.register(SuccessBackend)
        response = self.client.get(self.url, HTTP_ACCEPT="application/octet-stream, application/json; q=0.9")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["content-type"], "application/json")

    def test_success_accept_order(self):
        class JSONSuccessBackend(BaseHealthCheckBackend):
            def run_check(self):
                pass

        plugin_dir.reset()
        plugin_dir.register(JSONSuccessBackend)
        response = self.client.get(
            self.url,
            HTTP_ACCEPT="text/html, application/xhtml+xml, application/json; q=0.9, */*; q=0.1",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["content-type"], "text/html; charset=utf-8")

    def test_success_accept_order__reverse(self):
        class JSONSuccessBackend(BaseHealthCheckBackend):
            def run_check(self):
                pass

        plugin_dir.reset()
        plugin_dir.register(JSONSuccessBackend)
        response = self.client.get(
            self.url,
            HTTP_ACCEPT="text/html; q=0.1, application/xhtml+xml; q=0.1, application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["content-type"], "application/json")

    def test_format_override(self):
        class JSONSuccessBackend(BaseHealthCheckBackend):
            def run_check(self):
                pass

        plugin_dir.reset()
        plugin_dir.register(JSONSuccessBackend)
        response = self.client.get(self.url + "?format=json", HTTP_ACCEPT="text/html")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["content-type"], "application/json")

    def test_format_no_accept_header(self):
        class JSONSuccessBackend(BaseHealthCheckBackend):
            def run_check(self):
                pass

        plugin_dir.reset()
        plugin_dir.register(JSONSuccessBackend)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200, msg=response.content.decode("utf-8"))
        self.assertEqual(response["content-type"], "text/html; charset=utf-8")

    def test_error_accept_json(self):
        class JSONErrorBackend(BaseHealthCheckBackend):
            def run_check(self):
                self.add_error("JSON Error")

        plugin_dir.reset()
        plugin_dir.register(JSONErrorBackend)
        response = self.client.get(self.url, HTTP_ACCEPT="application/json")
        self.assertEqual(response.status_code, 500, msg=response.content.decode("utf-8"))
        self.assertEqual(response["content-type"], "application/json")
        self.assertIn("JSON Error", json.loads(response.content.decode("utf-8"))[JSONErrorBackend().identifier()])

    def test_success_param_json(self):
        class JSONSuccessBackend(BaseHealthCheckBackend):
            def run_check(self):
                pass

        plugin_dir.reset()
        plugin_dir.register(JSONSuccessBackend)
        response = self.client.get(self.url, {"format": "json"})
        self.assertEqual(response.status_code, 200, msg=response.content.decode("utf-8"))
        self.assertEqual(response["content-type"], "application/json")
        self.assertJSONEqual(
            response.content.decode("utf-8"),
            {JSONSuccessBackend().identifier(): JSONSuccessBackend().pretty_status()},
        )

    def test_success_subset_define(self):
        class SuccessOneBackend(BaseHealthCheckBackend):
            def run_check(self):
                pass

        class SuccessTwoBackend(BaseHealthCheckBackend):
            def run_check(self):
                pass

        plugin_dir.reset()
        plugin_dir.register(SuccessOneBackend)
        plugin_dir.register(SuccessTwoBackend)

        with self.settings(
            HEALTH_CHECK={
                "SUBSETS": {
                    "startup-probe": ["SuccessOneBackend", "SuccessTwoBackend"],
                    "liveness-probe": ["SuccessTwoBackend"],
                }
            }
        ):
            response_startup_probe = self.client.get(self.url + "startup-probe/", {"format": "json"})
            self.assertEqual(
                response_startup_probe.status_code,
                200,
                msg=response_startup_probe.content.decode("utf-8"),
            )
            self.assertEqual(response_startup_probe["content-type"], "application/json")
            self.assertJSONEqual(
                response_startup_probe.content.decode("utf-8"),
                {
                    SuccessOneBackend().identifier(): SuccessOneBackend().pretty_status(),
                    SuccessTwoBackend().identifier(): SuccessTwoBackend().pretty_status(),
                },
            )

            response_liveness_probe = self.client.get(self.url + "liveness-probe/", {"format": "json"})
            self.assertEqual(
                response_liveness_probe.status_code,
                200,
                msg=response_liveness_probe.content.decode("utf-8"),
            )
            self.assertEqual(response_liveness_probe["content-type"], "application/json")
            self.assertJSONEqual(
                response_liveness_probe.content.decode("utf-8"),
                {SuccessTwoBackend().identifier(): SuccessTwoBackend().pretty_status()},
            )

    def test_error_subset_not_found(self):
        plugin_dir.reset()
        response = self.client.get(self.url + "liveness-probe/", {"format": "json"})
        print(f"content: {response.content}")
        print(f"code: {response.status_code}")
        self.assertEqual(response.status_code, 404, msg=response.content.decode("utf-8"))

    def test_error_param_json(self):
        class JSONErrorBackend(BaseHealthCheckBackend):
            def run_check(self):
                self.add_error("JSON Error")

        plugin_dir.reset()
        plugin_dir.register(JSONErrorBackend)
        response = self.client.get(self.url, {"format": "json"})
        self.assertEqual(response.status_code, 500, msg=response.content.decode("utf-8"))
        self.assertEqual(response["content-type"], "application/json")
        self.assertIn("JSON Error", json.loads(response.content.decode("utf-8"))[JSONErrorBackend().identifier()])


class TestMainViewAtomicRequests(TransactionTestCase):
    url = reverse("health_check:health_check_home")

    def setUp(self):
        # Other tests in this module reset the plugin registry; restore a DB-touching
        # plugin so the mocked ensure_connection actually surfaces during the request.
        from health_check.db.backends import DatabaseBackend

        plugin_dir.reset()
        plugin_dir.register(DatabaseBackend)
        self.addCleanup(plugin_dir.reset)

    def test_non_native_atomic_request(self):
        # See also: https://github.com/codingjoe/django-health-check/pull/469
        from django.conf import settings as dj_settings

        original = dj_settings.DATABASES["default"].get("ATOMIC_REQUESTS", False)
        dj_settings.DATABASES["default"]["ATOMIC_REQUESTS"] = True
        try:
            # disable the ensure_connection
            with patch(
                "django.db.backends.base.base.BaseDatabaseWrapper.ensure_connection",
                Mock(side_effect=DatabaseError()),
            ):
                response = self.client.get(self.url)
                self.assertContains(response, "<title>System status</title>", status_code=500)
        finally:
            dj_settings.DATABASES["default"]["ATOMIC_REQUESTS"] = original
