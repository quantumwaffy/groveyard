---
description: Audit the current changes for asyncio concurrency correctness (locks, blocking calls, races, cancellation) via the async-reviewer agent.
allowed-tools: Bash(git status:*), Bash(git diff:*), Bash(git log:*)
---

Run a concurrency audit of the current work.

1. Gather the scope of changes:
   - `git status`
   - `git diff` (and `git diff --staged`) to see uncommitted work; if the branch is
     the subject, also `git diff master...HEAD`.
2. Delegate to the **async-reviewer** agent, pointing it at the changed files.
   It audits (most important first): blocking calls on the event loop, bus
   transaction atomicity, per-device state races, **device→bus** lock ordering /
   deadlock, and cancellation safety — judged against `CLAUDE.md` and
   `docs/protocol.md`.
3. Present the findings ranked by severity, each with file:line, a one-line failure
   scenario (the interleaving or cancellation that triggers it), and a suggested
   fix. If a category is clean, say so briefly. Do not edit code — this is a review.