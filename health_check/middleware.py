from django.http import JsonResponse

from health_check.conf import get_setting


class LivenessMiddleware:
    """
    Short-circuit a liveness probe with HTTP 200 before any other middleware or integration runs.

    Place at the top of ``MIDDLEWARE`` so it runs first; otherwise the probe is
    gated on whatever sits above it, which defeats the purpose of liveness.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = get_setting("LIVENESS_PATH").rstrip("/")
        if request.path.rstrip("/") == path:
            return JsonResponse({"status": "ok"})
        return self.get_response(request)
