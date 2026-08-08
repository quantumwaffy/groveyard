---
description: Orchestrate a task — decompose it and distribute the work across the specialist agents automatically.
argument-hint: <what you want built, changed, tested, or reviewed>
---

Act as the **orchestrator** for this task:

**$ARGUMENTS**

Follow the Orchestration policy in `CLAUDE.md`:

1. **Load context yourself** — read `CLAUDE.md` and the relevant `docs/protocol.md`
   rows before delegating.
2. **Decompose** into subtasks and map each to an agent via the routing table
   (`driver-author` / `test-author` / `async-reviewer`); handle trivial parts inline.
3. **Dispatch** with a self-contained brief per agent (module, exact protocol rows,
   acceptance criteria) — agents start cold and can't see this chat. Run independent
   subtasks in **parallel** (one batch), dependent ones **sequentially**.
4. Run the **standard driver pipeline** where relevant: `driver-author` →
   `async-reviewer` → fix loop.
5. Run the **gates** (`ruff check`, `ruff format`, `ty check`, `pytest`) once project
   config exists; otherwise state what should run.
6. **Report a synthesis:** what each agent produced, what passed the gates, and open
   questions. Don't dump raw agent transcripts. Don't claim verified unless the
   checks actually ran.

If the task is ambiguous or spans many modules, briefly outline the plan and the
agent assignments first, then proceed — delegation is pre-authorized, so you don't
need to ask permission to start.