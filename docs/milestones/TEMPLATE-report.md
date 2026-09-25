# Mxx — Verification report

**Gate:** BLOCKED

Use `VERIFIED` only when every required check passes. Put the blocking check and evidence below; keep the gate line machine-readable.
**Approved plan revision:** `<commit>`
**Implementation revision:** `<commit or exact working-tree description>`
**Report date:** YYYY-MM-DD

## Environment and exact commands

Record operating system, runtime, dependency/service versions and artifact digests where relevant. Include prerequisites and fixtures used. Preserve exact commands and exit codes.

| Command | Purpose | Exit code | Result |
|---|---|---:|---|
| `<exact command>` | `<named check or demonstration>` | `<code>` | PASS / FAIL / NOT_RUN |

## Named checks

Report every roadmap test and any active-plan check. A `NOT_RUN` entry includes a concrete reason and the effect on the gate.

| Check | Result | Evidence path | Findings |
|---|---|---|---|
| Mxx-T01 | PASS / FAIL / NOT_RUN | `<path>` | `<concise evidence>` |

## Evidence and demonstration

- **Transcripts and artifacts:** `<repository-relative paths>`
- **Reproduction:** `<commands and expected observations>`
- Exclude credentials, private payloads, and confidential test evidence.

## Review findings and remaining limitations

Record findings, fixes, unresolved issues, and any owner-approved scope decision with its authority. Do not describe planned behavior or a mock-only result as a passed integration guarantee.

## Gate decision and next bounded action

State whether the acceptance gate is met and cite the evidence. Identify the next owner decision; do not start another milestone automatically.
