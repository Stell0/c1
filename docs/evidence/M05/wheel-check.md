# M05 wheel profile check

`UV_CACHE_DIR=.uv-cache uv build --wheel --offline --out-dir /tmp/c1-m05-wheel`
exited 0 on 2026-09-27. The resulting `c1-0.0.0.dev0-py3-none-any.whl`
contains `profile.json`, `context.jsonld`, and `shapes.ttl` for each new
`profiles/available/identity/` and `profiles/available/directory/` catalog.
The output wheel is disposable and is not committed.
