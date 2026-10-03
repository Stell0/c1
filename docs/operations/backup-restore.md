# Backup and restore

## What a backup contains

`c1-admin backup` takes a **quiesced** backup: it stops the C1 container (the only writer), records the database heads, stops TerminusDB briefly to export its storage volume, dumps the `openfga` and `keycloak` PostgreSQL databases, writes `manifest.json` with SHA-256 checksums, and restarts the services. The backends other than TerminusDB stay up; C1 serves nothing during the backup (measured duration in [limits.md](limits.md)).

```sh
uv run --locked c1-admin backup --to /backups/c1-2026-10-04            # full
uv run --locked c1-admin backup --to /backups/c1-k --knowledge-only    # TerminusDB storage only
```

| File | Content |
|---|---|
| `terminusdb-storage.tar` | The whole TerminusDB storage: knowledge and workflow (journal) databases with full history |
| `openfga.pgdump` | Current memberships, instance grants and binding tuples |
| `keycloak.pgdump` | Realm, clients, users and password hashes |
| `manifest.json` | Heads, profile versions, OpenFGA store and model, checksums |

Backups are secret-bearing (journal, tuples, password hashes): they are written mode 0600 in a mode-0700 directory. Store them encrypted and access-controlled. The `secrets/` directory is **not** included; back it up separately.

A backup refuses to start while a security operation is pending.

Why not `terminusdb bundle`: in TerminusDB 12.0.7 a bundle references layers that exist only on the server that made it, so it cannot be restored into another server (M13 W1 finding). The storage volume is complete and portable.

## Knowledge-only restore

Use it to return the knowledge graph to an earlier state while keeping today's access policy.

```sh
uv run --locked c1-admin restore-knowledge --from /backups/c1-k
```

1. Verifies the manifest and checksums, stops C1, and refuses while a security operation is pending.
2. Refuses if a profile was installed after the backup, or a profile version differs (reinstall such profiles through a reviewed ChangeSet after restoring an older compatible backup).
3. Saves a safety copy of the current TerminusDB storage next to the backup.
4. Starts a temporary, unpublished TerminusDB from the backup storage on the backend network, replaces the live knowledge database with a clone of it (full history, same commit identifiers), and removes the temporary server.
5. Appends a `Restore` record (manifest checksum, previous and restored heads, operator) to the journal and restarts C1.

The journal and OpenFGA are **not** restored. Therefore resources that were re-scoped, revoked or tombstoned after the backup stay governed by their current bindings; resources created after the backup lose their records but their bindings remain, so they answer 404; ChangeSets applied after the backup keep their audit records; and drafts prepared on a newer head are refused as stale. This is an operational storage restore; to undo individual knowledge changes, prefer a reviewed compensating ChangeSet (`restores_from_revision`).

## Full disaster recovery

Restore into a **new, isolated** deployment; never over the primary.

```sh
uv run --locked c1-admin restore-full --from /backups/c1-2026-10-04 \
    --target-dir /srv/c1-dr --target-project c1-dr --target-net-prefix 10.89.252 --target-port 18444
uv run --locked c1-admin dr verify  --dir /srv/c1-dr --project c1-dr --net-prefix 10.89.252
uv run --locked c1-admin dr release --dir /srv/c1-dr --project c1-dr --net-prefix 10.89.252 \
    --port 18444 --accept-security-as-of 2026-10-04T08:00:00+00:00 --reason "incident 42"
```

1. `restore-full` creates the target from the reference files and your secret files, imports the TerminusDB storage, restores both PostgreSQL databases, checks that the restored heads match the manifest, writes a **restore guard** into the journal, and starts C1 without the proxy. While the guard is unreleased, C1 answers 503 to every request.
2. `dr verify` reconciles any pending security operation, compares every journal binding with OpenFGA, and records the result in the guard. It fails on any mismatch.
3. Before releasing, apply every revocation made after the backup time (memberships live only in OpenFGA, so C1 cannot know about later revocations). The restored grants are the backup's grants.
4. `dr release` requires a passing verification and a fresh passing comparison, records your explicit `--accept-security-as-of` time and reason, restarts C1 and starts the proxy.

An old security backup is never treated as current silently: until an operator records that acceptance, the restored deployment serves nothing.
