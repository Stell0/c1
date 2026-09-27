# Current binding index timing

Command: `PYTHONPATH=. uv run --locked python /tmp/c1_m05_index_timing.py` against the configured local development workflow journal.

Result: PASS — 12 bindings, 4 active scopes, 0 pending resources; cold build 351.88 ms, same-head reuse 111.60 ms, cached snapshot identity reused. One sample on this development host; no throughput claim.

Reproduce from the repository root with the local stack running and the configured development journal populated:

```sh
PYTHONPATH=. uv run --locked python /tmp/c1_m05_index_timing.py
```

Save the following as `/tmp/c1_m05_index_timing.py` before running the command:

```python
import asyncio
import os
import time
from probes.config import environment
from c1.authorization.journal import Journal
from c1.config import Settings
from c1.query.index import CurrentBindingIndex
from c1.runtime import storage_config

async def main():
    for key, value in environment().items():
        os.environ.setdefault(key, value)
    settings = Settings.from_env()
    async with Journal(storage_config(settings, workflow=True)) as journal:
        head = await journal.head()
        index = CurrentBindingIndex(journal)
        start = time.perf_counter()
        first = await index.snapshot(head)
        first_ms = (time.perf_counter() - start) * 1000
        start = time.perf_counter()
        second = await index.snapshot(head)
        second_ms = (time.perf_counter() - start) * 1000
        print(f'bindings={len(first.bindings)} active_scopes={len(first.active_scopes)} pending_resources={len(first.pending_resources)}')
        print(f'build_ms={first_ms:.2f} reuse_ms={second_ms:.2f} reused={first is second}')

asyncio.run(main())
```
