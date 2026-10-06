"""M14b-T04: indexed history versus TerminusDB history (run inside the C1 container)."""

import asyncio
import json
import random
import time

from c1.authorization.journal import Journal
from c1.changes.history import HistoryService
from c1.changes.profiles import detect_installed_registry
from c1.config import Settings
from c1.runtime import storage_config
from c1.storage.terminus import Terminus


async def main() -> None:
    s = Settings.from_env()
    async with Terminus(storage_config(s)) as k, Journal(storage_config(s, workflow=True)) as j:
        reg = await detect_installed_registry(k)
        svc = HistoryService(k, None, j, reg)  # type: ignore[arg-type]  # no authorization
        ids = sorted({b["resource_id"] for b in await j.list("Binding")})
        random.Random(14).shuffle(ids)
        same = differ = fallback = 0
        t_idx = t_back = 0.0
        examples = []
        for rid in ids[: int(__import__("os").environ.get("C1_HISTORY_SAMPLE", "60"))]:
            t = time.perf_counter()
            idx = await svc._indexed_history(rid)
            t_idx += time.perf_counter() - t
            if idx is None:
                fallback += 1
                continue
            t = time.perf_counter()
            back = []
            for doc in svc._document_ids(rid):
                if await k.get(doc) is not None:
                    back.extend(await k.history(doc))
            t_back += time.perf_counter() - t
            a = [(e["identifier"], e["timestamp"], e["message"]) for e in idx]
            b = [(e["identifier"], e["timestamp"], e["message"]) for e in back]
            if a == b:
                same += 1
            else:
                differ += 1
                examples.append((rid, [x[0] for x in a], [x[0] for x in b]))
        print(
            json.dumps(
                {
                    "compared": same + differ,
                    "identical": same,
                    "different": differ,
                    "fallback": fallback,
                    "indexed_s": round(t_idx, 2),
                    "backend_s": round(t_back, 2),
                    "examples": examples[:3],
                }
            )
        )


asyncio.run(main())
