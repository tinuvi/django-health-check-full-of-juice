from django.conf import settings
from django.core.checks import Error, Warning, register

from health_check.conf import get_setting

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


@register()
def subsets_resolve(app_configs, **kwargs):
    """Verify every entry in HEALTH_CHECK['SUBSETS'] resolves to a BaseHealthCheckBackend subclass."""
    from health_check.mixins import parse_subset_entry, resolve_backend

    subsets = get_setting("SUBSETS") or {}
    if not subsets:
        return []

    errors = []
    seen = {}
    for subset_name, entries in subsets.items():
        if not isinstance(entries, (list, tuple)):
            errors.append(
                Error(
                    f"HEALTH_CHECK['SUBSETS'][{subset_name!r}] must be a list of entries.",
                    hint=(
                        "Set the value to a list of dotted paths (e.g. "
                        "['my.module.MyHealthCheck']) or (path, kwargs) tuples."
                    ),
                    id="health_check.E002",
                )
            )
            continue
        for entry in entries:
            try:
                path, _kwargs = parse_subset_entry(entry)
            except Exception as exc:  # noqa: BLE001 - report any shape failure as an Error.
                errors.append(
                    Error(
                        f"HEALTH_CHECK['SUBSETS'][{subset_name!r}] entry {entry!r} is malformed: {exc}",
                        hint=(
                            "Each entry must be a dotted-path string, or a (path, kwargs) "
                            "tuple/list whose first element is a string and second is a dict."
                        ),
                        id="health_check.E005",
                    )
                )
                continue

            cached = seen.get(path)
            if cached is not None:
                if isinstance(cached, Exception):
                    errors.append(_subset_resolution_error(subset_name, path, cached))
                continue
            try:
                resolve_backend(path)
            except Exception as exc:  # noqa: BLE001 - we surface any resolution failure as an Error.
                seen[path] = exc
                errors.append(_subset_resolution_error(subset_name, path, exc))
            else:
                seen[path] = True
    return errors


def _subset_resolution_error(subset_name, path, exc):
    return Error(
        f"HEALTH_CHECK['SUBSETS'][{subset_name!r}] entry {path!r} could not be resolved: {exc}",
        hint="Confirm the dotted path is importable and points at a BaseHealthCheckBackend subclass.",
        id="health_check.E004",
    )
