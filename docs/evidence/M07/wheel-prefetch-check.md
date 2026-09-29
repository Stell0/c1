# M07 history-prefetch wheel check

Built the current source tree offline without installing or resolving new
dependencies. Earlier wheel evidence remains in `wheel-history-*`.

- Exact command: `UV_OFFLINE=1 UV_CACHE_DIR=.uv-cache uv build --wheel`
- Exit: 0; [build log](wheel-prefetch-build.log)
- Artifact: `dist/c1-0.0.0.dev0-py3-none-any.whl`
- ZIP entries: 117
- SHA-256: `041d1e060768ac685babeeae857dbdfc1f19fa60f915d2e1dccee42b19794741`

The archive contains 12 `c1/context/` files, the graph-context profile, 3 topics
and 3 batteries profile assets, `c1/changes/storage.py`, and 4 `c1/storage/`
files. The archive check found no environment, evidence, cache, or Python cache
paths. `uv build` warned that `.uv-cache` is inside the source directory; no
cache entries were present in the inspected wheel.
