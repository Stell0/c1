# C1 operations

These documents describe the reference deployment in `deployment/reference/` and the M14c external-provider candidate `0.1.0rc2`. Historical reference qualification is in [M13](../milestones/M13-report.md); current candidate qualification and release status are in [M14c](../milestones/M14c-report.md). Performance measurements retain their reported source/version.

| Document | Covers |
|---|---|
| [install.md](install.md) | Requirements, image build, first start, TLS, settings, secrets and rotation |
| [api.md](api.md) | Authentication, the OpenAPI description, request rules and errors |
| [security-administration.md](security-administration.md) | Administrators, scopes, memberships, re-scoping, review rules |
| [current-binding-recovery.md](current-binding-recovery.md) | How current bindings govern old content, interrupted operations, consistency checks |
| [backup-restore.md](backup-restore.md) | Quiesced backups, knowledge-only restore, guarded disaster recovery |
| [schema-migration.md](schema-migration.md) | Installing profiles, incompatible changes, restores and schema |
| [import-export.md](import-export.md) | Snapshot export versus backup, JSON-LD import rules |
| [limits.md](limits.md) | Configured limits and the measured behavior on the declared machine |
| [maintenance.md](maintenance.md) | Scheduled storage maintenance (TerminusDB optimize) |
| [external-oidc.md](external-oidc.md) | M14c candidate provider, token, initialization and enrollment contract; check qualification evidence |
| [external-oidc-recovery.md](external-oidc-recovery.md) | M14c candidate external-provider maintenance, application-owned backup and guarded recovery |

C1 needs no AI provider, model or key. It does need its identity provider (Keycloak), authorization service (OpenFGA), knowledge store (TerminusDB) and their database (PostgreSQL).
