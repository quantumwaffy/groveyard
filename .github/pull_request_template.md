## What

<!-- What does this change, in one or two sentences? -->

## Why

<!-- The reasoning, not just the mechanics — this is what CLAUDE.md and
     CONTRIBUTING.md ask commit messages to capture; the PR description is a
     good place for it too if the commits don't. -->

## Checklist

- [ ] `uv run ruff check .` passes
- [ ] `uv run ruff format .` leaves nothing to reformat
- [ ] `uv run ty check` passes
- [ ] `uv run pytest` passes, and new behaviour has new tests (a bug fix has
      a regression test that fails without the fix)
- [ ] If this touches a driver or the transport/protocol/board layers: the
      `*_locked` locking convention is followed and the concurrency contract
      is tested (same-device serialisation, cancellation safety) — see
      [Concurrency model](https://quantumwaffy.github.io/groveyard/architecture/concurrency/)
- [ ] Docstrings updated for anything the mkdocstrings-generated API
      reference would otherwise show stale
- [ ] `docs/protocol.md` updated if this changes or adds wire-protocol facts

## Anything left out on purpose?

<!-- If part of the request was descoped, say what and why — see the
     "Delivering work" guidance in CLAUDE.md. -->
