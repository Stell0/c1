# M08 API — software targets and target-pinned lookup

Both routes need an authenticated bearer token and exist only while the
data-only `software` profile is installed. Otherwise they answer `404`
`C1-SW-404`, the same as an unknown route. Both evaluate one authorized
selection (M05). Every match, count, order, citation, and coverage entry
is computed over records the caller can read under current bindings.
Hidden, missing, and wrong-class target members get the same `404`.
Each request runs within the configured request budget and returns `503`
`C1-SW-007` when it is exceeded. Neither route runs, fetches, or follows
stored content.

## Target

A target is either `{"target_set_id": "<TargetSet IRI>"}` or an inline
object:

| Field | Meaning |
|---|---|
| `snapshots` | SourceSnapshot IRIs; at most one per repository (`C1-SW-004`). |
| `branches` | `[{"repository": "<CodeRepository IRI>", "branch": "main"}]`. Allowed only with `as_of`. |
| `as_of` | An RFC 3339 timestamp with a zone. A branch resolves to the latest readable BranchObservation at or before it. |
| `contracts` | Contract Document IRIs, such as a specific `openapi.json` version. When given, operations are limited to these. |
| `configurations` | Configuration IRIs. When given, runs must use one of them. |

There is no implicit "latest". A target with neither snapshots nor
branches is `400` `C1-SW-002`, and branches without `as_of` are `400`
`C1-SW-003`. Each branch resolution is reported. A branch with no
observation at `as_of` is listed as `unresolved` with reason
`no-observation`; it never falls back to another snapshot.

## `POST /v1/software/targets/resolve`

Body: a target, plus an optional `revision` (C1 knowledge revision).
The response has:

- `revision`
- `target`: resolved snapshots with their repository and commit, plus
  contracts and configurations
- `branch_resolutions`: repository, branch, `as_of`, observation,
  `observed_at`, and snapshot
- `unresolved`

## `POST /v1/software/lookup`

Body fields:

| Field | Meaning |
|---|---|
| `target` | Required; the target shape above. |
| `select` | Optional narrowing: `symbol_id`, `capability_id` (symbols with `implementsCapability`), `operation_id` (symbols with `implementsOperation` or `declaredCall`), and `path_prefix`. |
| `kinds` | A subset of `occurrences`, `operations`, `tests`, `runs`, `documents`, `relationships`, `coverage`, `issues`, `unresolved`. Default: all. |
| `limit` | 1–200, default 50 (`422` `C1-SW-005` outside the range). |
| `cursor` | A signed, revision-bound continuation. It is reauthorized on every page and is never a grant. |
| `revision` | Optional C1 knowledge revision, independent of the software target. |

Each item has `kind`, `id`, `target_member`, and `basis` (`structural`,
`declared`, `static-extraction`, `interpretive`, or `observed`). Items by
kind:

- **Occurrences:** the symbol, roles, and a half-open zero-based range
  with its position encoding. Each also carries a `citation`: Document,
  path, commit, content digest, part, part kind, `code_completeness`
  (`complete-unit` or `excerpt`), and the exact excerpt text.
- **Relationships:** predicate, subject, object, origin, attribution,
  generating activity, and in-target evidence.
- **Runs:** only runs whose every snapshot is in the target and whose
  configuration matches when the target declares configurations.
  Mocked runs report `integration_mode: "mocked"` and the mocked
  products.
- **Tests:** `definition-only` when no matching run exists.
- **Coverage, issues, and unresolved references:** records bound to
  target snapshots. Their paths and messages appear only when readable.

`count` is the total of readable matching items. `next_cursor` is present
only when more items exist.
