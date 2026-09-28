# M06 pre-alias implementation input snapshot

- Starting HEAD: `29ddc193cd28ff777b62daf21caea35e0b83f6d5`
- Manifest: [`pre-alias-implementation-files.sha256`](pre-alias-implementation-files.sha256)
- Input count: 269 files
- Ordering: ascending repository-relative POSIX path
- Scope: tracked and nonignored files from `src/`, `scripts/`, `tests/`, `profiles/`, `fixtures/`, `probes/`, and `deployment/`, plus `Makefile`, `pyproject.toml`, `uv.lock`, and root `compose.yaml` if present.
- Environment exclusion: basenames beginning `.env` or ending `.env` are excluded. `git ls-files -co --exclude-standard` excludes standard ignored files before filtering. No environment file was opened or hashed.
- Symlinks: the digest is over the stored link target text, not the target contents.
- Reproduction command (run from repository root):

```sh
python3 - > docs/evidence/M06/pre-alias-implementation-files.sha256 <<'PY'
import hashlib
import os
import subprocess
from pathlib import Path, PurePosixPath

raw = subprocess.check_output(["git", "ls-files", "-co", "--exclude-standard", "-z"])
paths = sorted(set(os.fsdecode(item) for item in raw.split(b"\0") if item))
roots = {"src", "scripts", "tests", "profiles", "fixtures", "probes", "deployment"}
exact = {"Makefile", "pyproject.toml", "uv.lock", "compose.yaml"}
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

Gate state: INTERRUPTED before the suffix-ending Document IRI alias fix. This is retained as the pre-alias input snapshot and does not attest a completed gate.

The command prints only SHA-256 digests and repository-relative paths. The manifest binds inputs at the interrupted pre-alias run; use the current implementation snapshot for corrected gate inputs.
