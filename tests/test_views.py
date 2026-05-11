import json
from unittest import TestCase
from unittest.mock import Mock, patch

from django.db import DatabaseError
from django.test import SimpleTestCase, TransactionTestCase, override_settings
from django.urls import reverse

from health_check.backends import BaseHealthCheckBackend
from health_check.exceptions import ServiceWarning
from health_check.views import MediaType


class _AlwaysOk(BaseHealthCheckBackend):
    def run_check(self):
        pass


class _AlwaysFail(BaseHealthCheckBackend):
    def check_status(self):
        self.add_error("Super Fail!")


class _AlwaysWarn(BaseHealthCheckBackend):
    def check_status(self):
        raise ServiceWarning("so so")


class _NonCriticalFail(BaseHealthCheckBackend):
    critical_service = False

    def check_status(self):
        self.add_error("Super Fail!")


class _JsonOk(BaseHealthCheckBackend):
    def run_check(self):
        pass


class _JsonError(BaseHealthCheckBackend):
    def run_check(self):
        self.add_error("JSON Error")


class _SuccessOne(BaseHealthCheckBackend):
    def run_check(self):
        pass


class _SuccessTwo(BaseHealthCheckBackend):
    def run_check(self):
        pass


def _subset(*paths):
    return {"HEALTH_CHECK": {"SUBSETS": {"probe": list(paths)}}}


_PROBE_URL = reverse("health_check:health_check_subset", kwargs={"subset": "probe"})


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
    @override_settings(**_subset("tests.test_views._AlwaysOk"))
    def test_success(self):
        response = self.client.get(_PROBE_URL)
        self.assertEqual(response.status_code, 200, msg=response.content.decode("utf-8"))
        self.assertEqual(response["content-type"], "text/html; charset=utf-8")

    @override_settings(**_subset("tests.test_views._AlwaysOk"))
    def test_html_has_doctype_and_lang(self):
        response = self.client.get(_PROBE_URL)
        body = response.content.decode("utf-8")
        self.assertTrue(
            body.lstrip().startswith("<!DOCTYPE html>"),
            msg="response body should start with an HTML5 doctype declaration",
        )
        self.assertIn('<html lang="en">', body)

    @override_settings(**_subset("tests.test_views._AlwaysFail"))
    def test_error(self):
        response = self.client.get(_PROBE_URL)
        self.assertContains(response, "Super Fail!", status_code=500)
        self.assertEqual(response["content-type"], "text/html; charset=utf-8")

    def test_warning(self):
        with override_settings(**_subset("tests.test_views._AlwaysWarn")):
            response = self.client.get(_PROBE_URL)
            self.assertContains(response, "so so", status_code=500)

        with override_settings(
            HEALTH_CHECK={
                "SUBSETS": {"probe": ["tests.test_views._AlwaysWarn"]},
                "WARNINGS_AS_ERRORS": False,
            }
        ):
            response = self.client.get(_PROBE_URL)
            self.assertContains(response, "so so", status_code=200)
            self.assertEqual(response["content-type"], "text/html; charset=utf-8")

    @override_settings(**_subset("tests.test_views._NonCriticalFail"))
    def test_non_critical(self):
        response = self.client.get(_PROBE_URL)
        self.assertContains(response, "Super Fail!", status_code=200)
        self.assertEqual(response["content-type"], "text/html; charset=utf-8")

    @override_settings(**_subset("tests.test_views._JsonOk"))
    def test_success_accept_json(self):
        response = self.client.get(_PROBE_URL, HTTP_ACCEPT="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["content-type"], "application/json")

    @override_settings(**_subset("tests.test_views._JsonOk"))
    def test_success_prefer_json(self):
        response = self.client.get(_PROBE_URL, HTTP_ACCEPT="application/json; q=0.8, text/html; q=0.5")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["content-type"], "application/json")

    @override_settings(**_subset("tests.test_views._AlwaysOk"))
    def test_success_accept_xhtml(self):
        response = self.client.get(_PROBE_URL, HTTP_ACCEPT="application/xhtml+xml")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["content-type"], "text/html; charset=utf-8")

    @override_settings(**_subset("tests.test_views._AlwaysOk"))
    def test_success_unsupported_accept(self):
        response = self.client.get(_PROBE_URL, HTTP_ACCEPT="application/octet-stream")
        self.assertEqual(response.status_code, 406)
        self.assertEqual(response["content-type"], "text/plain")
        self.assertEqual(
            response.content,
            b"Not Acceptable: Supported content types: text/html, application/json",
        )

    @override_settings(**_subset("tests.test_views._AlwaysOk"))
    def test_success_unsupported_and_supported_accept(self):
        response = self.client.get(_PROBE_URL, HTTP_ACCEPT="application/octet-stream, application/json; q=0.9")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["content-type"], "application/json")

    @override_settings(**_subset("tests.test_views._JsonOk"))
    def test_success_accept_order(self):
        response = self.client.get(
            _PROBE_URL,
            HTTP_ACCEPT="text/html, application/xhtml+xml, application/json; q=0.9, */*; q=0.1",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["content-type"], "text/html; charset=utf-8")

    @override_settings(**_subset("tests.test_views._JsonOk"))
    def test_success_accept_order__reverse(self):
        response = self.client.get(
            _PROBE_URL,
            HTTP_ACCEPT="text/html; q=0.1, application/xhtml+xml; q=0.1, application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["content-type"], "application/json")

    @override_settings(**_subset("tests.test_views._JsonOk"))
    def test_format_override(self):
        response = self.client.get(_PROBE_URL + "?format=json", HTTP_ACCEPT="text/html")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["content-type"], "application/json")

    @override_settings(**_subset("tests.test_views._JsonOk"))
    def test_format_no_accept_header(self):
        response = self.client.get(_PROBE_URL)
        self.assertEqual(response.status_code, 200, msg=response.content.decode("utf-8"))
        self.assertEqual(response["content-type"], "text/html; charset=utf-8")

    @override_settings(**_subset("tests.test_views._JsonError"))
    def test_error_accept_json(self):
        response = self.client.get(_PROBE_URL, HTTP_ACCEPT="application/json")
        self.assertEqual(response.status_code, 500, msg=response.content.decode("utf-8"))
        self.assertEqual(response["content-type"], "application/json")
        self.assertIn("JSON Error", json.loads(response.content.decode("utf-8"))[_JsonError().identifier()])

    @override_settings(**_subset("tests.test_views._JsonOk"))
    def test_success_param_json(self):
        response = self.client.get(_PROBE_URL, {"format": "json"})
        self.assertEqual(response.status_code, 200, msg=response.content.decode("utf-8"))
        self.assertEqual(response["content-type"], "application/json")
        self.assertJSONEqual(
            response.content.decode("utf-8"),
            {_JsonOk().identifier(): _JsonOk().pretty_status()},
        )

    def test_success_subset_define(self):
        with override_settings(
            HEALTH_CHECK={
                "SUBSETS": {
                    "startup-probe": [
                        "tests.test_views._SuccessOne",
                        "tests.test_views._SuccessTwo",
                    ],
                    "liveness-probe": ["tests.test_views._SuccessTwo"],
                }
            }
        ):
            startup_url = reverse("health_check:health_check_subset", kwargs={"subset": "startup-probe"})
            response_startup = self.client.get(startup_url, {"format": "json"})
            self.assertEqual(response_startup.status_code, 200, msg=response_startup.content.decode("utf-8"))
            self.assertEqual(response_startup["content-type"], "application/json")
            self.assertJSONEqual(
                response_startup.content.decode("utf-8"),
                {
                    _SuccessOne().identifier(): _SuccessOne().pretty_status(),
                    _SuccessTwo().identifier(): _SuccessTwo().pretty_status(),
                },
            )

            liveness_url = reverse("health_check:health_check_subset", kwargs={"subset": "liveness-probe"})
            response_liveness = self.client.get(liveness_url, {"format": "json"})
            self.assertEqual(response_liveness.status_code, 200, msg=response_liveness.content.decode("utf-8"))
            self.assertEqual(response_liveness["content-type"], "application/json")
            self.assertJSONEqual(
                response_liveness.content.decode("utf-8"),
                {_SuccessTwo().identifier(): _SuccessTwo().pretty_status()},
            )

    def test_error_subset_not_found(self):
        with override_settings(HEALTH_CHECK={"SUBSETS": {}}):
            url = reverse("health_check:health_check_subset", kwargs={"subset": "ghost"})
            response = self.client.get(url, {"format": "json"})
            self.assertEqual(response.status_code, 404, msg=response.content.decode("utf-8"))

    @override_settings(**_subset("tests.test_views._JsonError"))
    def test_error_param_json(self):
        response = self.client.get(_PROBE_URL, {"format": "json"})
        self.assertEqual(response.status_code, 500, msg=response.content.decode("utf-8"))
        self.assertEqual(response["content-type"], "application/json")
        self.assertIn("JSON Error", json.loads(response.content.decode("utf-8"))[_JsonError().identifier()])


class TestMainViewAtomicRequests(TransactionTestCase):
    @override_settings(
        HEALTH_CHECK={"SUBSETS": {"probe": ["health_check.contrib.db_heartbeat.backends.DatabaseHeartbeatCheck"]}}
    )
    def test_non_native_atomic_request(self):
        # See also: https://github.com/codingjoe/django-health-check/pull/469
        from django.conf import settings as dj_settings

        original = dj_settings.DATABASES["default"].get("ATOMIC_REQUESTS", False)
        dj_settings.DATABASES["default"]["ATOMIC_REQUESTS"] = True
        try:
            with patch(
                "django.db.backends.base.base.BaseDatabaseWrapper.ensure_connection",
                Mock(side_effect=DatabaseError()),
            ):
                response = self.client.get(_PROBE_URL)
                self.assertContains(response, "<title>System status</title>", status_code=500)
        finally:
            dj_settings.DATABASES["default"]["ATOMIC_REQUESTS"] = original
