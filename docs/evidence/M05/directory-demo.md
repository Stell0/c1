# M05 directory demonstration

On 2026-09-27, with the pinned local stack healthy, these commands exited 0:

```sh
uv run --locked python scripts/load_fixture.py --fixture directory --database c1_m03_dev_knowledge
uv run --locked python scripts/demo_m05.py
```

The loader returned `{"fixture":"directory","state":"applied"}` after a
service-authored ChangeSet was independently reviewed and applied. The demo
returned the same Person ID for Alice, Bob, Carol, and Dave:
`urn:c1:instance:dev:entity/00000013-0000-4000-8000-000000000000`.
Their readable assertion counts were respectively **3**, **2**, **5**, and
**2**. The console's synthetic audit IDs are omitted here; no token or
credential was recorded.

The loader requires a fresh local fixture state for another full run. The
integration tests use isolated databases and stores, so their result does not
depend on this persistent demonstration database.
