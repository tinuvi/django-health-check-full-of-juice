import copy
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

from django.core.exceptions import ImproperlyConfigured
from django.db import connections
from django.http import Http404
from django.utils.module_loading import import_string

from health_check.backends import BaseHealthCheckBackend
from health_check.conf import get_setting
from health_check.exceptions import ServiceWarning


def resolve_backend(dotted_path):
    """Import and validate a dotted path pointing at a ``BaseHealthCheckBackend`` subclass."""
    try:
        cls = import_string(dotted_path)
    except (ImportError, ModuleNotFoundError) as exc:
        raise ImproperlyConfigured(f"HEALTH_CHECK SUBSETS: cannot import backend {dotted_path!r}: {exc}") from exc
    if not isinstance(cls, type) or not issubclass(cls, BaseHealthCheckBackend):
        raise ImproperlyConfigured(f"HEALTH_CHECK SUBSETS: {dotted_path!r} is not a subclass of BaseHealthCheckBackend")
    return cls


def parse_subset_entry(entry):
    """
    Normalize one ``HEALTH_CHECK["SUBSETS"][name]`` entry to ``(dotted_path, kwargs)``.

    Accepted shapes:
      - ``"my.module.Backend"`` (zero-arg construction)
      - ``("my.module.Backend", {"alias": "replica"})`` or its list equivalent
        (``Backend(**kwargs)`` construction)

    Raises ``ImproperlyConfigured`` on any other shape.
    """
    if isinstance(entry, str):
        return entry, {}
    if isinstance(entry, (tuple, list)):
        if len(entry) != 2:
            raise ImproperlyConfigured(
                f"HEALTH_CHECK SUBSETS entry {entry!r} must be a 2-element (path, kwargs) sequence."
            )
        path, kwargs = entry
        if not isinstance(path, str):
            raise ImproperlyConfigured(
                f"HEALTH_CHECK SUBSETS entry {entry!r}: first element must be a dotted-path string."
            )
        if not isinstance(kwargs, dict):
            raise ImproperlyConfigured(
                f"HEALTH_CHECK SUBSETS entry {entry!r}: second element must be a dict of keyword arguments."
            )
        return path, kwargs
    raise ImproperlyConfigured(
        f"HEALTH_CHECK SUBSETS entry {entry!r}: must be a dotted-path string or a (path, kwargs) sequence."
    )


class CheckMixin:
    # Instance-level cache so a single request that resolves the subset twice
    # (run_check + get_context_data, or run_check + JSON render) sees the same
    # plugin instances and therefore the same accumulated errors.
    _plugin_cache = None

    def filter_plugins(self, subset=None):
        if subset is None:
            raise Http404("A subset name is required. The no-subset endpoint has been removed.")

        if self._plugin_cache is None:
            self._plugin_cache = {}
        cached = self._plugin_cache.get(subset)
        if cached is not None:
            return cached

        subsets = get_setting("SUBSETS") or {}
        if subset not in subsets:
            raise Http404(f"Subset: '{subset}' does not exist.")

        instances = []
        for entry in subsets[subset]:
            path, kwargs = parse_subset_entry(entry)
            instances.append(resolve_backend(path)(**copy.deepcopy(kwargs)))
        instances.sort(key=lambda plugin: plugin.identifier())
        resolved = OrderedDict((plugin.identifier(), plugin) for plugin in instances)
        self._plugin_cache[subset] = resolved
        return resolved

    def check(self, subset=None):
        return self.run_check(subset=subset)

    def run_check(self, subset=None):
        errors = []

        def _run(plugin):
            plugin.run_check()
            try:
                return plugin
            finally:
                if not get_setting("DISABLE_THREADING"):
                    # DB connections are thread-local so we need to close them here
                    connections.close_all()

        def _collect_errors(plugin):
            if plugin.critical_service:
                if not get_setting("WARNINGS_AS_ERRORS"):
                    errors.extend(e for e in plugin.errors if not isinstance(e, ServiceWarning))
                else:
                    errors.extend(plugin.errors)

        plugins = self.filter_plugins(subset=subset)
        plugin_instances = plugins.values()

        if get_setting("DISABLE_THREADING"):
            for plugin in plugin_instances:
                _run(plugin)
                _collect_errors(plugin)
        else:
            with ThreadPoolExecutor(max_workers=len(plugin_instances) or 1) as executor:
                for plugin in executor.map(_run, plugin_instances):
                    _collect_errors(plugin)
        return errors
