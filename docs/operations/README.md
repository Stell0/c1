# C1 operations

These documents describe how to run release candidate `0.1.0rc1` with the reference deployment in `deployment/reference/`. They describe measured, tested behavior; the [M13 report](../milestones/M13-report.md) records the evidence.

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

C1 needs no AI provider, model or key. It does need its identity provider (Keycloak), authorization service (OpenFGA), knowledge store (TerminusDB) and their database (PostgreSQL).
