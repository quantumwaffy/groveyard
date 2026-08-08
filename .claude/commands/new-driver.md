---
description: Scaffold a groveyard device driver + tests for a starter-kit module, wired to the protocol reference and project conventions.
argument-hint: <module> (e.g. button, led, buzzer, relay, light-sensor, sound-sensor, potentiometer, dht, ultrasonic, rgb-lcd)
---

Implement the **`$ARGUMENTS`** device driver for groveyard.

Steps:

1. Read `CLAUDE.md` (architecture, two-lock concurrency model, tooling,
   conventions) and `docs/protocol.md` (the relevant command row and any device
   conversions for `$ARGUMENTS`). Look at an existing driver + the fake transport
   to match patterns; if none exist yet, establish the pattern per `CLAUDE.md` and
   say so.
2. Delegate the implementation to the **driver-author** agent. It must produce:
   the async driver class (per-device lock, cached state, named constants, full
   type hints, English docstrings with units/ranges/timing), tests against the
   fake transport (happy path + the protocol edge cases and concurrency contract
   relevant to this module), and the public-API export wiring.
3. When it returns, run `uv run ruff check .`, `uv run ruff format .`,
   `uv run ty check`, and `uv run pytest` if project config exists; otherwise state
   what should be run.
4. Summarize: files added, the locking/cancellation reasoning, protocol citations,
   and any open questions. Do not claim it's verified unless the checks actually ran.

If `$ARGUMENTS` is empty or isn't a starter-kit module, list the supported modules
from `docs/protocol.md` §6 and ask which one.