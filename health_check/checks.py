from django.conf import settings
from django.core.checks import Warning, register

LIVENESS_MIDDLEWARE_DOTTED = "health_check.middleware.LivenessMiddleware"


@register()
def liveness_middleware_first(app_configs, **kwargs):
    middleware = list(getattr(settings, "MIDDLEWARE", []) or [])
    if LIVENESS_MIDDLEWARE_DOTTED in middleware and middleware[0] != LIVENESS_MIDDLEWARE_DOTTED:
        return [
            Warning(
                f"{LIVENESS_MIDDLEWARE_DOTTED!r} is not the first entry in MIDDLEWARE; "
                "liveness probes will be gated on whatever runs above it.",
                hint="Move it to index 0 of MIDDLEWARE.",
                id="health_check.W001",
            )
        ]
    return []
