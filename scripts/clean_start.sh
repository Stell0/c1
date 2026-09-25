#!/usr/bin/env bash
# Clone and check HEAD, or a disposable Git snapshot of uncommitted development work.
set -euo pipefail
repo_root=$(git -C "$(dirname "$0")/.." rev-parse --show-toplevel)
mode=${1:-}
if [[ $# -gt 1 || ( -n "$mode" && "$mode" != "--worktree" ) ]]; then
    echo 'Usage: scripts/clean_start.sh [--worktree]' >&2
    exit 2
fi
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT
unset OPENAI_API_KEY ANTHROPIC_API_KEY GEMINI_API_KEY GOOGLE_API_KEY HF_TOKEN AZURE_OPENAI_API_KEY
unset C1_HARNESS_CANARY_FAIL VIRTUAL_ENV PYTHONPATH UV_PROJECT_ENVIRONMENT
# Do not reuse the checkout's environment, installation or mutable cache.
export UV_CACHE_DIR="$scratch/uv-cache"
export UV_PYTHON_INSTALL_DIR="$scratch/uv-python"
export UV_PYTHON_BIN_DIR="$scratch/uv-python/bin"
clone_source="$repo_root"
if [[ "$mode" == "--worktree" ]]; then
    mkdir "$scratch/snapshot"
    git -C "$repo_root" ls-files -z --cached --others --exclude-standard |
        python3 -c '
import pathlib, shutil, sys
source, destination = map(pathlib.Path, sys.argv[1:])
for name in sorted(set(sys.stdin.buffer.read().split(b"\0")) - {b""}):
    relative = pathlib.Path(name.decode())
    path = source / relative
    if path.is_symlink():
        raise SystemExit(f"Snapshot refuses symlink: {relative}")
    if path.is_file():
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
' "$repo_root" "$scratch/snapshot"
    git -C "$scratch/snapshot" init -q
    git -C "$scratch/snapshot" add .
    git -C "$scratch/snapshot" -c user.name='C1 local check' \
        -c user.email='c1-check@example.invalid' -c commit.gpgsign=false \
        commit -qm 'Disposable M00 verification snapshot'
    clone_source="$scratch/snapshot"
    echo 'Mode: disposable working-tree snapshot; source repository is not committed.'
elif [[ -n "$(git -C "$repo_root" status --porcelain --untracked-files=normal)" ]]; then
    echo 'Clean checkout required; use --worktree for a disposable pre-commit snapshot.' >&2
    exit 2
fi
git clone --quiet --no-local "$clone_source" "$scratch/checkout"
cd "$scratch/checkout"
echo "Checking cloned tree $(git rev-parse HEAD^{tree})"
make bootstrap check
