# Open implementation choices

These decisions remain open until their owning milestone plan verifies the relevant capabilities and records evidence. A proposal in the architecture is not proof that a dependency or service provides the required behavior.

| Choice | Planned decision point | Required evidence or boundary |
|---|---|---|
| Python 3.14 compatibility | M02 decision: retain 3.13 | pySHACL 0.40.1 requires >=3.9 (no upper bound), classifiers end at 3.13. Python 3.14 is NOT_RUN; any upgrade needs a new compatibility gate (ADR-0001). |
| HTTP application and service configuration | M03 verified | FastAPI 0.141.1 and Uvicorn 0.54.0 use startup-owned `C1_*` configuration with fixed service/database selection. Real-service readiness and API behavior passed; see the M03 report and ADR-0008. |
| OIDC token and principal profile | M03 verified | Require the configured issuer, audience, subject, expiry, issued-at, bearer purpose, and trusted human/service kind. Real Keycloak tokens, JWKS outage behavior and identity-selector rejection passed (M03-T01/T07). |
| Backend, identity, and authorization service versions, editions, and licenses | M01 | Inspect pinned artifacts and demonstrate required open-source operations. |
| Transaction, revision, receipt, and durable workflow boundary | M01, refined in M04 | Demonstrate behavior against the selected services; do not assume a cross-service transaction. |
| Identity/policy publication coordination and recovery | M03 verified | Use the workflow journal, current OpenFGA tuple confirmation, and a single-process writer lock. Three real process crash points, pending-state denial and readiness passed (ADR-0010). |
| Supported RDF/JSON-LD/SHACL subset and mapping | M02 | Specify round-trip behavior and explicit rejection of unsupported constructs. |
| Authorization model, current bindings, inheritance, and consistency | M03 verified | Use independent scope roles, exactly one current resource binding, fresh `HIGHER_CONSISTENCY` checks, and no positive grant cache. Revocation, binding faults and historical denial passed against live services (ADR-0009). |
| Source/index/interface formats, language coverage, and mappings | M08 | Select a bounded subset (SCIP and OpenAPI/AsyncAPI are candidates) with provenance and coverage semantics. |
| Software target sets and applicability rules | M08–M11 | Keep target versions explicit; distinguish applicable evidence, review candidates, and unresolved compatibility. |
| Context profiles, ranking, and budgets | M07 and M09–M11 | Preserve qualifications, source lineage, permissions, and explicit continuation. |
| Frontend and browser interaction details | M12 | Use the same secured APIs and verify accessible human workflows. |
| Deployment artifacts, operational limits, and recovery thresholds | M13 | Pin and inventory final artifacts; measure operational behavior and repeat recovery checks. |

This list is a navigation aid, not permission to change fixed requirements. The active milestone plan must resolve only choices needed for its acceptance gate and record any conflict explicitly.
