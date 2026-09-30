# M09 API — test-development context packages

`POST /v1/context` keeps the M07 grammar. M09 adds two optional fields, which
only software-task profiles accept.

```json
{
  "profile": "test-development",
  "profile_version": "1",
  "anchor": {"id": "<CodeSymbol | Capability | InterfaceOperation IRI>"},
  "target": {
    "snapshots": ["<SourceSnapshot IRI>", "..."],
    "contracts": ["<contract Document IRI>"],
    "configurations": ["<Configuration IRI>"]
  },
  "goal": "conformance",
  "formats": ["markdown", "structured"],
  "budget": {"unit": "bytes", "maximum": 65536},
  "cursor": "<optional continuation>"
}
```

## Request fields

- **`target`** takes either `{"target_set_id": IRI}` or inline members. At
  least one snapshot is required, with at most one snapshot per repository.
  Branch names are not accepted here: resolve them first with
  `POST /v1/software/targets/resolve` (M08).
- **`goal`** is `conformance` or `characterization`. It changes only the goal
  statement and the labels of the normative and implementation sections.
- **Required for `test-development`:** `target` and `goal`. Without them the
  request returns 400 `C1-CX-001`. Topics, keywords, fields and
  `project_ref` also return 400 `C1-CX-001`.
- **Graph profiles** such as `graph-context` reject `target` and `goal` with
  400 `C1-CX-001`. Their request digests are unchanged.

## Outcomes and errors

- **Hidden, unknown or wrong-class anchor or target member:** the same 404,
  `C1-CX-404` for the anchor or `C1-SW-404` for a target member.
- **Invalid target shape:** 400 `C1-SW-001` through `C1-SW-004`.
- **Anchor with no definition in a target snapshot:**
  `{"outcome": "unresolved", "reason": "no-definition-in-target", "target": …}`.
  C1 never substitutes another snapshot's definition.
- **Label anchors** can give `ambiguous` or `unresolved`, with only readable
  candidates listed.
- **Continuation after the target, any unit or its bindings changed:**
  409 `C1-CX-011` (restart).
- **Budget below one indivisible unit:** 422 `C1-CX-010` with
  `minimum_required`. Units are never truncated.
- **Time budget exceeded:** 503 `C1-CX-014`.

## Structured package

| Key | Content |
|---|---|
| `interpretation` | Profile, version and digest; revision; anchor; goal; target symbols; readable coverage records for the target snapshots. |
| `goal_statement`, `section_labels` | Goal-dependent labels. |
| `target` | Resolved snapshots (id, repository, commit, label), contracts and configurations. |
| `sections.normative` | Documentation parts (`documents` plus `describesSnapshot` of a target snapshot) and the target contract part. Role `normative`. |
| `sections.implementation` | The anchor's definition parts (`code-unit`) and direct same-snapshot dependencies (`dependency-unit`, with `referenced_at`). Role `structural`. |
| `sections.interfaces` | Operations with their `implementsOperation` and `declaredCall` basis and evidence citations. |
| `sections.tests` | Test definitions. `status` is `matching-run` or `definition-only`; `matching_results` lists the results of matching runs. |
| `sections.runs` | `match` (`matching` or `other-target`), `integration_mode`, `mocked_products`, `integration_evidence`, snapshots, configuration, `exercised` and result. Role `observed`. |
| `sections.fixtures` | `fixtureOf` definitions. |
| `sections.instructions` | `executionInstructions` sections with `untrusted: true`, fenced as text in Markdown and never executed. |
| `sections.discrepancies` | Recorded `discrepancy` assertions: `implementation_part`, `normative_part`, attribution, and quoted evidence. Role `interpretive`. |
| `gaps` | The fixed dependency statement, limit notices, a missing-normative notice, and readable `UnresolvedReference` and `ImportIssue` records for returned code files. |
| `sources` | Numbered citations: part citations with path, commit and content digest, and evidence citations with quotes. |
| `bounds`, `format_parity_digest` | As in M07. |

Every part unit carries `part_id`, `document_id`, `path`, `commit`,
`target_member`, `part_kind`, the exact `text`, and, for code,
`language` and `code_completeness` (`complete-unit` or `excerpt`). In
Markdown, code fences use the info string `<language> complete unit` or
`<language> excerpt`.
