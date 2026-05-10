from django.conf import settings

_DEFAULTS = {
    "DISK_USAGE_MAX": 90,
    "MEMORY_MIN": 100,
    "WARNINGS_AS_ERRORS": True,
    "SUBSETS": {},
    "DISABLE_THREADING": False,
    "LIVENESS_PATH": "/healthcheck/liveness",
}


def get_setting(name, default_value=None):
    user_settings = getattr(settings, "HEALTH_CHECK", {})
    if name in user_settings:
        return user_settings[name]
    if name in _DEFAULTS:
        return _DEFAULTS[name]
    return default_value
