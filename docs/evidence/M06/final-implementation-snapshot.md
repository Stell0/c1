# M06 final implementation input snapshot

- Snapshot: final corrected inputs for the scoped M05-T04 fresh-token rerun after the combined gate's cached-token failure.
- Starting HEAD: `29ddc193cd28ff777b62daf21caea35e0b83f6d5`
- Manifest: [`final-implementation-files.sha256`](final-implementation-files.sha256)
- Input count: 271 files
- Ordering: ascending repository-relative POSIX path
- Scope: tracked and nonignored files from `src/`, `scripts/`, `tests/`, `profiles/`, `fixtures/`, `probes/`, and `deployment/`, plus `Makefile`, `pyproject.toml`, `uv.lock`, root `compose.yaml` if present, and `.secrets.baseline`.
- Baseline rationale: `.secrets.baseline` is included because the unused synthetic `fga_token` in `tests/unit/m06/test_document_routes.py` triggered a Secret Keyword false positive; the milestone lead audited the mock-token exception into the baseline.
- Input delta versus the combined-run snapshot: only `tests/integration/m05/test_t04_identity_m05.py` changed for the scoped fresh-token test helper; production source inputs are unchanged.
- Environment exclusion: basenames beginning `.env` or ending `.env` are excluded. `git ls-files -co --exclude-standard` excludes standard ignored files before filtering. No environment file was opened or hashed.
- Symlinks: the digest is over the stored link target text, not the target contents.
- Reproduction command (run from repository root):

```sh
python3 - > docs/evidence/M06/final-implementation-files.sha256 <<'PY'
import hashlib
import os
import subprocess
from pathlib import Path, PurePosixPath

raw = subprocess.check_output(["git", "ls-files", "-co", "--exclude-standard", "-z"])
paths = sorted(set(os.fsdecode(item) for item in raw.split(b"\0") if item))
roots = {"src", "scripts", "tests", "profiles", "fixtures", "probes", "deployment"}
exact = {"Makefile", "pyproject.toml", "uv.lock", "compose.yaml", ".secrets.baseline"}
for name in paths:
    p = PurePosixPath(name)
    if name not in exact and (not p.parts or p.parts[0] not in roots):
        continue
    base = p.name.lower()
    if base.startswith(".env") or base.endswith(".env"):
        continue
    path = Path(name)
    content = os.readlink(path).encode() if path.is_symlink() else path.read_bytes()
    print(f"{hashlib.sha256(content).hexdigest()}  {name}")
PY
```

The command prints only SHA-256 digests and repository-relative paths. The combined-run inputs remain in [`implementation-snapshot.md`](implementation-snapshot.md); the interrupted pre-alias run remains separate.
