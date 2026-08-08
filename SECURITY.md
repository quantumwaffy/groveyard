# Security Policy

groveyard drives physical actuators (relays, buzzers, LEDs) — a bug that lets
untrusted input reach a driver in an unsafe way is a safety issue as much as
a security one. Reports are taken seriously.

## Supported versions

Only the latest published `0.x` release is supported. There is no long-term
support branch while the project is pre-1.0.

## Reporting a vulnerability

Please **do not** open a public GitHub issue for a security report. Instead,
use
[GitHub's private vulnerability reporting](https://github.com/quantumwaffy/groveyard/security/advisories/new)
for this repository, or email <sashachistyh@gmail.com> with:

- A description of the issue and its potential impact (e.g. "can drive an
  actuator to an unintended state", "can hang the event loop", "can deadlock
  the bus").
- Steps to reproduce, ideally against the fake transport
  (`groveyard.testing`) so no hardware is needed to verify.
- The version of groveyard affected.

You should receive a response within a few days. Once a fix is available, a
patch release will be published and the report credited (unless you prefer
otherwise) in the [changelog](https://quantumwaffy.github.io/groveyard/changelog/).

## Scope

In scope: the groveyard library itself (`src/groveyard/`) — locking
correctness, cancellation safety, input validation, and the wire protocol
implementation. Out of scope: the GrovePi+ board's own firmware, and
`smbus2`, which are third-party.
