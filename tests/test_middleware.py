from unittest.mock import Mock

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase

from health_check.middleware import LivenessMiddleware


class TestLivenessMiddleware(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.sentinel = HttpResponse("downstream")
        self.get_response = Mock(return_value=self.sentinel)
        self.middleware = LivenessMiddleware(self.get_response)

    def test_returns_ok_for_default_liveness_path(self):
        request = self.factory.get("/healthcheck/liveness")
        response = self.middleware(request)
        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(response.content, {"status": "ok"})
        self.get_response.assert_not_called()

    def test_returns_ok_for_default_liveness_path_with_trailing_slash(self):
        request = self.factory.get("/healthcheck/liveness/")
        response = self.middleware(request)
        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(response.content, {"status": "ok"})
        self.get_response.assert_not_called()

    def test_falls_through_for_other_paths(self):
        request = self.factory.get("/some/other/path")
        response = self.middleware(request)
        self.assertIs(response, self.sentinel)
        self.get_response.assert_called_once_with(request)

    def test_does_not_match_paths_that_only_share_a_prefix(self):
        request = self.factory.get("/healthcheck/liveness/extra")
        response = self.middleware(request)
        self.assertIs(response, self.sentinel)
        self.get_response.assert_called_once_with(request)

    def test_honors_liveness_path_override(self):
        with self.settings(HEALTH_CHECK={"LIVENESS_PATH": "/probe/alive"}):
            request = self.factory.get("/probe/alive")
            response = self.middleware(request)
            self.assertEqual(response.status_code, 200)
            self.assertJSONEqual(response.content, {"status": "ok"})

            default_request = self.factory.get("/healthcheck/liveness")
            fallthrough = self.middleware(default_request)
            self.assertIs(fallthrough, self.sentinel)
