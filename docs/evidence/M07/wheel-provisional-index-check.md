# Provisional-index wheel and input manifest

Created a separate sorted 345-entry source-input manifest at
`implementation-files-provisional-index.sha256`. Inputs were discovered with
`git ls-files -co --exclude-standard -z`, deduplicated and filtered to
`src/`, `scripts/`, `tests/`, `profiles/`, `fixtures/`, `probes/`,
`deployment/`, plus `Makefile`, `pyproject.toml`, `uv.lock`, `compose.yaml`,
and `.secrets.baseline`. Regular files were hashed by bytes; symlinks by link
text. Earlier manifests and the main manifest were not changed.

The current wheel was rebuilt offline:

- Exact command: `UV_OFFLINE=1 UV_CACHE_DIR=.uv-cache uv build --wheel`
- Exit: 0; [build log](wheel-provisional-index-build.log)
- Artifact: `dist/c1-0.0.0.dev0-py3-none-any.whl`
- ZIP entries: 117
- SHA-256: `1777fe25920584396d593020e7bb6bc94bc2660eb793d7207b157533cff1d4f3`

Archive path inspection found 12 `c1/context/` entries, the graph-context
profile, three topics assets, three batteries assets, `c1/changes/storage.py`,
and four `c1/storage/` entries. No environment, evidence, cache, or Python
cache paths were present. `uv build` warned that `.uv-cache` is inside the
source tree; inspection found no cache paths in the wheel.
