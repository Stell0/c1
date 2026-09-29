# M07 guarded-probe wheel and implementation-input inventory

The separate guarded-probe input manifest was generated from
`git ls-files -co --exclude-standard -z`, filtering the sorted, deduplicated
paths to `src/`, `scripts/`, `tests/`, `profiles/`, `fixtures/`, `probes/`,
`deployment/`, plus `Makefile`, `pyproject.toml`, `uv.lock`, `compose.yaml`,
and `.secrets.baseline`. The manifest has 344 entries. Regular files are
hashed as bytes; symlinks are hashed as the byte representation of their link
text. This excludes ignored caches and keeps earlier manifests unchanged.

The manifest generator is reproducible with:

```sh
python3 - <<'PY'
from hashlib import sha256
from pathlib import Path
import os
import subprocess

repo = Path.cwd()
listed = subprocess.run(
    ["git", "ls-files", "-co", "--exclude-standard", "-z"],
    check=True,
    stdout=subprocess.PIPE,
).stdout
paths = {entry.decode() for entry in listed.split(b"\0") if entry}
roots = ("src/", "scripts/", "tests/", "profiles/", "fixtures/", "probes/", "deployment/")
exact = {"Makefile", "pyproject.toml", "uv.lock", "compose.yaml", ".secrets.baseline"}
selected = sorted(path for path in paths if path in exact or path.startswith(roots))
output = Path("docs/evidence/M07/implementation-files-guarded-probe.sha256")
with output.open("w", encoding="utf-8", newline="\n") as stream:
    for name in selected:
        path = repo / name
        data = os.fsencode(os.readlink(path)) if path.is_symlink() else path.read_bytes()
        stream.write(f"{sha256(data).hexdigest()}  {name}\n")
print(f"manifest={output} count={len(selected)}")
PY
```

The current source tree wheel was rebuilt offline.

- Exact command: `UV_OFFLINE=1 UV_CACHE_DIR=.uv-cache uv build --wheel`
- Exit: 0; [build log](wheel-guarded-build.log)
- Artifact: `dist/c1-0.0.0.dev0-py3-none-any.whl`
- ZIP entries: 117
- SHA-256: `cdcf2ae8eb668769bc429c539892c161502e239b9ce1b0d60ea5937677c4c5e4`

The archive contains 12 `c1/context/` files, the graph-context profile, three
topics and three batteries profile assets, `c1/changes/storage.py`, and four
`c1/storage/` files. No environment, evidence, cache, or Python cache paths
were present. `uv build` warned that `.uv-cache` is inside the source tree;
inspection found no cache paths in the wheel.
