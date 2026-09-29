#!/usr/bin/env bash
# One-time generation of the checked-in SCIP JSON indexes (M08 D12).
#
# Tests and demonstrations read only fixtures/software-integration/scip/*.json.
# This script is run by a maintainer when snapshot sources change. It needs
# network access once to install the pinned tools:
#   - scip-python 0.6.6 (MIT) through the checked-in package-lock.json
#   - scip CLI v0.10.0 (Apache-2.0) release binary, verified by SHA-256
set -euo pipefail

here=$(cd "$(dirname "$0")/.." && pwd)
tools=$here/tools
out=$here/scip
scip_sha256=eeb28ebbff443c01609fb1691809958f3f0c7a8651af689a5bc8560061cd8ab0
scip_url=https://github.com/scip-code/scip/releases/download/v0.10.0/scip-linux-amd64.tar.gz

npm ci --prefix "$tools" --no-audit --no-fund --ignore-scripts
mkdir -p "$tools/bin"
if [[ ! -x "$tools/bin/scip" ]]; then
  curl -sSL -o "$tools/bin/scip-linux-amd64.tar.gz" "$scip_url"
  echo "$scip_sha256  $tools/bin/scip-linux-amd64.tar.gz" | sha256sum -c -
  tar -xzf "$tools/bin/scip-linux-amd64.tar.gz" -C "$tools/bin" scip
fi
[[ "$("$tools/bin/scip" --version)" == "scip version v0.10.0" ]]

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
# An empty environment stops scip-python from invoking pip.
echo '[]' > "$work/environment.json"
mkdir -p "$out"

for spec in ledger:a1 ledger:a2 shop:b1 shop:b2; do
  repo=${spec%%:*}
  snapshot=${spec##*:}
  rm -rf "$work/$repo"
  cp -r "$here/repos/$repo/$snapshot" "$work/$repo"
  (cd "$work/$repo" && node "$tools/node_modules/.bin/scip-python" index \
      --project-name "$repo" --project-version "$snapshot" \
      --environment "$work/environment.json" --output "$work/$snapshot.scip" . >/dev/null)
  "$tools/bin/scip" print --json "$work/$snapshot.scip" > "$work/$snapshot.raw.json"
  python3 - "$work/$snapshot.raw.json" "$out/$snapshot.json" "$repo" <<'PY'
import json
import sys

source, target, repo = sys.argv[1:]
index = json.loads(open(source, encoding="utf-8").read())
# The indexer records the generating host's absolute path; replace it with a
# fixed, documented fixture root so no host detail is checked in.
index["metadata"]["project_root"] = f"file:///fixture/{repo}"
index["documents"].sort(key=lambda item: item["relative_path"])
with open(target, "w", encoding="utf-8") as stream:
    json.dump(index, stream, indent=1, sort_keys=True, ensure_ascii=False)
    stream.write("\n")
PY
done

python3 - "$here" <<'PY'
import hashlib
import json
import pathlib
import sys

here = pathlib.Path(sys.argv[1])
def digest(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def tree_digest(root: pathlib.Path) -> str:
    entries = sorted(p for p in root.rglob("*") if p.is_file())
    payload = "".join(f"{p.relative_to(root).as_posix()}\0{digest(p)}\n" for p in entries)
    return hashlib.sha256(payload.encode()).hexdigest()

provenance = {
    "generator": "fixtures/software-integration/tools/generate_scip.sh",
    "tools": {
        "scip-python": {"version": "0.6.6", "license": "MIT", "lockfile_sha256": digest(here / "tools/package-lock.json")},
        "scip": {"version": "v0.10.0", "license": "Apache-2.0", "release_sha256": "eeb28ebbff443c01609fb1691809958f3f0c7a8651af689a5bc8560061cd8ab0"},
    },
    "command": "scip-python index --project-name <repo> --project-version <snapshot> --environment <empty> ; scip print --json",
    "normalization": "metadata.project_root replaced by file:///fixture/<repo>; documents sorted by relative_path; JSON pretty-printed with sorted keys",
    "snapshots": {
        snap: {
            "repository": repo,
            "source_tree_sha256": tree_digest(here / "repos" / repo / snap),
            "index_sha256": digest(here / "scip" / f"{snap}.json"),
        }
        for repo, snap in (("ledger", "a1"), ("ledger", "a2"), ("shop", "b1"), ("shop", "b2"))
    },
}
(here / "scip/PROVENANCE.json").write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n")
PY
echo "SCIP indexes regenerated in $out"
