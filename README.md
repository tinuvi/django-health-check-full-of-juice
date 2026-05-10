# Check the health of your Django app

[![Quality Gate Status](https://sonarcloud.io/api/project_badges/measure?project=tinuvi_django-health-check-full-of-juice&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=tinuvi_django-health-check-full-of-juice)
[![Coverage](https://sonarcloud.io/api/project_badges/measure?project=tinuvi_django-health-check-full-of-juice&metric=coverage)](https://sonarcloud.io/summary/new_code?id=tinuvi_django-health-check-full-of-juice)

This project is an opinionated library focused on Tinuvi's needs. It has been evolved from version 3.20.8 of the [original library](https://github.com/codingjoe/django-health-check).

## Installation

Install the package from PyPI:

```bash
pip install django-health-check-full-of-juice
```

Or, with Poetry:

```bash
poetry add django-health-check-full-of-juice
```

Requires Python ≥ 3.12 and Django ≥ 5.2.11.

## Quick start

1. Add `health_check` (and any built-in backends you want to use) to `INSTALLED_APPS`:

   ```python
   INSTALLED_APPS = [
       # ...
       "health_check",
       "health_check.cache",
       "health_check.db",
       "health_check.storage",
       "health_check.contrib.celery",
       "health_check.contrib.celery_heartbeat",
       "health_check.contrib.celery_ping",
       "health_check.contrib.db_heartbeat",
       "health_check.contrib.django_q",
       "health_check.contrib.migrations",
       "health_check.contrib.psutil",
       "health_check.contrib.rabbitmq",
       "health_check.contrib.redis",
       "health_check.contrib.s3boto3_storage",
   ]
   ```

2. Wire up the URLs (typically under an unauthenticated path so probes can reach it):

   ```python
   # urls.py
   from django.urls import include, path

   urlpatterns = [
       # ...
       path("ht/", include("health_check.urls")),
   ]
   ```

3. Hit `GET /ht/` from your load balancer / Kubernetes probe / monitoring tool. The endpoint returns `200 OK` if every registered backend reports healthy and `500` otherwise. Pass `?format=json` to get a JSON response.

## Running checks from the CLI

A management command is also available — useful in deploy pipelines and one-off diagnostics:

```bash
python manage.py health_check
```

Run a named subset (see [Subsets](#subsets) below):

```bash
python manage.py health_check --subset <subset-name>
```

The command exits non-zero if any check fails.

## Recommended setup

We use a three-probe scheme in our projects. Each probe answers a different question, so each one is wired up differently.

| Route                       | Question it answers                                              | How it's served                                          |
|-----------------------------|------------------------------------------------------------------|----------------------------------------------------------|
| `/healthcheck/liveness`     | Is the Python process alive and the request loop responsive?    | `LivenessMiddleware` short-circuits before app code runs |
| `/healthcheck/readiness`    | Are the *crucial* services this app needs to run reachable?     | `health_check` URL include + a `readiness` subset        |
| `/healthcheck/integrations` | Are *all* services this app depends on reachable (incl. above)? | `health_check` URL include + an `integrations` subset    |

### Liveness — bypass middleware and integrations

Liveness must not be gated on Django middleware, the auth stack, or any integration: if it is, a sick downstream dep can trigger a needless restart by your orchestrator. Use `LivenessMiddleware` and put it at the **very top** of `MIDDLEWARE`:

```python
MIDDLEWARE = [
    "health_check.middleware.LivenessMiddleware",
    "django.middleware.security.SecurityMiddleware",
    # ... the rest of your middleware
]
```

It responds to `GET /healthcheck/liveness` (and `/healthcheck/liveness/`) with `200 {"status": "ok"}` and short-circuits before any other middleware runs. The path is configurable via `HEALTH_CHECK["LIVENESS_PATH"]` (default: `/healthcheck/liveness`).

If you forget to put it at index 0, `python manage.py check` emits warning `health_check.W001` so CI can catch the mistake. To bypass the warning on a per-command basis (e.g. when running `migrate` in a deploy step where the ordering is intentionally different), pass Django's built-in `--skip-checks` flag:

```bash
python manage.py migrate --skip-checks
```

### Readiness and integrations — two subsets

Wire the URLs and define two subsets — `readiness` for crucial services only, `integrations` for everything (readiness *plus* the rest):

```python
# urls.py
from django.urls import include, path

urlpatterns = [
    # ...
    path("healthcheck/", include("health_check.urls")),
]
```

```python
# settings.py
HEALTH_CHECK = {
    "SUBSETS": {
        # Crucial services the app needs to run.
        "readiness": [
            "MigrationsHealthCheck",
            "DatabaseBackend",
            "CacheBackend",
        ],
        # Everything readiness has, plus every other integration the app talks to.
        "integrations": [
            "MigrationsHealthCheck",
            "DatabaseBackend",
            "CacheBackend",
            "DefaultFileStorageHealthCheck",
            "RedisHealthCheck",
            "CeleryPingHealthCheck",
            "RabbitMQHealthCheck",
        ],
    },
}
```

If your project uses Django-Q instead of (or alongside) Celery, swap in or add `DjangoQClusterHealthCheck` to `integrations`. It reads the heartbeat the Django-Q sentinel publishes to its broker on every cycle, so the web tier can fail synthetic monitoring when the worker fleet stops broadcasting.

That gives you:

- `GET /healthcheck/liveness` — orchestrator liveness probe (handled by middleware).
- `GET /healthcheck/readiness` — orchestrator readiness probe (subset).
- `GET /healthcheck/integrations` — full dependency check, e.g. for synthetic monitoring.

The backend names in each subset are the registered class names of whichever `health_check.*` apps you put in `INSTALLED_APPS` — only list backends you've actually enabled.

### Kubernetes probes

For a **web application** (anything that exposes HTTP), use `httpGet` probes:

```yaml
startupProbe:
  httpGet:
    path: /healthcheck/readiness
    port: 8080
readinessProbe:
  httpGet:
    path: /healthcheck/readiness
    port: 8080
livenessProbe:
  httpGet:
    path: /healthcheck/liveness
    port: 8080
```

Liveness hits the middleware-served path so it can't be gated on the Django stack; startup and readiness both hit the `readiness` subset because "ready to receive traffic" and "ready to be considered started" answer the same question for a typical Django web app.

For a **consumer** (Celery worker, Django-Q worker, or any process that doesn't bind a port), there's no HTTP listener to probe, so use `exec` probes that run the management command. Define a third subset, `liveness`, that contains *only* a backend safe to evaluate from inside the worker pod — see the per-framework recipes below — and wire all three probes:

```yaml
startupProbe:
  exec:
    command:
      - /bin/sh
      - -c
      - python manage.py health_check -s readiness --skip-checks
readinessProbe:
  exec:
    command:
      - /bin/sh
      - -c
      - python manage.py health_check -s readiness --skip-checks
livenessProbe:
  exec:
    command:
      - /bin/sh
      - -c
      - python manage.py health_check -s liveness --skip-checks
```

`--skip-checks` is load-bearing here. Consumers reuse the same Django settings module as the web app — including `LivenessMiddleware` at the top of `MIDDLEWARE` — so without `--skip-checks`, every probe invocation runs Django's full system-check phase before the health check itself, slowing down each probe and printing the `health_check.W001` warning to stderr.

#### Django-Q workers

Django-Q's sentinel publishes a `Stat` snapshot to the broker every cycle (TTL ≈ 3 s) — so the entry vanishes within seconds when the sentinel wedges or dies. Two backends sit on top of that signal:

- `DjangoQLocalHealthCheck` — passes only if a stat keyed to the current host is fresh. Use this for the worker pod's `livenessProbe`.
- `DjangoQClusterHealthCheck` — passes if any stat for the configured cluster name is fresh. Use this in the web tier's `integrations` subset.

```python
HEALTH_CHECK = {
    "SUBSETS": {
        "liveness": ["DjangoQLocalHealthCheck"],
        # readiness / integrations as above
    },
}
```

Tradeoff: this probe touches the Django-Q broker. With the ORM broker, a database outage will fail liveness — acceptable, since the worker can't process anything without it. With the Redis broker, a Redis outage will trigger a worker-restart storm; weigh that before adopting this for Redis-backed setups.

By default the cluster name comes from `Q_CLUSTER["name"]` and the unhealthy status set is `{"Stopping", "Stopped"}`. Override with `HEALTH_CHECK["DJANGO_Q_CLUSTER_NAME"]` and `HEALTH_CHECK["DJANGO_Q_UNHEALTHY_STATUSES"]`.

#### Celery workers

Celery doesn't broadcast an equivalent native heartbeat, so `health_check.contrib.celery_heartbeat` ships a Celery worker bootstep that touches a heartbeat file on a timer; the matching backend asserts the file's mtime is fresh. Broker-independent, pod-local — exactly what a `livenessProbe` should be.

Install the bootstep in your Celery app definition:

```python
from celery import Celery
from health_check.contrib.celery_heartbeat.bootsteps import LivenessProbe

app = Celery("myproject")
app.steps["worker"].add(LivenessProbe)
```

Then point the `liveness` subset at the matching backend:

```python
HEALTH_CHECK = {
    "SUBSETS": {
        "liveness": ["CeleryHeartbeatHealthCheck"],
        # readiness / integrations as above
    },
}
```

Defaults: heartbeat file `/tmp/celery_worker_heartbeat`, refresh interval `1.0` s, max age `60` s. Override with `HEALTH_CHECK["CELERY_HEARTBEAT_FILE"]`, `HEALTH_CHECK["CELERY_HEARTBEAT_INTERVAL"]`, and `HEALTH_CHECK["CELERY_HEARTBEAT_MAX_AGE"]`. Note that `CeleryPingHealthCheck` (under `integrations`) and `CeleryHeartbeatHealthCheck` answer different questions — keep `celery_ping` where it is for synthetic monitoring; use `celery_heartbeat` only for the worker's own liveness.

## Configuration

All configuration lives under the `HEALTH_CHECK` dict in your Django settings. Every key is optional and falls back to the default shown below.

```python
HEALTH_CHECK = {
    "DISK_USAGE_MAX": 90,         # percent; emits a warning when disk usage is at/above this threshold
    "MEMORY_MIN": 100,            # MB of available RAM below which a warning is emitted
    "WARNINGS_AS_ERRORS": True,   # if False, ServiceWarning won't fail the endpoint with HTTP 500
    "SUBSETS": {},                # named subsets — see below
    "DISABLE_THREADING": False,   # if True, run backends sequentially in the request thread
}
```

Settings are read lazily at check time via `health_check.conf.get_setting`, so `django.test.override_settings` (and any runtime mutation of `settings.HEALTH_CHECK`) is honored.

### Subsets

Group backends so probes can target a specific slice of your stack. The values are the class names of the registered backends. Hit a subset via `/<your-mount-point>/<subset-name>/` or `python manage.py health_check --subset <subset-name>`.

```python
HEALTH_CHECK = {
    "SUBSETS": {
        "startup": ["MigrationsHealthCheck", "DatabaseBackend"],
    },
}
```

See [Recommended setup](#recommended-setup) for the readiness/integrations layout we use in production.

## Writing a custom backend

Subclass `BaseHealthCheckBackend`, implement `check_status`, and register it on app ready:

```python
# myapp/backends.py
from health_check.backends import BaseHealthCheckBackend
from health_check.exceptions import ServiceUnavailable


class MyServiceHealthCheck(BaseHealthCheckBackend):
    critical_service = True  # if False, failures don't fail the overall check

    def check_status(self):
        if not my_service.is_reachable():
            raise ServiceUnavailable("my-service is unreachable")

    def identifier(self):
        return self.__class__.__name__
```

```python
# myapp/apps.py
from django.apps import AppConfig
from health_check.plugins import plugin_dir


class MyAppConfig(AppConfig):
    name = "myapp"

    def ready(self):
        from .backends import MyServiceHealthCheck

        plugin_dir.register(MyServiceHealthCheck)
```

Add `myapp` to `INSTALLED_APPS` and the new backend will appear alongside the built-ins.
