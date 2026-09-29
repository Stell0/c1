# M07 code review

Target: changes from `7c1c7e67ad9e4b7ab49a6fbd4749ef9cdce77ad2`; final tested input manifest is recorded separately.

An independent Astra advisor reviewed the context code and identified seven defects. The milestone lead integrated the fixes and executed tests; the advisor reviewed the fixes without executing gates.

- Required topic-scheme references now fail closed in list, detail, export and writes.
- Part citations require matching Evidence/Document source revisions; this does not prove immutable bytes beyond the supported selector contract.
- Measurement targets match the registered predicate class ranges.
- Narrower expansion uses independently authorized active broader Assertions.
- Cursor checkpoints include used selector, matching and binding dependencies; private metadata is removed before publication.
- Orientation uses canonical labels and sorted types.
- Validated cursor tokens render in raw inline code with invariant byte overhead.

The independent closure review found no unresolved blocker in these fixes. The later live fixture failures exposed two additional necessary fixes: single-profile schema ChangeSets, and canonical UUID storage preflight. A focused security review recommended and reviewed the narrowly proven pre-commit C1-ST-004 cleanup. It found no blocking issue: uncertain receipt/head/security observations retain the barrier; only owned provisioning bindings can fail; actual writes/publication still require current authorization; history is retained. Its idempotent-response refinement was applied.

The root reviewed the actual code and focused tests. Live acceptance, full regressions and their exact result remain governed by M07-report.md; this document is code-review evidence, not a replacement for those gates.
