# ADR-0007 — Supported interchange and lexical values

**Status:** M02 implementation decision under the owner's implementation request.
The owner explicitly approved the SHACL alternative correction on 2026-09-27.

## Decision

Publish the `core` profile as a local manifest, JSON-LD context, SHACL shapes,
vocabulary rationale and generated backend schema. The manifest defines classes,
fields, ranges, cardinalities, keys and version requirements. Domain extensions
provide data in the same format and cannot add Python code or hooks. Migrations
are proposals identifying affected classes and checks, not executed changes.

Use RDFLib 7.6.0 for RDF/JSON-LD semantics and pySHACL 0.40.1 for the selected
structural shape subset. Run with inference, advanced features, JavaScript and
remote imports disabled. Only trusted bundled shape graphs reach pySHACL;
ingested data cannot supply executable validation rules.

Resolve only registered bundled context identifiers in memory before processing.
Reject inline or remote contexts, imports, lists, nesting/reverse/index/JSON
extensions, blank nodes, unknown predicates/classes and unsupported datatypes
with explicit diagnostic codes before storage. A rejected batch must not cause
any backend write or context fetch. A literal object cannot carry both a language
tag and an explicit datatype in JSON-LD syntax.

`LiteralValue` stores authoritative lexical text, datatype and optional lowercased
BCP 47 language. A language tag implies `rdf:langString`. Typed numeric/time
backend fields are derived projections; they never replace lexical text. Values
outside a backend projection range retain their full lexical representation and
an explicit projection status. Native JSON numeric/boolean input is normalized
from its decoded JSON value; explicitly typed lexical strings retain their
original spelling. The RDFLib semantic check and lexical bridge must agree.

TerminusDB rejects repeated identical `ValueHash` subdocuments in one document
batch with `api:SameDocumentIdsMutatedInOneTransaction`. Embedded `LiteralValue`
and `Value` records use backend `Random` keys instead. These backend-only IDs are
not RDF resource identities and are omitted from interchange; named resources
retain their canonical identifiers. T01 must demonstrate repeated literal values
and exact lexical round-trip in the same batch.

Keyword normalization `c1-kw-1` is NFKC, casefold, NFKC, trim and Unicode whitespace
collapse. Preserve first original spelling for duplicate language/normalized
pairs. Matching is exact; an untagged query may match any language. Empty filters
add no condition. Diacritics, phrases and disagreements are retained.

Time boundaries retain known, unknown or explicitly unbounded state. Known
coarse values derive a comparison interval; they are not replaced by fabricated
precision. Intervals are half-open. Timezone-unknown values retain that uncertainty.
Recording time is not a client-writable field. OWL-Time's deprecated
`time:inXSDDateTime` is used only where `xsd:dateTime` without a timezone cannot
truthfully be represented by `time:inXSDDateTimeStamp`.

## Approved plan correction

D5 restricts `sh:or` to an IRI/literal choice, but D2/D3 permit datatype alternatives
for labels and temporal fields. The owner-approved correction admits only flat declared
datatype alternatives, retaining rejection of nested logic, scripts, remote
imports and every unsupported operator. This enforces the existing field
contract without broadening the accepted knowledge datatype set. The explicit
owner approval supersedes D5's restriction to IRI/literal alternatives.

## Evidence and sources

- [JSON-LD 1.1](https://www.w3.org/TR/json-ld11/) defines context and value-object
  semantics; C1 advertises its explicit subset rather than unrestricted JSON-LD.
- [RDF 1.1 concepts](https://www.w3.org/TR/rdf11-concepts/) separates RDF terms
  from literal value interpretation and graph identity.
- [SHACL](https://www.w3.org/TR/shacl/) defines structural constraints, not truth
  or source independence. Contradictory claims are separate assertion resources.
- [XML Schema datatypes](https://www.w3.org/TR/xmlschema11-2/) and
  [BCP 47 syntax](https://www.rfc-editor.org/rfc/rfc5646) inform literal validators.
- [OWL-Time](https://www.w3.org/TR/owl-time/) supplies the reused temporal terms.
- [Pydantic models](https://docs.pydantic.dev/latest/concepts/models/) supplies
  typed record validation; model coercion is not evidence that a claim is true.

The M02 report will name executed tests and exact artifacts. This ADR does not
claim migration execution, policy enforcement, queries or a production API.
