# Mxx — Milestone title

**Status:** PLANNED | PROVISIONAL on prerequisite report. Plan revision: `<commit or working-tree description>`. **Planning does not authorize implementation.**
**Roadmap contract:** [PLAN.md](../../PLAN.md) §Mxx.
**Planned on:** YYYY-MM-DD.

## 1. Authority and starting state

- Record the controlling source baseline, approved changes, active instructions, and owner authorization.
- Record the actual repository revision and relevant working-tree changes.
- Identify prerequisite milestones and reports; state which facts were re-checked and which remain provisional.
- Record available tools, runtime/dependency versions, and relevant environment limitations.
- Identify source conflicts precisely and explain the resolution without weakening requirements.

## 2. Goal and boundaries

- State the observable outcome and acceptance contract from PLAN.md.
- List in-scope deliverables and explicit exclusions.
- Identify architectural and security invariants affected.

## 3. Decisions to resolve

| ID | Choice | Alternatives considered | Evidence and decision |
|---|---|---|---|
| D1 | `<bounded choice>` | `<alternatives>` | `<source, pinned version, capability or test evidence>` |

Do not treat proposed architecture mechanisms as verified capabilities. Record choices needing owner approval separately; an ADR does not grant scope authority.

## 4. Work breakdown

| Step | Files or modules | Owner | Dependency/order |
|---|---|---|---|
| W1 | `<paths>` | `<role/person>` | `<prerequisite>` |

State migrations and safe integration order. Parallelize only independently owned work within this milestone.

## 5. Test implementation

| Roadmap test | Executable check | Fixture and expected result | Failure condition |
|---|---|---|---|
| Mxx-T01 | `<test name>` | `<exact expected observations>` | `<observable failure>` |

Map every named roadmap check. Tests are future contracts until implemented and executed. Use real pinned services for guarantees that mocks cannot establish.

## 6. Verification commands

List exact commands, prerequisites, expected exit codes, regression selection, and security/no-AI checks. Distinguish local checks from remote CI or service checks.

```sh
<command>
```

## 7. Recovery and security

Describe failure points, recovery/rollback, permission and publication effects, authorization behavior, secret handling, and safe handling of untrusted input.

| Failure point | Expected safe behavior and recovery |
|---|---|
| `<failure>` | `<behavior>` |

## 8. Handoff

- **Deliverables:** `<paths>`
- **Demonstration:** `<reproducible steps and expected result>`
- **Evidence report:** `docs/milestones/Mxx-report.md`
- **Unresolved issues:** `<facts, blockers, or none>`
- **Gate:** `<exact required outcomes>`
- **Next bounded action:** `<owner decision needed; do not start next milestone automatically>`
