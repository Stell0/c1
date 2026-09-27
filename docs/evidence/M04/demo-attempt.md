# M04 demo attempt

Command: `UV_CACHE_DIR=/tmp/c1-uv-cache uv run --locked python -m scripts.demo_m04`

The first sandboxed attempt exited 1 because loopback services were inaccessible
from that sandbox. A second attempt with approved loopback access exited 1 after
the ChangeSet applied: the authorized history request failed with
`C1-ST-003`, because the pinned backend returned a timestamp shape the M04
history parser did not yet accept. The history owner is correcting that parser.
No result is claimed until the demo is rerun successfully. The raw traceback
and audit stream are excluded from this evidence file.

The corrected run is recorded in [demo-verify.md](demo-verify.md).
