# External-provider maintenance and recovery

This is the qualified M14c contract for the pinned `0.1.0rc2` artifact and
documented dedicated-backend transport. [M14c evidence](../milestones/M14c-report.md)
records Gate B lifecycle/recovery results and exact pins. Each deployment supervisor
must qualify its own persistence, transport and lifecycle procedures.

## Maintenance and snapshot ownership

Public application commands operate on configured backends without reference
Compose, containers, or IdP administration:

```sh
c1-admin application state
c1-admin application consistency
c1-admin application optimize
```

`optimize` retains heads/history and can run online. State/consistency are
read-only inventories; their output is not a force-ready mechanism.

The supervisor stops the single C1 writer and uses the **same shared lock path**
for exclusive operator work. It handles database shutdown/checkpointing,
snapshot transport, storage import/export, and service lifecycle. C1 does not
manage supervisor infrastructure. Preserve secrets separately from diagnostic
metadata and encrypt/access-control secret-bearing backups.

A full external-provider backup contains knowledge/workflow storage, OpenFGA
persistence, initialization/instance identity, schema/model versions, trusted
namespace metadata, configuration metadata, and checksums. It excludes external
realms/users/password hashes, IdP databases, signing keys, and provider admin
credentials. The initial transport contract uses complete TerminusDB storage
and a custom-format PostgreSQL dump of the OpenFGA database; other persistence
transports require an explicitly qualified versioned contract.

Use dedicated application-owned backend persistence for this transport. Whole
TerminusDB storage/PostgreSQL snapshots can include every database/store in that
backend; a shared service containing other installations requires separately
qualified scoped transport and custody rules before production use.

After quiescing the writer, prepare a new mode-0700 directory with mode-0600
`terminusdb-storage.tar` and `openfga.pgdump` using the supervisor's backup
mechanisms. With the writer still stopped:

```sh
c1-admin application backup-manifest --directory /backups/c1-snapshot \
  --operator deployment-operator
```

This checks actual heads, profiles, pending operations, bindings and restored
guards, copies protected initialization metadata into `initialization.json`,
and writes version-2 `manifest.json` with checksums. It does not perform the
transport or declare arbitrary files a verified restore. A new/empty manifest
path is required. Record the pinned C1/backend versions and supervisor transport
commands; verification requires a real fresh-node restore.

## Guarded restore

1. Keep the target isolated/unpublished and stop its writer. Verify all backup
   files/checksums before importing; restore complete knowledge/workflow and
   OpenFGA persistence using the qualified supervisor transport.
2. Restore the protected initialization file and secret configuration. Preserve
   instance ID/IRI base, exact issuer, issuer alias, namespace identity, audience,
   classification profile, store/model IDs, and client/sector registration.
   Reconcile backend networking through trusted supervisor configuration.
3. With imported services available but the C1 writer stopped, establish the
   guard and validate restored identity/schema/model/consistency:

   ```sh
   c1-admin application restore-validate --directory /backups/c1-snapshot \
     --operator deployment-operator
   ```

   Restarting C1 while this journal guard is unreleased returns 503 for ordinary
   requests. Repeated validation reconciles the same manifest-bound guard;
   multiple different unreleased guards are refused. Do not publish the target.
4. Independently verify that the external identity namespace was preserved and
   that restored subjects still identify the same people. Matching issuer text,
   email, username, or a new signing key is insufficient. Routine key rotation
   does not itself establish namespace migration. Reconcile pairwise-subject
   client/sector registration explicitly.

## Continuity evidence and explicit release

An authorized operator supplies a protected JSON attestation following the
`namespace_evidence` schema from `c1-admin application contract`. It contains
`contract_version=1`, exact `issuer`, `namespace_id`, `instance_id`, `client_id`,
and the original approved `subject`, plus `operator`, `continuity_verified=true`,
numeric UTC `verified_at`, and the SHA-256 of retained independent continuity
evidence. The evidence must come from verified namespace ownership/registration
and subject continuity, not simply repeated issuer text. It expires after one
hour; future times outside clock allowance are refused.

Obtain a fresh, normal user access token for that same identity through the
qualified provider/client contract and supply it in a protected local token
file. It is not an Explorer cookie export or IdP administrator credential.
C1 validates it normally and matches its exact subject to the original approval.
Keep both files private and out of logs/evidence artifacts.

```sh
c1-admin application dr-verify \
  --namespace-evidence /run/private/continuity.json \
  --continuity-token-file /run/private/user-access-token

c1-admin application dr-release \
  --namespace-evidence /run/private/continuity.json \
  --continuity-token-file /run/private/user-access-token \
  --accept-security-as-of SNAPSHOT_CREATED_AT_FROM_MANIFEST \
  --reason incident-reference --operator deployment-operator
```

Verification checks consistency, schema/model compatibility and namespace proof.
Release must occur within five minutes of verification, repeat the identity proof,
match current knowledge head and exact authorization tuple digest, and accept
the exact snapshot time explicitly. A fresh consistency/JWKS check runs before
guard release. Reapply later revocations before verification: C1 cannot infer
grants changed outside the restored snapshot.

Corruption, missing artifacts, incompatible versions, mismatched instance or
identity namespace, stale verification, changed authorization, unavailable IdP,
or an unverified client registration prevents release. Guards remain until a
valid verification and explicit release. Never remap by email/username, silently
restore old grants as current, bypass a guard with a receipt, or promise image
rollback across incompatible data changes.

After release, the supervisor restarts C1, checks live `/v1/readyz`, and only then
publishes routing. Preserve manifests, sanitized verification results, source/image
pins, operator acceptance, and failure-injection evidence. Backups and tokens
remain separately protected. Reference bundled-Keycloak backup retains its
provider-owned database path; it is not an external-provider requirement.
