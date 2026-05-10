---
paths: "health_check/conf.py"
---

# conf.py rules

`conf.py` is pure-core: it knows about core settings only — those consumed by `health_check/` modules outside `contrib/`.

- Keep `_DEFAULTS` limited to core keys.
- Do **not** add contrib-specific keys to `_DEFAULTS`, including `None` placeholders that delegate resolution back to a contrib.
- Preserve the `get_setting(name, default_value=None)` signature.
- Resolution order: `settings.HEALTH_CHECK[name]` → `_DEFAULTS[name]` → `default_value`. Don't reorder.
- Contrib backends own their defaults — pass them at the call site: `get_setting("MY_CONTRIB_KEY", default)`.
