# C1 core vocabulary 1.0.0

Namespace: `urn:c1:ns:core#`. This URN identifies terms; it is not a retrieval URL.
The pinned [context](context.jsonld), [manifest](profile.json), and
[SHACL shapes](shapes.ttl) define the supported interchange profile. The
[RDFS declarations](vocabulary.ttl) publish class and property identities,
including `c1:Assertion rdfs:subClassOf rdf:Statement`. They are not loaded
into instance data or used for inference. The
manifest is the declared vocabulary; application code must not treat this
document as an executable rule source.

C1 reuses RDF 1.1, RDFS, SKOS, Dublin Core Terms, PROV-O, Web Annotation,
OWL-Time, and XML Schema. An Assertion is a named `rdf:Statement`-style
resource with `rdf:subject`, `rdf:predicate`, and `rdf:object`; its
independent ID, provenance, and lifecycle distinguish it from a direct edge.
The profile uses `skos:prefLabel` and `skos:altLabel` for entity labels,
`dcterms:title/identifier/issued/creator/description` for source metadata,
`prov:Activity/Agent/wasGeneratedBy/wasAttributedTo/used/startedAtTime/endedAtTime`
for provenance, `oa:hasSource/hasSelector/exact/start/end` for evidence
selection, and `time:hasBeginning/hasEnd/inXSD*` for world-valid intervals.
`time:inXSDDateTime` is deprecated in OWL-Time but remains necessary to
preserve an `xsd:dateTime` without a timezone; `time:inXSDDateTimeStamp`
would imply a timezone and alter the source's precision. `rdf:value` is the
general literal predicate in datatype round-trip fixtures.

Every C1 term below fills a concept or qualifier those vocabularies do not
specify at the needed granularity. No C1 term grants authorization.

| Term | Definition | Why an existing term does not suffice |
|---|---|---|
| `Entity` | Stable identity for a real-world or conceptual thing. | `prov:Entity` describes provenance objects, not canonical identity and alias resolution. |
| `Assertion` | Independently identified, attributable claim about one subject, predicate, and object. | `rdf:Statement` alone lacks the C1 claim lifecycle and review contract. |
| `Source` | Identified source material carrying claim evidence. | `dcterms:Source` is a property, not this resource type with immutable version metadata. |
| `Evidence` | Link from a claim to one specific source version and selector. | Web Annotation models the selector but not the C1 claim-to-version obligation. |
| `Document` | Stable textual document identity. | `dcterms:BibliographicResource` does not specify C1 versioned parts. |
| `DocumentPart` | Independently identified, ordered part of a document. | `dcterms:hasPart` does not identify an independently bound part or its order. |
| `ResolutionRecord` | Reviewed identity or alias decision with candidates and rationale. | `prov:Activity` is an activity, not the durable decision record. |
| `SchemaProfile` | Installed profile name and version. | Ontology version terms do not identify the installed schema state of this repository. |
| `ChangeSet` | Proposed knowledge operations at a base revision. | `prov:Activity` represents performed work, not a mutable proposal. |
| `ValidationReport` | Structural validation outcome for a ChangeSet. | SHACL reports do not express the full C1 proposal/revision relation. |
| `ReviewDecision` | Actor's recorded decision on a ChangeSet. | `prov:wasAttributedTo` alone does not express the decision. |
| `ApplyReceipt` | Applied ChangeSet's durable knowledge commit identity. | PROV generation does not encode C1 idempotency receipt semantics. |
| `Keyword` | Named explicit keyword with original and normalized spellings. | SKOS concepts imply a controlled concept scheme; explicit exact keywords need no scheme. |
| `TimeBoundary` | Named known, unknown, or unbounded temporal endpoint. | OWL-Time has instants but no unknown-versus-unbounded marker. |
| `TimeInterval` | Named C1 half-open world-valid interval. | `time:Interval` has no half-open convention. |
| `Selector` | Named selector detail for evidence. | Web Annotation selector classes do not cover the supported C1 selector-kind discriminator. |
| `assertionRef` | Evidence's assertion identity. | `oa:hasTarget` would imply an annotation target with broader annotation semantics. |
| `applyReceipt` | ChangeSet's optional application receipt reference. | PROV generation does not bind a proposal to its durable apply receipt. |
| `baseRevision` | Knowledge head against which a proposal was made. | PROV revision relationships do not encode optimistic concurrency. |
| `boundaryState` | Endpoint state `known`, `unknown`, or `unbounded`. | OWL-Time cannot distinguish absent knowledge from an open interval. |
| `candidate` | Candidate identity in a resolution decision. | SKOS matching predicates imply a decided correspondence. |
| `changeSet` | Workflow record's associated proposal. | PROV activity relations do not identify a pending proposal. |
| `confidence` | Producer's attributed, potentially uncalibrated confidence value. | No reused term conveys C1's separation from review or truth. |
| `confidenceMethod` | Attribution or calibration method for confidence. | A bare confidence number hides its interpretation. |
| `contentDigest` | Digest of immutable source/document content. | `dcterms:identifier` does not state digest semantics. |
| `decision` | Review or resolution decision value. | PROV association does not give a decision state. |
| `diagnostic` | Structural validation finding attached to a report. | SHACL reports do not cover the full ChangeSet validation contract. |
| `evidence` | Assertion's independently identified evidence links. | `prov:wasDerivedFrom` does not require source-version selectors. |
| `excerpt` | Stored selected source text. | `oa:exact` belongs to a selector and may differ from a curated excerpt. |
| `keyword` | Entity's explicit Keyword nodes. | `dcterms:subject` would conflate tags with controlled topics. |
| `keywordLanguage` | Optional BCP 47 tag for the original keyword. | Literal language tags cannot attach to a named normalization record. |
| `keywordText` | Exact original keyword spelling. | `rdfs:label` would conflate search tags with display labels. |
| `knowledgeCommit` | Knowledge revision in an apply receipt. | `prov:generatedAtTime` is a time, not an opaque revision. |
| `intendedCreationScope` | Proposed resource creation scope annotation. | Security bindings are current external state; this records intent only. |
| `lifecycle` | Content state independent of review and origin. | `prov:invalidatedAtTime` cannot express active/superseded states. |
| `manualStatement` | Attribution that no external source supports this statement. | PROV attribution alone does not disclose that evidence is intentionally absent. |
| `method` | Producer activity method. | `prov:hadPlan` presumes a separately modeled plan resource. |
| `normalizationVersion` | Rule version used for keyword normalization. | SKOS labeling has no normalization algorithm version. |
| `normalizedKeyword` | Deterministic exact-match key. | SKOS labels retain source spelling and do not define C1 matching. |
| `observedAt` | Time source/evidence content was observed. | `dcterms:issued` is publication, not observation. |
| `outcome` | Activity outcome reported by its producer. | PROV Activity does not assign a standard result-state property. |
| `output` | Resources produced by an activity. | `prov:generated` is broader and does not capture the C1 listed output contract. |
| `orderKey` | Deterministic document-part ordering token. | `dcterms:hasPart` has no order. |
| `origin` | Claim's imported/manual/derived origin. | PROV lineage alone does not classify this C1 state. |
| `partKind` | Structural role of a document part. | Dublin Core type is too broad for part roles. |
| `partOfDocument` | Parent document identity for a part. | `dcterms:isPartOf` does not prescribe the independent C1 part contract. |
| `profileName` | Installed profile identifier. | Ontology metadata does not name the active repository profile. |
| `profileVersion` | Installed profile semantic version. | `owl:versionInfo` refers to an ontology, not repository profile state. |
| `projectReference` | Optional organizational project association. | `dcterms:isPartOf` might imply a content partition; project is only organizational. |
| `proposedEvidence` | Evidence referenced by a proposed ChangeSet. | PROV use implies a performed activity; the proposal may never apply. |
| `proposedOperation` | Serialized ChangeSet operation payload. | PROV activity cannot represent unapplied edits. |
| `provisionedScopeHint` | Historical scope annotation, never an authorization input. | No RDF provenance term means current policy binding; that is separate security state. |
| `rationale` | Human reason for a decision. | `dcterms:description` would not identify decision rationale specifically. |
| `reviewDecision` | ChangeSet's optional review decision reference. | PROV association alone does not identify an approval decision. |
| `requestDigest` | Digest binding an idempotent proposal or receipt. | `dcterms:identifier` does not carry request-binding semantics. |
| `resultRevision` | Knowledge revision reported for an activity outcome. | `prov:generatedAtTime` is not a repository revision. |
| `revenue` | Example declared economic relationship predicate. | Generic `rdf:value` would omit what the amount measures. |
| `reviewState` | Policy review outcome independent of claim truth. | PROV attribution does not imply review. |
| `selectorKind` | Which supported selector representation a named selector uses. | Web Annotation has selector classes but no C1 profile discriminator. |
| `sourceKind` | Source's material category. | `dcterms:type` has no fixed C1 source categorization. |
| `sourceRevision` | Immutable revision identifier of source material. | `dcterms:hasVersion` relates resources but does not carry an opaque revision token. |
| `status` | Workflow record state. | PROV event times do not encode proposal validation or application states. |
| `targetResource` | Resource ID affected by a proposed ChangeSet. | PROV affected-resource relations refer to events that have happened. |
| `text` | Document part's textual content. | `rdf:value` would not distinguish content from typed property value. |
| `toolName` | Producing tool identifier. | PROV Agent may identify an agent, but not the tool release used in an activity. |
| `toolVersion` | Producing tool version. | `owl:versionInfo` is about ontology versions. |
| `validDuring` | Assertion's modeled-world validity interval. | PROV generation time is recording/production, not world-valid time. |
| `validationReport` | ChangeSet's optional validation report reference. | SHACL reports alone do not represent C1's proposal validation result. |
| `worksFor` | Example declared employment relationship predicate. | `org:memberOf` does not precisely represent employment and would imply membership. |
