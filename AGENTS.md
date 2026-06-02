# Agent instructions (cross-tool)

This file follows the cross-tool [AGENTS.md](https://agents.md) convention. Claude Code, Copilot, Cursor, Cline, and Aider all read it.

For full project conventions and the production quality bar, see [`CLAUDE.md`](./CLAUDE.md) — both files share the same standards.

## TL;DR for any AI agent writing code here

- **Python 3.10+**, deps via `uv`, tests via `uv run pytest -q`.
- **PEP 604 unions** (`str | None`), type hints on every signature.
- **Structured logging** (`logging.getLogger(__name__)`) — never `print()` outside CLI entrypoints.
- **Real error handling** — no `except: pass`, no blanket `except Exception:` swallowing.
- **Validate every external input** at the boundary (length, type, range, format) BEFORE business logic.
- **Timeouts on every external I/O call** (default 5s). Paginate list endpoints. Cap loops over user input.
- **No magic numbers** — module-level constants with descriptive names.
- **Tests cover three branches**: happy path, edge cases, error paths. One test per acceptance criterion minimum.
- **Names describe meaning.** Banned: `simple_`, `helper_`, `utils_`, `do_`, `handle_` noise.
- **Comments**: write WHY, never WHAT. Default to none.

## Workflow

1. Read `spec.md` (and `feedback.md` if present on a retry run).
2. Scan only files you need to touch.
3. Implement minimum to satisfy acceptance criteria — no future-proofing.
4. Write tests in `tests/` mirroring `src/` layout.
5. Run `uv run pytest -q`. Must be green.
6. Stop. Do NOT `git commit` / `git push` — orchestrator handles that.

## Out of scope

- Refactoring unrelated modules
- Changing existing CI workflow once present
- Anything outside the repo working directory
