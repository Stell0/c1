# Milestone plans and reports

This directory holds the per-milestone planning and verification documents required by [PLAN.md](../../PLAN.md) §2 and [AGENTS.md](../../AGENTS.md) §3.

## Files

| File | Purpose | Created when |
|---|---|---|
| `Mxx.md` | Detailed implementation plan for milestone `Mxx` | When the owner selects `Mxx` for planning |
| `Mxx-report.md` | Verification report with reproducible evidence | When `Mxx` implementation reaches `VERIFYING` |
| `../evidence/Mxx/` | Command transcripts, exit codes, JUnit files, inventories | During `Mxx` verification |
| `../decisions/ADR-NNNN-slug.md` | Architecture decision records referenced by plans | When a plan resolves a choice |

## Required sections of a plan

Every `Mxx.md` contains these eight sections, in this order, with the content required by PLAN.md §2:

1. Authority and starting state
2. Goal and boundaries
3. Decisions to resolve
4. Work breakdown
5. Test implementation
6. Verification commands
7. Recovery and security
8. Handoff

## Status workflow

`NOT_PLANNED → PLANNED → APPROVED → IN_PROGRESS → VERIFYING → VERIFIED`, with `BLOCKED` and its recorded reason available at any stage. The status of record is the milestone table in PLAN.md §3. A plan file existing does not mean the milestone is approved. A report existing does not mean the gate passed; the report's gate line does.

## Provisional plans

A plan may be written before its prerequisite milestone is verified. Such a plan carries `PROVISIONAL on the Mxx report` in its status line. Before the owner moves it to `APPROVED`, the milestone lead re-validates every fact the plan marks as "verified at planning time" against the prerequisite report and current registries, and records the differences in the plan's section 1. A provisional plan never authorizes implementation.

## Report requirements

A report records, per AGENTS.md §11: milestone ID, approved plan revision, implementation revision, exact commands, runtime and dependency versions, fixtures, exit codes, PASS/FAIL/NOT_RUN per named check, evidence paths, review findings, remaining limitations, owner-approved scope decisions, a reproducible demonstration, and the bounded next action. Secrets and private payloads are excluded from evidence.

## ADR format

```
# ADR-NNNN — Title
Status: proposed | accepted | superseded by ADR-MMMM
Context: the question and the constraints from the specification and architecture.
Decision: what was chosen, stated precisely (versions, digests, names).
Evidence: URLs, tags, file paths, command output that support the decision, with the date checked.
Consequences: what becomes easier, what becomes harder, what must be re-verified later.
```

## Templates

Start a selected milestone plan from [TEMPLATE-plan.md](TEMPLATE-plan.md) and its completion record from [TEMPLATE-report.md](TEMPLATE-report.md). Keep the eight required plan sections in the order above. Replace each prompt with evidence specific to the active milestone; do not copy planning-time assumptions forward as verified facts.

The report gate reflects the evidence actually obtained. Mark unavailable remote services or workflows `NOT_RUN` and record the blocking reason. A required check marked `NOT_RUN` keeps the gate BLOCKED under PLAN.md §2 and AGENTS.md §11; a lower-priority plan cannot waive it.
