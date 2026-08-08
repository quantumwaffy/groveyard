# Contributing to groveyard

Thanks for considering a contribution. This document is the fast path from
"cloned the repo" to "opened a PR that passes review the first time."

For *why* the code is shaped the way it is, read the
[architecture overview](https://quantumwaffy.github.io/groveyard/architecture/)
and the [concurrency model](https://quantumwaffy.github.io/groveyard/architecture/concurrency/)
first — most review feedback on a first PR traces back to one of those two
pages.

## Development setup

groveyard uses [uv](https://docs.astral.sh/uv/) for environment and
dependency management. No Raspberry Pi is required — the whole test suite
runs against an in-memory fake transport.

```bash
git clone https://github.com/quantumwaffy/groveyard.git
cd groveyard
uv sync --all-groups   # dev + docs dependency groups
```

## The gates

Every change must pass all four before it is considered done. This is not a
suggestion — CI runs exactly these commands:

```bash
uv run ruff check .      # lint
uv run ruff format .     # format
uv run ty check          # type check (Astral's `ty`, not mypy/pyright)
uv run pytest             # tests, with a coverage report
```

`ruff` enforces mandatory type annotations (`ANN`), mandatory Google-style
docstrings on every public *and* private member (`D`), absolute-imports-only
(`TID`), and a blocking-call check for `async def` code (`ASYNC`) — the
library's single biggest hazard. `ty` must report zero errors; no bare `Any`
at a public boundary.

## Project layout

```
src/groveyard/
├── transport/    # bus handle + the one bus-wide lock (base, i2c, fake)
├── protocol/     # 0x04 bridge command encoding/decoding
├── board.py      # connection lifecycle, port registry, pin-mode cache
├── devices/      # one class per module: base.py + button.py, led.py, ...
├── testing/      # FakeBridgeFirmware — shipped so YOUR tests don't need a Pi
└── __init__.py   # the curated public surface

tests/            # pytest + pytest-asyncio, against the fake transport only
docs/             # this documentation site (MkDocs Material + mkdocstrings)
```

Full tour: [Layers overview](https://quantumwaffy.github.io/groveyard/architecture/).

## Coding conventions, condensed

The complete rules live in [`CLAUDE.md`](https://github.com/quantumwaffy/groveyard/blob/master/CLAUDE.md) (originally written to
brief an AI coding agent, which makes it unusually explicit — it is a fine
human reference too). The highlights:

- **Absolute imports only.** `from groveyard.transport.base import Transport`,
  never a relative import.
- **Type hints and docstrings everywhere,** public and private, Google
  style, citing `docs/protocol.md` where a value comes from the wire format.
- **OOP only.** Module level holds constants, enums, and type aliases —
  never free functions carrying logic, never mutable module state.
- **No magic numbers.** Name every pin mode, PWM bound, and timing constant
  where it is owned (bridge constants in `protocol/`, a driver's own register
  constants in that driver's module).
- **The typed error hierarchy.** Runtime failures raise
  `GroveyardError` subclasses; a caller mistake (an out-of-range argument)
  raises plain `ValueError`/`TypeError` instead — see
  [Errors](https://quantumwaffy.github.io/groveyard/api/errors/).
- **The `*_locked` convention is mandatory** for anything touching device
  state — see
  [Concurrency model § the `*_locked` convention](https://quantumwaffy.github.io/groveyard/architecture/concurrency/#the-_locked-convention).
  `asyncio.Lock` is not reentrant; getting this wrong is the single most
  common way a first driver PR needs a second round.

## Adding a new driver

[Writing a new driver](https://quantumwaffy.github.io/groveyard/guides/new-driver/)
is a full worked example — reading it end to end before opening a PR for a
new module will save you a review round. Short version:

1. Find the module's row in [`docs/protocol.md`](docs/protocol.md) (add one,
   with hardware facts only, if it does not exist yet).
2. Subclass the closest fit in `groveyard.devices.base`.
3. Add only the conversions the base class does not already give you; keep
   the raw value reachable on analog drivers.
4. Re-export the class from `devices/__init__.py` and `groveyard/__init__.py`.
5. Write tests against the fake transport — happy path, protocol edge cases,
   the concurrency contract, cancellation safety. See
   [Testing without hardware](https://quantumwaffy.github.io/groveyard/guides/testing/).
6. Run the gates.

## Working on documentation

The docs site lives in `docs/` and is built with
[MkDocs Material](https://squidfunk.github.io/mkdocs-material/) plus
[mkdocstrings](https://mkdocstrings.github.io/) for the auto-generated API
reference (so most of it stays in sync with the code by construction — edit
the docstring, not the page). Preview changes locally:

```bash
uv run mkdocs serve
```

## Using Claude Code in this repository (optional)

This repository ships `.claude/agents/` and `.claude/commands/` for
contributors who use [Claude Code](https://claude.com/claude-code). They are
entirely optional — nothing about the library depends on them — but if you
have it available, `/new-driver <module>` and `/concurrency-audit` automate
the workflow above, including an independent async-correctness review before
you open a PR. See the *Orchestration* section of [`CLAUDE.md`](https://github.com/quantumwaffy/groveyard/blob/master/CLAUDE.md).

## Commit and PR conventions

- Keep commits focused; a driver's implementation and its tests can be one
  commit.
- Write commit messages that explain *why*, not just what — the diff already
  shows what changed.
- In the PR description, note anything you deliberately left out or any
  assumption you made (see `CLAUDE.md`'s conventions for the kind of
  reasoning worth writing down — it applies to human PRs too).
- New behaviour needs new tests; a bug fix needs a regression test that fails
  without the fix.

## Reporting a bug or requesting a feature

Open a [GitHub issue](https://github.com/quantumwaffy/groveyard/issues). For
a bug, include: the driver/layer involved, expected vs. actual behaviour,
and — if it is concurrency-related — the smallest reproduction you can
manage (a two-task scenario is usually enough).

For a security-relevant report (something that could make hardware behave
dangerously, for example), see [`SECURITY.md`](https://github.com/quantumwaffy/groveyard/blob/master/SECURITY.md) instead of a
public issue.

## Code of conduct

This project follows the [Contributor Covenant](https://github.com/quantumwaffy/groveyard/blob/master/CODE_OF_CONDUCT.md). By
participating, you are expected to uphold it.
