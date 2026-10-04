# C1 retrieval and storage benchmark

The benchmark measures one C1 release candidate as deployed: the M13 reference
deployment over TLS, production Keycloak and the public API only. It reports five
separate score families. **There is no aggregate score.** Fidelity and security are
pass/fail families: any loss or any differing observation is a hard failure,
whatever the other numbers say.

Plan: [M14.md](../milestones/M14.md). Results and the baseline: [M14 report](../milestones/M14-report.md).

## Run

```sh
# A fresh reference deployment per scale; it is torn down afterwards (needs the C1 image).
C1_REFERENCE=1 uv run --locked python -m benchmark run --scale S --scale M --out docs/evidence/M14

# The same run as the M14-T01..T06 integration tests (used for the gate).
C1_REFERENCE=1 C1_BENCH_SCALES=S,M uv run --locked pytest -q tests/integration/m14

# Baseline from results files, and comparison against it.
uv run --locked python -m benchmark baseline --results docs/evidence/M14/results-S.json \
    --results docs/evidence/M14/results-M.json --out benchmark/baselines/v1-makako.json
uv run --locked python -m benchmark compare --baseline benchmark/baselines/v1-makako.json \
    --results docs/evidence/M14/results-S.json
```

AI provider variables must be unset. No model, embedding or provider account is used.

## Corpus `bench-v1`

`benchmark/corpus.py` generates every record from `seed=14` and a scale factor. The
same seed and scale always give byte-identical records and gold data, and the
digests are recorded in `corpus-manifest-<scale>.json`.

Each unit of scale contains:
- 4 companies with keywords and an alias;
- 8 products per company, each with one battery and three battery versions;
- a capacity measurement on the first version, with evidence, an import activity, a unit and conditions; every third product also has a second, conflicting capacity from another source;
- 24 people with one or two `worksFor` employments, whose `validDuring` intervals have year-only, unknown and exact bounds;
- 6 documents with 6 ordered parts.

Records are spread over four scopes:
- `bench-public` and `bench-team` are readable by the tested principal (alice);
- `bench-legal` is not readable by alice;
- `bench-hidden` is used only by the security family.

The reviewer (carol) reads all four. Records load through ordinary ChangeSets of at
most 200 operations: erin authors, carol approves and applies. A measurement and its
evidence always stay in one ChangeSet.

| Scale | Factor | Records | Visible to alice | Information needs |
|---|---|---|---|---|
| S | 1 | 932 | 854 | 53 |
| M | 3 | 2,792 | 2,558 | 53 |

## Gold data

Every query is an information need whose gold set is computed from the generator's
own structures, restricted to what the tested principal may read, and written to
`gold-<scale>.json` before any request is made. No gold item comes from C1 output.

| Family | Request | Gold |
|---|---|---|
| keyword | `/v1/entities?keywords_any`/`keywords_all` | entities carrying the exact keyword(s) |
| alias | `/v1/entities?alias` | the entity with that alias |
| label-prefix | `/v1/entities?label&label_mode=prefix` | entities whose label starts with the prefix |
| valid-at | `/v1/assertions?predicate=worksFor&object&valid_at[&include_unknown]` | employments holding at the instant: closed–open intervals; an unknown bound is indeterminate and matches only with `include_unknown` |
| document | `/v1/documents?text_contains` | the document whose readable part contains the token |
| graph | three strategies, below | the battery versions reachable through company → product → battery → version |
| context | `POST /v1/context` (`graph-context`) at 8, 32 and 64 KiB | the capacity claims of the company's readable first versions |

Graph needs run three existing deterministic strategies:
- **keyword-only:** `keywords_any=battery`;
- **neighborhood:** depth 3 over the three declared predicates, keeping the returned nodes typed `BatteryVersion` in C1's order;
- **graph-context:** the orientation paths of a 64 KiB package.

## Score families

1. **Storage fidelity (T01).** Every record is read back by its ID as carol and compared property by property with the submitted record, as multisets of typed values. Also checked:
   - every declared conflict keeps both claims (`competing_for`);
   - every document returns its parts in order with identical text digests;
   - the full export (entities, assertions, sources and evidence: the `/v1/export` scope), imported page by page with `import_jsonld`, yields identical identities.

   Score = exact records / records. Properties that the server adds are reported, not counted as loss.
2. **Retrieval quality (T02).** Per need, then macro-averaged per family and strategy:
   - Recall, Precision and nDCG (log2 discount) at K = 5, 10 and 50, and MRR, with binary relevance;
   - for graph-context, path recall: the share of gold node paths present in the orientation paths;
   - for context needs, coverage of the required claims on the first page, over all continuation pages, and the pages needed to reach full coverage.

   C1's order is not a relevance ranking, and the numbers record that order as it is. In the keyword, alias, valid-at and document families, any set difference from the gold data is a correctness defect.
3. **Security invariance (T03).** All observations of alice are fingerprinted after removing only revision tokens, cursors, `generated_at` and request IDs. An observation is the full response pages: items, counts, explanations, paths, context Markdown and structure.

   The harness then adds 98 `bench-hidden` resources (at S) designed to match every need:
   - the same keywords, aliases and label prefixes;
   - hidden products, batteries and versions under visible companies;
   - hidden edges between visible nodes;
   - competing hidden capacities on visible versions;
   - hidden employments of visible people;
   - hidden parts inside visible documents that contain the queried tokens.

   It repeats the run, replaces the hidden records with changed labels, values and text, and runs again. Score = identical observations / observations. Anything below 1.0 fails.
4. **Revocation (T04).** alice's `bench-team` reader role is revoked, and every need is rerun at head and at the pre-revocation revision. No team resource ID or team text may appear in any response. The role is then granted again, and every observation must match the baseline.
5. **Performance (T05).** Measured on the host the run used:
   - corpus load time, and TerminusDB storage before and after loading (`du` of the storage volume);
   - median, p90 and maximum latency over 5 repeats of every need, per family and strategy;
   - context build time per budget;
   - OpenFGA requests per query, counted from the OpenFGA log;
   - C1's cgroup `memory.peak`.

   These are measurements on that host, not scalability claims.

**Configurations (T06).** `benchmark/configurations.py` registers four configurations:
- `deterministic` runs;
- `semantic-seeds`, `semantic-plus-gate` and `hybrid-plus-gate-plus-graph` are reported `NOT_AVAILABLE` with their reason, because those optional components (M15–M18) are not implemented.

## Comparison

`compare` classifies a results file against the baseline for the same corpus scale:
- **hard failure:** fidelity below 1.0, security below 1.0, or a revocation leak;
- **change:** any quality metric that differs from the baseline, listed as higher or lower for review, never accepted silently;
- **performance warning:** a family's median above 1.5× the baseline, compared only on the same host.

If the corpus or gold digests differ, quality results are flagged as not comparable.

The baseline (`benchmark/baselines/v1-makako.json`) stores:
- the corpus and gold digests;
- the C1 revision and the host;
- fidelity and security scores and the revocation result;
- the quality families;
- performance medians.

It changes only through an explicit, reported `baseline` run.
