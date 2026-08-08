# groveyard — project guide for Claude

A **modern, async Python library** for driving the sensors and actuators of a
GrovePi+ starter kit on a Raspberry Pi. We are building this **from scratch**. The
design goal is a clean, fully-typed `asyncio` API where many concurrent tasks can
safely share one I2C bus and stateful devices **without race conditions**.

> **Language rule:** every artifact in this repo — code, comments, docstrings,
> commit messages, docs — is written in **English**. (Conversation with the user
> may be in any language; the repo is not.)

---

## Status

All five layers are implemented and reviewed: `transport/`, `protocol/`,
`board.py`, ten drivers under `devices/`, and the curated `__init__.py`
surface — see [the architecture docs](docs/architecture/index.md) for a full
tour. The design decisions below describe what was actually built, not a plan
for later. New work is additive: a new module means a new `Device` subclass
(see [Writing a new driver](docs/guides/new-driver.md)), not an edit to a core
layer.

What exists today: this guide, `docs/` (the full documentation site, built
with MkDocs — run `uv run mkdocs serve` to browse it locally), the
`.claude/` agents + commands, `src/groveyard/` (the library), and `tests/`.

---

## The hardware in one paragraph

The board is an I2C **bridge** (address `0x04`, bus 1): the Pi is master, the
board firmware relays commands to Grove ports. Every bridged operation is a
`write [cmd, a, a, a] → sleep → read` transaction on the shared bus. A few devices
(the RGB LCD) are **native I2C** and talk on their own address but still share the
physical bus. Full byte-level details, command table, and per-module conversions
live in **`docs/protocol.md`** — read it before writing any driver.

---

## Architecture (layers, bottom → top)

Keep these layers separate; each depends only on the one below it.

1. **Transport** (`transport`) — owns the smbus2 handle and the **single bus
   lock**. Exposes low-level `read`/`write` primitives. Runs the *blocking* smbus2
   calls via `asyncio.to_thread` so the event loop is never blocked. Defines an
   abstract `Transport` interface with two implementations: real hardware and an
   in-memory **fake** used by tests (no Raspberry Pi required to develop or run CI).
2. **Bridge protocol** (`protocol`) — pure encoding/decoding of the `0x04`
   firmware command set (`pin_mode`, `digital_read/write`, `analog_read/write`,
   `ultrasonic`, `dht`, `version`, echo-byte handling, not-ready sentinels,
   retries, per-command timing). No device concepts, no locks beyond the bus lock
   it borrows from the transport.
3. **Board / hub** (`board`) — the connection object. Holds the transport, does the
   firmware-version handshake on connect, tracks **cached pin modes**, and is the
   factory that hands out device drivers bound to a port. Async context manager
   (`async with Board(...) as board:`).
4. **Drivers** (`devices/…`) — one high-level class per module (`Button`, `Led`,
   `Buzzer`, `Relay`, `LightSensor`, `SoundSensor`, `Potentiometer`, `Dht`,
   `Ultrasonic`, `RgbLcd`). Each owns its **per-device lock** and cached state.
5. **Public API** (`__init__`) — curated exports; the only surface users import.

---

## Concurrency model — the heart of this library

Two hazards, two locks. This is non-negotiable design.

- **Shared bus → one bus lock (in the transport).** A bridged op is
  write→sleep→read; if two tasks interleave, one reads the other's reply. The
  transport wraps *the whole transaction* in a single `asyncio.Lock` so every bus
  exchange — bridged or native-I2C — is atomic with respect to every other.
- **Stateful device → one lock per device.** A single logical operation can span
  several bus transactions (configure-then-read; read-modify-write on the LCD or a
  dimmable LED). The per-device `asyncio.Lock` makes that logical operation atomic
  so two tasks driving the *same* device can't tear its state. Two tasks driving
  *different* devices proceed concurrently (only briefly contending on the bus lock).

Rules:

- **Never block the event loop.** All smbus2 / `time.sleep` equivalents go through
  `asyncio.to_thread` and `await asyncio.sleep`. No synchronous I/O in `async def`.
- **Lock ordering to avoid deadlock:** acquire the **device lock first, then the
  bus lock** (device → bus), always in that order. The bus lock is a short leaf
  lock held only around one transaction; never call back into a device method
  while holding the bus lock.
- **Cancellation safety:** a task cancelled mid-operation must not leave a device
  half-configured or a lock held. Use `async with lock:` (releases on cancel) and
  keep critical sections minimal. Actuators (relay, buzzer, LED) should fail safe
  to *off* on disconnect/close.
- **Idempotent setup:** cache pin mode / init state and skip redundant
  reconfiguration, but guard the cache with the device lock.
- Prefer `asyncio.TaskGroup` in examples/tests for structured concurrency.

---

## Tech stack & tooling

- **Python:** target 3.12+ (PEP 695 type params, `TaskGroup`, `Self`, modern typing).
- **Env & deps:** `uv`.
- **Lint + format:** `ruff` (both `ruff check` and `ruff format`).
- **Type checking:** `ty` (Astral's type checker) — code must be fully typed and
  `ty`-clean. *(Note: `ty`, not mypy/pyright.)*
- **Tests:** `pytest` + `pytest-asyncio`, run against the **fake transport** — no
  hardware in CI.
- **Hardware I/O:** `smbus2` (only real dependency for on-device use; kept behind
  the transport so tests never import it).

Common commands:

```bash
uv sync --all-groups        # install deps (dev + docs groups)
uv run ruff check .         # lint
uv run ruff format .        # format
uv run ty check             # type check
uv run pytest               # tests + coverage report (fake transport, no Pi needed)
uv run mkdocs serve         # preview the documentation site locally
```

CI (`.github/workflows/ci.yml`) runs all four gates plus a package build and a
strict docs build on every push and PR; `release.yml` publishes to PyPI via
trusted publishing on a `v*` tag — see `RELEASING.md`.

If a command's exact form isn't set up yet, propose it rather than guessing a tool
we didn't choose (e.g. don't invoke mypy or poetry).

---

## Coding conventions — mandatory

These are hard rules, not preferences. Where a tool can enforce a rule it is wired
into `ruff`/`ty` (see *Enforced by tooling* below) so violations fail the gates;
the rest are enforced in review by `async-reviewer` and the orchestrator.

### Imports, types, docs

- **Absolute imports only.** Never use relative imports (`from .x` / `from ..x`).
  Always `from groveyard.transport.base import Transport`. *(ruff `TID252`.)*
- **Type hints everywhere.** Every function, method, parameter, and return value is
  annotated — no exceptions. No bare `Any` at the public surface. Code must be
  `ty`-clean. *(ruff `ANN` for presence, `ty` for correctness.)*
- **Docstrings everywhere.** Every module, class, and method — public *and* private
  — has an English docstring (Google style): what it does, units, ranges, side
  effects, timing, and raised exceptions; cite `docs/protocol.md` where relevant.
  *(ruff `D`, google convention.)*

### Object-orientation & design principles

- **OOP only.** Behaviour lives in classes. Module level holds *only* constants,
  enums, and type aliases — never free functions carrying logic, never mutable
  module-level state.
- **SOLID:**
  - **S**ingle responsibility — one class/layer, one job (transport moves bytes;
    protocol encodes commands; board manages ports/lifecycle; a driver models one
    device). Nothing reaches across its layer.
  - **O**pen/closed — extend by adding a `Device` subclass or a `Transport`
    implementation; never edit the core layers to bolt on a new module.
  - **L**iskov — every `Transport` and every `Device` is substitutable for its base
    (the fake transport must behave like the real one).
  - **I**nterface segregation — small, focused abstractions (`Transport`,
    `BusSession`, `Device`); no fat god-objects.
  - **D**ependency inversion — depend on abstractions, not concretions. Inject
    collaborators through the constructor (`Board(transport)`, `Device(board)`);
    higher layers never instantiate `smbus2` directly.
- **KISS** — the simplest design that satisfies the requirement; no cleverness.
- **YAGNI** — build only what a listed starter-kit module needs now; no speculative
  hooks, config, or abstraction for imagined futures.
- **DRY** — one source of truth (protocol bytes in `protocol`, register constants in
  their driver); factor duplication into a base class or helper.
- **Separation of concerns / layering** — respect the layer diagram above; a change
  to one layer must not force edits in another.
- **Composition over inheritance** — inherit only for genuine *is-a* (a driver *is a*
  `Device`); otherwise compose (a `Board` *has a* `Transport`).
- **Law of Demeter** — talk to your direct collaborators; don't chain through their
  internals.
- **Explicit over implicit**, and **fail safe** — actuators default to *off*; errors
  surface as the typed hierarchy, never as bare exceptions or silent `None`.

### Naming, values, errors

- **Naming:** `snake_case` functions, `PascalCase` classes, `SCREAMING_SNAKE`
  constants; module names match the layer. Command constants live in the layer that
  owns them (bridge constants in `protocol`, LCD registers in the LCD driver).
- **No magic numbers** — name every pin mode, PWM bound, and timing constant.
- **Errors:** the typed hierarchy `GroveyardError` → `TransportError`,
  `ProtocolError`, `DeviceNotReadyError`. Bounded retries for transient bus errors
  live in transport/protocol, never in drivers.
- **Values:** analog drivers always expose the raw `0..1023` reading; unit
  conversions are convenience on top (see `docs/protocol.md` §5).
- Keep drivers thin: intent + owned state + the device lock; the bytes belong to
  `protocol`.

### Enforced by tooling

`ruff` selects `ANN` (annotations), `D` (docstrings, google), `TID`
(`ban-relative-imports = "all"`), `ASYNC` (no blocking calls in `async`), plus
`E/W/F/I/UP/B/SIM/RUF`. `ty` checks type correctness. Run the gates before "done".

---

## Testing approach

- Drivers and protocol are tested against the **fake transport**, which records
  written frames and returns scripted replies (including echo bytes and not-ready
  sentinels). No Raspberry Pi, no smbus2 import in the test path.
- Cover the **concurrency contract explicitly**: tests that launch many tasks
  against one device (must serialize) and against different devices (must not
  needlessly serialize), and tests asserting bus transactions never interleave.
- Cover **cancellation**: cancel mid-transaction, assert no lock leak and no
  half-written device state.
- Cover protocol edge cases: echo-byte handling, `23`/`255` retry, DHT `NaN`/range
  rejection, ultrasonic timing.

---

## Orchestration — how work is distributed

**You (the main thread) are the orchestrator.** The user sends one request; you
decompose it and delegate to the specialist subagents automatically. The user has
given **standing authorization** to delegate proactively — this overrides the
default "don't spawn agents unless asked", so you do not stop to ask permission
before routing work. Subagents cannot spawn other subagents, so *all* routing and
integration happens here in the main thread.

### Routing policy

| Incoming intent | Route to | Produces |
|-----------------|----------|----------|
| Add / change a device driver | `driver-author` | driver class + its tests |
| Add / expand tests only | `test-author` | tests vs the fake transport |
| Review async / concurrency correctness | `async-reviewer` | ranked findings (read-only) |
| Architecture / protocol question, tiny edit | **handle inline** | answer / small change |

### Workflow

1. **Understand & load context yourself** — read `CLAUDE.md` and the relevant
   `docs/protocol.md` rows *before* delegating, so each brief is precise.
2. **Decompose** the request into subtasks; map each to an agent via the table.
3. **Dispatch.** Give every agent a **self-contained brief** — it starts cold and
   cannot see this chat: name the module, the exact protocol rows, and the
   acceptance criteria.
   - Independent subtasks (e.g. two unrelated drivers) → **parallel** (multiple
     `driver-author` instances in one batch).
   - Dependent subtasks → **sequential** (one output feeds the next).
4. **Standard driver pipeline:** `driver-author` → `async-reviewer` → if findings,
   loop back to `driver-author` (or fix inline for trivial issues) → gates.
5. **Gates:** run `uv run ruff check . && uv run ruff format . && uv run ty check &&
   uv run pytest` (once project config exists) before declaring done.
6. **Integrate & report** — synthesize results for the user; relay what matters,
   don't dump raw agent transcripts. State what ran, what passed, and open questions.

### When to handle inline (do NOT delegate)

Delegation has a cold-start cost — reserve it for substantial, self-contained work.
Answer directly for: questions, single-file or small edits, protocol lookups, quick
fixes, and anything faster to do than to brief. Never fan out for its own sake.

The `/orchestrate <task>` command is the explicit trigger for this flow; the same
routing also applies to plain requests.

## Working agreements for Claude

- Act as the **orchestrator**: route each request per the Orchestration section
  above; delegation is pre-authorized, integration and gates stay with you.
- Read `docs/protocol.md` **before** writing or reviewing any driver.
- Respect the layer boundaries and the **device→bus** lock order every time.
- Do not introduce a synchronous public API or block the event loop.
- Do not add dependencies beyond the chosen stack without flagging it.
- English in the repo; you may converse with the user in any language.

### Specialized agents (`.claude/agents/`)

- **driver-author** — implements a new device driver end-to-end (driver + tests)
  following the layering, concurrency, and typing rules here.
- **async-reviewer** — read-only audit of `asyncio` correctness: lock usage and
  ordering, blocking calls in the loop, bus/device race conditions, cancellation
  safety.
- **test-author** — writes `pytest`/`pytest-asyncio` tests against the fake
  transport, including the concurrency and cancellation contracts above.

### Slash commands (`.claude/commands/`)

- **/orchestrate `<task>`** — explicit trigger for the Orchestration flow: decompose
  the task and distribute it across the agents. (Plain requests get the same routing.)
- **/new-driver `<module>`** — scaffold a driver + its tests for a starter-kit
  module, wired to the protocol reference and conventions.
- **/concurrency-audit** — run the async-reviewer over the current changes.