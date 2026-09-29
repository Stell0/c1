# Synthetic cross-project batteries fixture

All companies, products, quantities, reports, conditions and excerpts here are
synthetic test data. They make no statement about real products.

`build.py` is a pure deterministic fixture constructor. Run
`python fixtures/cross-project-batteries/build.py` to regenerate `fixture.json`
and the batteries profile. The authoritative profile lives in `profile/`;
`profiles/available/batteries/` is its byte-for-byte trusted local catalog copy.
The constructor copies the supported core Entity property templates into each
custom entity class; each record has exactly one registered class.
IDs use deterministic name-derived bytes with UUIDv4 version bits, matching the
canonical storage ID contract. The storage-mapping regression covers every
producer record and the separate security-test mutations.

The ordinary loader installs the topics and batteries profiles as Erin,
independently reviewed by Carol. Papertrader creates the one shared Tesla
identity. Robotelier resolves that visible identity through the exact-label
entity API before submitting its own ordinary ChangeSet. Both producers have
ordinary reader, creator and contributor grants, and Carol separately approves
their submissions. Provenance actor placeholders are bound to the actual
authenticated producer principals by the loader. Explicit external import
activities retain fixed IDs, original Sources and their individual Evidence
outputs; ChangeSet recording activities are separate events.

The assembled datasheet is `document-v2`; its original Source is `source-v1`.
An independently authorized ordinary `dcterms:source` assertion connects them.
The public quote part and hidden appendix are independently authorized.
Capacity qualifiers are ordinary assertions about each claim's Measurement
resource, linked through an ordinary `measurementRef` assertion.
The two M-B3 quantities have the same known valid interval, unit and conditions
(`25 C; nominal discharge`), so they are comparable competing claims under the
declared single-valued capacity rule. Different measurement conditions alone
would not establish a conflict.

Load with `uv run --locked python scripts/load_fixture.py --fixture
cross-project-batteries --database <trusted database>`. The loader refreshes the
same actual producer or reviewer token before every request.
Each schema profile is installed by its own independently reviewed ChangeSet,
using the fresh revision resulting from the previous installation.
If setup stopped before either producer's content applied, add `--resume-setup`
to reuse only matching installed profile versions and active fixture scope IDs
and labels. This mode rejects an already created Tesla fixture identity and
does not delete, replace, or reset stored data.

`expected/` contains reviewed deterministic packages. Regeneration is explicit:
`uv run --locked python scripts/demo_m07.py --write-goldens`. Only knowledge
revision, generation time and request ID are canonicalized. Meaningful resource,
source, evidence and external import activity IDs are preserved.
Golden files are expected templates: authenticated producer subjects are
represented by explicit `urn:c1:fixture:producer:papertrader` and `robotelier`
placeholders and bound to the real trusted fixture producer principals before
comparison. Actual response attribution is retained and compared exactly.
