---
description: Run mutation testing on a target file with mutmut and iteratively close test gaps
---

# Mutation Testing Workflow

Drive a mutation-testing pass on a single target file using `mutmut`. Improve the test suite by writing new assertions that kill surviving mutants, **without modifying the library source**. Everything runs inside the `integration-tests` service from `docker-compose.yml`.

mutmut drives tests through repeated `pytest.main()` calls, so the first-time setup adds a root `conftest.py` (Phase 0) and `also_copy`s it into `mutants/`. The bootstrap is guarded on `django.test.utils._TestState` so the repeated invocations stay idempotent — see https://github.com/boxed/mutmut/issues/504.

## Phase −1 — Discover the project layout

Mutation testing needs three inputs derived from the repo:

1. **Library package** — the directory holding production code. Read `pyproject.toml` `[tool.poetry] packages = [{ include = "..." }]`, or look for the top-level package directory next to `manage.py`. Call this `<source>` below (e.g. `health_check`).
2. **Test location and naming** — where `test_*.py` files live. Two common layouts: colocated (`<source>/tests/test_*.py`) or top-level (`tests/test_*.py`). Match whichever the repo uses.
3. **Django settings module** — read `manage.py` for `DJANGO_SETTINGS_MODULE` (e.g. `tests.testapp.settings`).

Confirm all three before continuing. If any is unclear, **ask the user** rather than guessing.

## Prerequisites

Before running any mutmut command, confirm two more inputs. If the user did not provide them, **ask and wait**.

1. **Target module.** The exact path of the library source file to mutate (e.g., `<source>/some_module.py`). Must have a corresponding test file under the discovered test location. Test files themselves are out of scope.
2. **Git worktree mode.** Whether to run inside a dedicated git worktree or in the current checkout:
   - **Worktree**: isolates `mutants/`, `mutants.sqlite`, the new `[tool.mutmut]` block in `pyproject.toml`, and the root `conftest.py`. Required for running several files in parallel.
   - **In-place**: runs in the current directory. Fine for a one-off, sequential session.

   When using a worktree, pass `-p <slug>` to every `docker compose` command (e.g. `-p mut-<target>`) so containers/volumes are isolated. Reuse the same slug across the session.

## Golden rules

1. **Never modify library source** during a mutation pass without explicit user permission. If a surviving mutant points to a real bug or dead code, **stop and report it** — do not silently fix.
2. **100% score is unlikely.** Logging-argument mutants and no-ops are expected survivors — the project mandates parameterized logging (`logger.info("msg %s", x)`).
3. **One target file at a time.**
4. **Tests must pass under the project's canonical runner** (`python manage.py test`), not just under pytest. The repo entrypoint `docker compose run --remove-orphans --rm integration-tests` runs the full suite.

## Phase 0 — One-time bootstrap (skip if already done)

mutmut needs a root `conftest.py` so Django is configured at pytest collection time. Create it once per checkout (or per worktree). Substitute the discovered settings module.

**Create `conftest.py` at the repo root:**

```python
from __future__ import annotations

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "<discovered.settings.module>")

import django  # noqa: E402

django.setup()

from django.test.runner import DiscoverRunner  # noqa: E402
from django.test.utils import _TestState, setup_test_environment  # noqa: E402

if not hasattr(_TestState, "saved_data"):
    setup_test_environment()
    _runner = DiscoverRunner(verbosity=0, keepdb=True)
    _runner.setup_databases()
```

Why `_TestState.saved_data` and not a module-level flag: pytest re-imports `conftest.py` between `pytest.main()` calls and wipes module globals, but Django's `_TestState` class attribute persists across reimports.

Add `mutants/` and `mutants.sqlite` to `.gitignore` if not already covered.

## Phase 1 — Configure the target

Add a `[tool.mutmut]` section to `pyproject.toml`:

```toml
[tool.mutmut]
paths_to_mutate = ["<source>"]
pytest_add_cli_args_test_selection = [
    "<discovered/test/path>/test_<target>.py",
]
also_copy = ["conftest.py"]
debug = false
```

- `paths_to_mutate` — the whole package must be copied to `mutants/` so intra-project imports still resolve. Restrict mutation via the CLI glob in Phase 2, not by narrowing this.
- `pytest_add_cli_args_test_selection` — narrows pytest collection to the one test file.
- `also_copy = ["conftest.py"]` — ships the bootstrap into `mutants/` so Django is configured against the mutated tree.
- `debug` — prints the pytest invocation. Useful for diagnosing bootstrap failures.

Only `pytest_add_cli_args_test_selection` changes between targets.

**`type_check_command` is intentionally absent.** mutmut wraps every function in a `_mutmut_trampoline` dispatcher that strict mypy rejects, which would falsely mark every mutant as 🧙 (type-caught). If you want a pre-filter, configure a relaxed mypy invocation and verify it doesn't blanket-reject before relying on it.

**Wipe prior state when switching targets:**

```bash
docker compose run --remove-orphans --rm integration-tests bash -c 'rm -rf mutants mutants.sqlite'
```

`mutants.sqlite` caches mutant IDs and exit codes from the previous run. Don't wipe between iterative re-runs on the same target — that cache is what makes already-killed mutants skip instantly.

## Phase 2 — Run mutmut

Pass the target as a dotted-path glob so mutmut only exercises mutants in that file:

```bash
docker compose run --remove-orphans --rm integration-tests \
  mutmut run "<source>.<target>*"
```

Output legend:

| Symbol | Status | Meaning |
|---|---|---|
| 🎉 | killed | A test caught the mutation |
| 🧙 | caught by type check | Type checker rejected before pytest ran (zero by default) |
| 🙁 | survived | No test caught it — **this is where we work** |
| 🫥 | no tests | No test covers the mutated code |
| ⏰ | timeout | Usually a killed mutant |
| 🤔 | suspicious | Test passed but unreliably |
| 🔇 | skipped | Explicitly ignored |

## Phase 3 — Read the report

Surviving mutant IDs:

```bash
docker compose run --remove-orphans --rm integration-tests bash -c 'mutmut results 2>&1 | grep "survived"'
```

Diff for one mutant:

```bash
docker compose run --remove-orphans --rm integration-tests \
  mutmut show '<mutant.id>'
```

**Bulk triage via `scripts/triage_mutmut_survivors.py`** — recommended when survivors >30. Buckets each survivor by mutation shape and emits HIGH / LOW / UNKNOWN tiers plus a per-function summary.

```bash
docker compose run --remove-orphans --rm integration-tests \
  python scripts/triage_mutmut_survivors.py --target <target>

# Narrow to one function/bucket:
docker compose run --remove-orphans --rm integration-tests \
  python scripts/triage_mutmut_survivors.py \
    --target <target> --function <fn> --bucket comparison_flip
```

Triage rules:
- UNKNOWN > 0: inspect manually before writing tests.
- LOW (`logger_noise`, `noop`): accept as survivors.
- HIGH: bug-check (Phase 5) then write tests (Phase 6). Attack the function with the highest HIGH count first.

## Phase 4 — Classify survivors

### High-value (always kill)
- **Arithmetic / constant changes** (e.g. `* 1000` → `/ 1000`).
- **Comparison / boolean flips** (`==` → `!=`, `and` → `or`, `<` → `<=`).
- **Argument forwarding** (`f(token)` → `f(None)`) — exposes mocks that were never asserted on.
- **Default value changes** (`.get("k", [])` → `.get("k", None)`).
- **Short-circuit / early-return changes.**

### Low-value (accept)
- **Logger argument mutations** — killing these forces brittle log-string assertions and **violates the project's parameterized-logging rule** (`.claude/rules/main-rules.md`).
- **Mutations on dead / unreachable code** — only fixable by removing the code, which requires source permission.

### Bug-candidate (STOP and report)
- Any mutation whose surviving form is "more correct" than the original or reveals a latent defect. Do not fix. Report and wait.

## Phase 5 — Bug check before writing tests

For each high-value survivor, re-read the source and ask:
- Is the original line actually correct, or does the mutation expose an asymmetry?
- Is the line reachable? Dead code → flag, don't kill.
- Does the test file already have the structure to assert on this, or do we need a new test case?

If anything smells, write up findings and pause.

## Phase 6 — Write tests

**Only modify test files.** Project rules apply:
- Use parameterized logging (`logger.info("msg %s", value)`); never f-strings in log calls.
- Follow any logger-naming rule in `.claude/rules/main-rules.md`.

Typical moves:
- **Argument forwarding** → `mock.assert_called_once_with(<expected>)`.
- **Missing-key edge case** → new test where the optional key is omitted.
- **Default value change** → new test exercising the default branch.
- **Comparison flip** → boundary tests on both sides of the comparator.

Run under the canonical runner. `--noinput` is required because the conftest's `keepdb=True` leaves the test DB on disk and Django would otherwise hang on a drop-confirmation prompt:

```bash
docker compose run --remove-orphans --rm integration-tests \
  python manage.py test --noinput <discovered.test.dotted.path>.test_<target>
```

All tests must pass before re-running mutmut.

## Phase 7 — Re-run and measure

```bash
docker compose run --remove-orphans --rm integration-tests \
  mutmut run "<source>.<target>*"
```

Iterate Phase 3 → Phase 7 until only accepted low-value survivors remain.

## Target score

Effective score = `(killed + caught_by_type_check) / total`. Without a `type_check_command`, this is `killed / total`.

| Score | Verdict |
|---|---|
| ≥ 90% | Excellent — likely over-engineered tests |
| **80%–90%** | **Target band** |
| 70%–80% | Acceptable if remaining survivors are logging-only |
| < 70% | Ship more tests |

## When to stop

Stop when all remaining survivors fall into:
1. Logger format-string / argument mutations.
2. Provably unreachable / no-op code.
3. Mutations only killable by asserting log/error messages verbatim.
4. Mutations needing integration fixtures disproportionate to defect risk.

Also stop and escalate if:
- 3+ new tests chasing one survivor cluster — signals refactor, not more tests.
- A survivor reveals a real defect.

## Quick command reference

> **Worktree sessions**: prepend `-p <slug>` to every `docker compose` command. Reuse the same slug across the session. In-place sessions can omit `-p`.

```bash
# Fresh run
docker compose run --remove-orphans --rm integration-tests \
  mutmut run "<source>.<target>*"

# Text summary
docker compose run --remove-orphans --rm integration-tests mutmut results

# Survivors only
docker compose run --remove-orphans --rm integration-tests bash -c \
  'mutmut results 2>&1 | grep "survived"'

# Diff for a specific mutant
docker compose run --remove-orphans --rm integration-tests \
  mutmut show '<mutant.id>'

# Interactive TUI
docker compose run --remove-orphans --rm -it integration-tests mutmut browse

# Bulk triage
docker compose run --remove-orphans --rm integration-tests \
  python scripts/triage_mutmut_survivors.py --target <target>

# Sanity-check tests under Django runner
docker compose run --remove-orphans --rm integration-tests \
  python manage.py test --noinput <discovered.test.dotted.path>.test_<target>
```

## After the session — SDLC hygiene

Per `.claude/rules/main-rules.md`:

1. **Full library suite**: `docker compose run --remove-orphans --rm integration-tests`
2. **Lint & format**: `docker compose run --remove-orphans --rm lint-formatter`
3. **CHANGELOG.md** — only if `<source>/` (excluding tests) changed. Pure test-additions don't touch it.
4. **Conventional Commits**, one concern per commit.
5. **Never edit `pyproject.toml`'s `version`** by hand — releases are tag-driven.

## Cleanup (in-place sessions only)

```bash
docker compose run --remove-orphans --rm integration-tests bash -c 'rm -rf mutants mutants.sqlite'
# Then manually remove the [tool.mutmut] block from pyproject.toml and the
# root conftest.py if you don't want to keep them.
```

## Deliverable per session

- Before/after counts (killed, survived, type-caught) and effective score.
- Table of which mutants were killed and by which new assertion.
- List of surviving mutants with justification (all in accept-as-survivor buckets).
- Any bug findings or dead-code observations — **flagged, not acted on**.
