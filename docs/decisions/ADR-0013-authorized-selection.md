# ADR-0013 — Authorized selection for bounded queries

**Status:** M05 implementation decision under the owner's implementation request.

## Decision

Each query captures the current workflow head and uses one absolute deadline. A
head-keyed projection of current bindings, scopes, and pending operations finds
provisional candidates. OpenFGA ListObjects supplies readable scope candidates,
but neither source alone proves a resource readable. Before any knowledge
record enters matching, counting, ordering, explanations, export, or traversal,
the service checks **every provisional resource** under the M03 plane:
active current binding and scope, no pending operation, exactly one matching
live `bound_to` tuple, and a fresh `can_read` decision. Assertions and linked
resources used by filters must be in that fully authorized set. The service
checks the workflow head and relevant authorization again before releasing a
response. No positive decision is cached across requests.

An unbounded readable-scope set, candidate overflow, deadline, security
service failure, or changed security head returns an error without partial
items or counts. Current scope/project restrictions are query narrowing, never
grants. A cursor pins the content revision and filter, and every continuation
rebuilds the current authorization selection.

The earlier M05 plan proposed checking only the final page. That allowed an
off-page record with a missing or mismatched OpenFGA binding to affect counts,
filters, or traversal. This ADR and the corrected M05 D1 supersede that step.

## Evidence and limits

M03's `AuthorizationPlane._resource` implements the live tuple and binding
checks. The [OpenFGA relationship-query documentation](https://openfga.dev/docs/interacting/relationship-queries)
states that ListObjects can stop at its configured result or time limit; the
[configuration reference](https://openfga.dev/docs/getting-started/setup-openfga/configuration)
lists defaults of 1000 results and 3 seconds. The
[consistency documentation](https://openfga.dev/docs/interacting/consistency)
states that HIGHER_CONSISTENCY bypasses the query cache. M05 tests must prove
the algorithm against the pinned OpenFGA model and TerminusDB services.
The supported deployment pins ListObjects to 1000 results and a 3-second
server deadline; C1 rejects at 500 scopes and enforces a 2-second client
deadline. A deployment that lowers those OpenFGA values must lower C1's
readable-scope cap or refuse query readiness, since the ListObjects response
has no completeness flag.

The workflow-head check coordinates C1-managed security writes. Direct
out-of-band OpenFGA mutations are outside that coordination and are prohibited
for this deployment. The 5000-candidate and 2-second caps can make a query
fail when hidden provisional data adds work. Successful response content is
required to be independent of hidden data; identical latency or availability
under arbitrary hidden-state changes is not claimed.
