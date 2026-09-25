# Open implementation choices

These decisions remain open until their owning milestone plan verifies the relevant capabilities and records evidence. A proposal in the architecture is not proof that a dependency or service provides the required behavior.

| Choice | Planned decision point | Required evidence or boundary |
|---|---|---|
| Python 3.14 compatibility | M02 | M00 selects Python 3.13 and locks development tools; re-check the proposed pySHACL dependency before upgrading. |
| HTTP framework and service configuration | M01, refined in M03 | Python is selected in M00; verify the framework, deployment wiring, and security-service settings with the infrastructure proofs. |
| Backend, identity, and authorization service versions, editions, and licenses | M01 | Inspect pinned artifacts and demonstrate required open-source operations. |
| Transaction, revision, receipt, and durable workflow boundary | M01, refined in M04 | Demonstrate behavior against the selected services; do not assume a cross-service transaction. |
| Identity/policy publication coordination and recovery | M01, refined in M03 | Define durable coordination, publication blocking, retry, recovery, and concurrency behavior. |
| Supported RDF/JSON-LD/SHACL subset and mapping | M02 | Specify round-trip behavior and explicit rejection of unsupported constructs. |
| Authorization model, current bindings, inheritance, and consistency | M03 | Verify current-policy checks, revocation, fail-closed behavior, and safe historical reads. |
| Source/index/interface formats, language coverage, and mappings | M08 | Select a bounded subset (SCIP and OpenAPI/AsyncAPI are candidates) with provenance and coverage semantics. |
| Software target sets and applicability rules | M08–M11 | Keep target versions explicit; distinguish applicable evidence, review candidates, and unresolved compatibility. |
| Context profiles, ranking, and budgets | M07 and M09–M11 | Preserve qualifications, source lineage, permissions, and explicit continuation. |
| Frontend and browser interaction details | M12 | Use the same secured APIs and verify accessible human workflows. |
| Deployment artifacts, operational limits, and recovery thresholds | M13 | Pin and inventory final artifacts; measure operational behavior and repeat recovery checks. |

This list is a navigation aid, not permission to change fixed requirements. The active milestone plan must resolve only choices needed for its acceptance gate and record any conflict explicitly.
