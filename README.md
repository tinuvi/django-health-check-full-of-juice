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

1. Add `health_check` to `INSTALLED_APPS`. **No contrib app needs to be installed** — backends are referenced by dotted import path in `HEALTH_CHECK["SUBSETS"]` and resolved on demand.

   ```python
   INSTALLED_APPS = [
       # ...
       "health_check",
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

3. Declare at least one named subset under `HEALTH_CHECK["SUBSETS"]`. Each entry is the dotted import path to a `BaseHealthCheckBackend` subclass:

   ```python
   # settings.py
   HEALTH_CHECK = {
       "SUBSETS": {
           "readiness": [
               "health_check.contrib.db_heartbeat.backends.DatabaseHeartbeatCheck",
               "health_check.contrib.migrations.backends.MigrationsHealthCheck",
           ],
       },
   }
   ```

4. Hit `GET /ht/<subset-name>/` from your load balancer / Kubernetes probe / monitoring tool. Returns `200 OK` if every backend reports healthy, `500` otherwise. Pass `?format=json` for a JSON response.

There is no "run every backend" endpoint — every probe targets an explicit subset, so the response is always reproducible.

## Running checks from the CLI

A management command is also available — useful in deploy pipelines and one-off diagnostics. `--subset` is required:

```bash
python manage.py health_check --subset readiness
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
        # Crucial services the app literally cannot serve traffic without.
        "readiness": [
            "health_check.contrib.migrations.backends.MigrationsHealthCheck",
            "health_check.contrib.db_heartbeat.backends.DatabaseHeartbeatCheck",
        ],
        # Everything readiness has, plus every other integration the app talks to.
        "integrations": [
            "health_check.contrib.migrations.backends.MigrationsHealthCheck",
            "health_check.contrib.db_heartbeat.backends.DatabaseHeartbeatCheck",
            "health_check.cache.backends.CacheBackend",
            "health_check.storage.backends.DefaultFileStorageHealthCheck",
            "health_check.contrib.redis.backends.RedisHealthCheck",
            "health_check.contrib.celery_ping.backends.CeleryPingHealthCheck",
            "health_check.contrib.rabbitmq.backends.RabbitMQHealthCheck",
        ],
    },
}
```

Keep `readiness` to backends the app literally cannot function without — failing it pulls every pod out of the load balancer at once, so a non-critical hiccup (e.g. Redis) shouldn't be in there or you've turned a degraded-performance event into a full outage. `CacheBackend` lives in `integrations` only, on the assumption that sessions are stored in the database (Django's default, `django.contrib.sessions.backends.db`). If your project sets `SESSION_ENGINE = "django.contrib.sessions.backends.cache"` (or `cached_db`), users can't authenticate without the cache — move `CacheBackend` back into `readiness` for that project.

If your project uses Django-Q instead of (or alongside) Celery, swap in or add `health_check.contrib.django_q.backends.DjangoQClusterHealthCheck` to `integrations`. It reads the heartbeat the Django-Q sentinel publishes to its broker on every cycle, so the web tier can fail synthetic monitoring when the worker fleet stops broadcasting.

That gives you:

- `GET /healthcheck/liveness` — orchestrator liveness probe (handled by middleware).
- `GET /healthcheck/readiness` — orchestrator readiness probe (subset).
- `GET /healthcheck/integrations` — full dependency check, e.g. for synthetic monitoring.

`python manage.py check` validates every dotted path in `HEALTH_CHECK["SUBSETS"]` at boot — typos and non-`BaseHealthCheckBackend` references surface as `health_check.E002`/`E003`/`E004` errors so CI catches them before deploy.

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

- `health_check.contrib.django_q.backends.DjangoQLocalHealthCheck` — passes only if a stat keyed to the current host is fresh. Use this for the worker pod's `livenessProbe`.
- `health_check.contrib.django_q.backends.DjangoQClusterHealthCheck` — passes if any stat for the configured cluster name is fresh. Use this in the web tier's `integrations` subset.

```python
HEALTH_CHECK = {
    "SUBSETS": {
        "liveness": ["health_check.contrib.django_q.backends.DjangoQLocalHealthCheck"],
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
        "liveness": ["health_check.contrib.celery_heartbeat.backends.CeleryHeartbeatHealthCheck"],
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
    "SUBSETS": {},                # named subsets — see below; required to expose any probe
    "DISABLE_THREADING": False,   # if True, run backends sequentially in the request thread
}
```

Settings are read lazily at check time via `health_check.conf.get_setting`, so `django.test.override_settings` (and any runtime mutation of `settings.HEALTH_CHECK`) is honored.

### Subsets

Group backends so probes can target a specific slice of your stack. Each entry is one of:

- A dotted import path string — `"my.module.MyHealthCheck"` — instantiated with no arguments.
- A `(path, kwargs)` 2-element tuple/list — `("my.module.MyHealthCheck", {"alias": "replica"})` — instantiated as `MyHealthCheck(**kwargs)`. Use this to spin up multiple instances of the same backend with different configuration (e.g. one `CacheBackend` per cache alias). The `kwargs` dict is deep-copied per request so a backend that mutates its own state can't leak into later probes.

Hit a subset via `/<your-mount-point>/<subset-name>/` or `python manage.py health_check --subset <subset-name>`.

```python
HEALTH_CHECK = {
    "SUBSETS": {
        "startup": [
            "health_check.contrib.migrations.backends.MigrationsHealthCheck",
            "health_check.contrib.db_heartbeat.backends.DatabaseHeartbeatCheck",
        ],
        "integrations": [
            "health_check.cache.backends.CacheBackend",  # default cache
            ("health_check.cache.backends.CacheBackend", {"backend": "cockatiel"}),  # named cache
        ],
    },
}
```

If you list the same backend class more than once with different kwargs, override `identifier()` so each instance returns a distinct string — the response dict is keyed by identifier, and same-keyed entries silently overwrite each other. The built-in `CacheBackend.identifier()` already returns `f"Cache backend: {self.backend}"`, so the example above is safe out of the box.

See [Recommended setup](#recommended-setup) for the readiness/integrations layout we use in production.

## Writing a custom backend

Subclass `BaseHealthCheckBackend`, implement `check_status`, and reference it by dotted path in `HEALTH_CHECK["SUBSETS"]`:

```python
# myapp/backends.py
from health_check.backends import BaseHealthCheckBackend
from health_check.exceptions import ServiceUnavailable


class MyServiceHealthCheck(BaseHealthCheckBackend):
    critical_service = True  # if False, failures don't fail the overall check

    def check_status(self):
        if not my_service.is_reachable():
            raise ServiceUnavailable("my-service is unreachable")
```

```python
# settings.py
HEALTH_CHECK = {
    "SUBSETS": {
        "integrations": [
            # ...
            "myapp.backends.MyServiceHealthCheck",
        ],
    },
}
```

No `AppConfig.ready()` hook is needed — the backend is loaded on demand the first time the subset is hit, and `python manage.py check` validates the path at boot time.
