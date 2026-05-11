# Changelog
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-05-11

### Added
- Django system checks `health_check.E002`/`E004`/`E005` (alongside the existing `W001`): validate every entry in `HEALTH_CHECK["SUBSETS"]` at `manage.py check` time. `E002` fires when a subset value isn't a list/tuple; `E004` when a dotted path can't be imported or doesn't resolve to a `BaseHealthCheckBackend` subclass; `E005` when an entry is malformed (not a string, not a 2-element `(path, kwargs)` sequence, wrong arity, non-string path, or non-dict kwargs).
- `health_check.mixins.resolve_backend(dotted_path)` and `health_check.mixins.parse_subset_entry(entry)`: helpers used by both `CheckMixin.filter_plugins` and the system check. `resolve_backend` raises `ImproperlyConfigured` on missing modules, missing attributes, or non-subclass references; `parse_subset_entry` normalizes a string or `(path, kwargs)` entry into `(path, kwargs)`.
- **Parameterized backends in `SUBSETS`**: each entry can now be either a dotted path string (zero-arg construction) or a `(path, kwargs)` 2-element tuple/list — e.g. `("health_check.cache.backends.CacheBackend", {"backend": "cockatiel"})`. The kwargs dict is deep-copied per request so per-instance mutation can't leak across probes. Lists are accepted in addition to tuples so settings deserialized from YAML/JSON work without conversion.

### Changed
- **Backends are now referenced by dotted import path in `HEALTH_CHECK["SUBSETS"]`** instead of by bare class name resolved against an in-memory plugin registry. Each subset entry is either the full dotted path (e.g. `"health_check.contrib.db_heartbeat.backends.DatabaseHeartbeatCheck"`) or a `(path, kwargs)` tuple/list. Update every `SUBSETS` entry accordingly. `health_check` itself is the only app that needs to remain in `INSTALLED_APPS`; every contrib app entry can be removed.
- `python manage.py health_check` now requires `--subset`; the no-argument "run every backend" mode has been removed.
- `CheckMixin.filter_plugins(subset=None)` now raises `Http404` instead of returning every registered plugin. The mixin no longer exposes `plugins` / `_plugins` / `_errors` attributes — its only public surface is `filter_plugins(subset)`, `check(subset)`, and `run_check(subset)`.
- The `HEALTHCHECK_CELERY_TIMEOUT` deprecation warning, previously emitted from `health_check.contrib.celery`'s `AppConfig.ready()`, now fires from `CeleryHealthCheck.check_status()` when the deprecated setting is in use (since `AppConfig.ready()` no longer exists).
- Renamed `DatabaseHeartBeatCheck` → `DatabaseHeartbeatCheck` in `health_check.contrib.db_heartbeat.backends` ("Heartbeat" is one word). Update any direct imports and any `HEALTH_CHECK["SUBSETS"]` entries that reference the old class name.

### Removed
- `health_check.plugins` module and the global `plugin_dir` registry. There is no longer any in-memory list of "registered" backends; `HEALTH_CHECK["SUBSETS"]` is the single source of truth and Django's system check framework validates it at boot.
- `AppConfig.ready()` registration hooks in every contrib/built-in app: `health_check.cache`, `health_check.storage`, `health_check.contrib.celery`, `celery_heartbeat`, `celery_ping`, `db_heartbeat`, `django_q`, `migrations`, `psutil`, `rabbitmq`, `redis`, `s3boto_storage`, `s3boto3_storage`. The `apps.py` files for those packages have been deleted; nothing in `INSTALLED_APPS` needs to change for the new mechanism, but you can drop the contrib entries since they no longer do anything.
- The no-subset HTTP endpoint at `path("", MainView.as_view(), name="health_check_home")`. Every probe must target a named subset under `HEALTH_CHECK["SUBSETS"]` and use the `health_check_subset` URL (`/<mount>/<subset>/`).
- The dynamic per-queue registration in `health_check.contrib.celery` (one `CeleryHealthCheck<Queue>` class per AMQP queue at boot). To check multiple queues, subclass `CeleryHealthCheck` once per queue (`class CeleryDefault(CeleryHealthCheck): queue = "default"`) and reference each subclass by dotted path.
- The conditional `DiskUsage` / `MemoryUsage` registration in `health_check.contrib.psutil` (skip-if-`None` semantic). Inclusion is now explicit: list the dotted path in a subset to enable it, omit it to disable.
- `health_check.db` app and its `DatabaseBackend` write-path check (the INSERT/UPDATE/DELETE probe against an internal `TestModel`). Use `DatabaseHeartbeatCheck` from `health_check.contrib.db_heartbeat` instead — it issues a `SELECT 1` (or `SELECT 1 FROM DUAL` on Oracle), requires no table, and works under conservative database-user permissions. To upgrade safely: while still on a prior version, run `python manage.py migrate db zero` to drop the `health_check_db_testmodel` table; then upgrade and remove `"health_check.db"` from `INSTALLED_APPS`.

## [0.1.0] - 2026-05-10

### Added
- Initial release as `django-health-check-full-of-juice`, an opinionated fork of [`django-health-check`](https://github.com/codingjoe/django-health-check) 3.20.8.
- `health_check.conf.get_setting(name, default_value=None)` helper that reads `settings.HEALTH_CHECK` lazily — values changed via `django.test.override_settings` (or any runtime mutation) are honored on each check. Resolution order: `settings.HEALTH_CHECK[name]` → `_DEFAULTS[name]` → `default_value`. Contrib backends own their own defaults and pass them at the call site (`get_setting("MY_KEY", default)`); `_DEFAULTS` carries core keys only.
- `health_check.middleware.LivenessMiddleware`: short-circuits a configurable liveness probe path with `200 {"status": "ok"}` before any other middleware or integration runs. Configured via the new `HEALTH_CHECK["LIVENESS_PATH"]` setting (default: `/healthcheck/liveness`). Sync only.
- Django system check `health_check.W001`: warns at `manage.py check` time if `LivenessMiddleware` is in `MIDDLEWARE` but not at index 0.
- `health_check.contrib.django_q` app with two backends that read the `Stat` heartbeat the Django-Q sentinel publishes to its broker: `DjangoQClusterHealthCheck` (fleet view, intended for the web tier's `integrations` subset) and `DjangoQLocalHealthCheck` (current-host view, intended for the worker pod's `liveness` subset). Configured via `HEALTH_CHECK["DJANGO_Q_CLUSTER_NAME"]` (default: `Q_CLUSTER["name"]`) and `HEALTH_CHECK["DJANGO_Q_UNHEALTHY_STATUSES"]` (default: `{"Stopping", "Stopped"}`). Adds `django-q2` as a dependency.
- `health_check.contrib.celery_heartbeat` app with `CeleryHeartbeatHealthCheck` backend and a Celery `LivenessProbe` bootstep. The bootstep touches a heartbeat file on a timer from inside the worker process; the backend asserts the file's mtime is fresh. Broker-independent, pod-local — suitable for a Celery worker `livenessProbe`. Configured via `HEALTH_CHECK["CELERY_HEARTBEAT_FILE"]` (default: `/tmp/celery_worker_heartbeat`), `HEALTH_CHECK["CELERY_HEARTBEAT_INTERVAL"]` (default: `1.0`), and `HEALTH_CHECK["CELERY_HEARTBEAT_MAX_AGE"]` (default: `60`).

### Changed
- Minimum supported Python is now 3.12; minimum supported Django is now 5.2.11.
- `health_check` management command no longer inherits from `CheckMixin`; it composes a `CheckMixin` instance internally to avoid leaking mixin attributes onto the Django `BaseCommand` API.
- Test runs now emit a JUnit XML report at `tests-reports/junit.xml` (via `unittest-xml-reporting`); SonarQube consumes it through `sonar.python.xunit.reportPath`.
- Narrowed the unknown-error catch in `celery`, `celery_ping`, `redis`, `rabbitmq`, and `django_q` backends from `BaseException` to `Exception` so worker-shutdown signals (`KeyboardInterrupt`, `SystemExit`) propagate instead of being reported as routine health-check failures.
- Restructured `BaseHealthCheckBackend.add_error` and `health_check.contrib.psutil.apps.HealthCheckConfig.ready` to drop empty `if` branches in favor of inverted conditions (no behavior change).
- Replaced the `with open(path, "ab"): pass` + `os.utime(path, None)` idiom in `health_check.contrib.celery_heartbeat.bootsteps.LivenessProbe` with `pathlib.Path(path).touch()`.
- Replaced `not X == Y` comparisons with `X != Y` in the cache and storage health-check backends.
- Renamed module-level `logger` to `_logger` across `health_check/` and made class-level `logger` attributes private on the S3 storage health checks. Standardized the logger name on `django_health_check_full_of_juice` in the migrations, S3, and RabbitMQ backends.
- Rendered health-check index page now starts with `<!DOCTYPE html>` and the root `<html>` tag carries `lang="en"`.

### Fixed
- `health_check.contrib.psutil.apps.HealthCheckConfig.ready` checked `"DISK_USAGE_MAX" in settings.HEALTH_CHECK` while guarding the `MemoryUsage` plugin, so a `HEALTH_CHECK = {"MEMORY_MIN": None}` setting was ignored (the plugin was registered anyway) and a `HEALTH_CHECK = {"DISK_USAGE_MAX": 90}` setting raised `KeyError: 'MEMORY_MIN'` at app boot. The membership check now correctly looks up `"MEMORY_MIN"`.

### Removed
- `health_check.contrib.mail` backend (`MailHealthCheck`) and its app config.
- Module-level `health_check.conf.HEALTH_CHECK` dict — use `health_check.conf.get_setting()` instead.
- `health_check.__version__` and `health_check.VERSION` attributes; the package version is now set exclusively by the publish workflow from the git tag.
