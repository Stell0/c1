# M04 wheel check

`UV_CACHE_DIR=.uv-cache uv build --wheel --out-dir /tmp/c1-m04-wheel` exited 0.
The resulting `c1-0.0.0.dev0-py3-none-any.whl` contains the `profile.json`,
`context.jsonld`, and `shapes.ttl` files for both trusted catalog aliases:
`example-vehicle` and `example-vehicle-v2-incompatible`. The wheel has 69
entries. The build used the pinned `hatchling==1.27.0` backend and emitted only
the known in-repository uv cache warning.
