# M06 review record

Reviewed on 2026-09-28 against the uncommitted M06 implementation, starting
from `29ddc193cd28ff777b62daf21caea35e0b83f6d5`.

The milestone lead integrated bounded implementation and test reviews. A
separate reviewer checked the final history snapshot coordination delta and
reported no unresolved production security or semantic blocker. This review
does not substitute for the real-service gate.

Fixed findings include document permission checks on insert/move, explicit
inheritance-parent matching, preservation of current bindings during content
moves, rejection of part retyping, candidate authorization before history
fetches, inclusion of a part's departure revision, stale history cursors,
historical class-hint completeness, final authorization ordering, cancellation
of sibling fetches, and workflow-manifest snapshot alignment.

The final alignment review checked both a changing manifest enumeration head
and a stable manifest head different from the authorization plan. Unit tests
reject both cases before using candidates or fetching backend history. The
original complete plan is reauthorized before publication, after the knowledge
head check, under the same absolute request deadline.

Test review corrected expired fixture-client tokens, invalid OpenFGA Read
filters, incorrect fixture-array positions, and an extra storage-wrapper
dereference. These corrections preserve real tokens, current permission
checks, the two-second request limit, and the named acceptance assertions.

Transport review found an in-scope ambiguity for canonical document IRIs
ending in `/parts`, `/render`, `/export`, or `/history`. ASGI decodes path
escapes before routing. The authenticated `by-id` query alias reuses the
bounded detail service, with focused suffix tests and live T01/T02 parity
coverage. The pre-alias combined gate was interrupted; closure requires a
complete rerun against the corrected frozen inputs.

The post-alias combined 72-case real-service run completed with 71 passes and
one failure. All seven M06 cases and the M01–M04 regressions passed; the only
failure was M05 T04, where its long-running fixture reused a cached token that
expired. The test-only helper now obtains a fresh real token for each action.
The complete M05 group rerun passed all 12 cases in 1455.99 s; its command,
log, and JUnit evidence are recorded in
[`M06-report.md`](../../milestones/M06-report.md). The separate M01 probe
also passed 12 tests. The isolated stack was then stopped with volumes
retained. The gate is PASS; the implementation revision remains for the owner
to record after the feature commit.
