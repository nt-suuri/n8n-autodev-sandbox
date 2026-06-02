# n8n-autodev-sandbox — agent instructions

You are working in a Python 3.10+ sandbox that the n8n auto-dev pipeline opens features against. Every PR you write must be production-grade — this is not a scratch repo.

## Stack
- **Language**: Python 3.10+ (PEP 604 unions everywhere).
- **Deps**: `uv` (pyproject.toml + `uv.lock`). Add deps with `uv add <pkg>`. Dev deps under `[project.optional-dependencies] dev` → `uv add --dev <pkg>`.
- **Test runner**: `uv run pytest -q`.
- **Lint** (when present): `uv run ruff check`. Format: `uv run ruff format`.
- **CI**: `.github/workflows/ci.yml` runs `uv sync --extra dev && uv run pytest -q` on every PR.

## Layout
```
src/<package>/        application code
tests/                pytest tests, mirror src/ layout
pyproject.toml        deps + tool config
```

## Conventions
- **One function = one responsibility.** Pure functions over classes when possible.
- **Type hints on every signature**, PEP 604 unions (`str | None`, never `Optional[str]`).
- **Logging** via `logging.getLogger(__name__)`. Never `print()` outside CLI entrypoints. Configure once in `logging_config.py` if missing.
- **Errors**: raise domain-specific exceptions at boundaries. Never `except: pass`. Never blanket `except Exception:` that swallows the error.
- **Input validation** at every external boundary (HTTP/file/env/DB). Use Pydantic models or explicit length/type/range checks BEFORE business logic.
- **Resource limits**: every external I/O call has a timeout (default 5s). List endpoints paginate. Loops over user input have a max-iteration guard.
- **Idempotency**: writes must be safe to retry. Use natural keys or explicit idempotency tokens.
- **No magic numbers** — extract to module-level constants.
- **Security**: parameterized queries only; never concat user input into shell. Never log secrets/PII.

## Tests (non-negotiable)
Every public function ships with tests covering:
1. Happy path
2. Edge cases (empty, `None`, boundary values, zero, very large)
3. Error path (dependency fails — mock it raising; assert the error is surfaced not swallowed)

One test per acceptance criterion minimum. Tests live in `tests/test_<module>.py`.

## Naming
Names describe meaning. Banned prefixes/suffixes: `simple_`, `advanced_`, `_simplified`, `helper_`, `utils_`, `do_`, `handle_`. If you can't name a function without one of those, split it.

## Comments
Default: none. Write WHY, never WHAT. Self-explanatory code > comments. No multi-paragraph docstrings on internal helpers — one line max.

## Git workflow (orchestrator handles, not you)
- Never `git commit`, never `git push`.
- Branch naming and PR creation: orchestrator's job.
- PR body must include `Closes #<issue>` (orchestrator appends it).

## Self-check before stopping
1. Every acceptance criterion in `spec.md` implemented?
2. `uv run pytest -q` green?
3. Type hints on every new signature?
4. Logging at state-change + error sites?
5. External inputs validated at the boundary?
6. Timeouts on all external I/O?
7. Tests cover happy + edge + error paths?
8. Would you approve this PR if a junior dev opened it on a production service? If no — fix it.

## Out of scope (do not touch)
- Existing modules unrelated to the spec
- CI workflow file (`.github/workflows/ci.yml`) once it exists — only create if missing
- Anything outside the repo working directory
