# Schema and profiles

C1's schema is the core profile plus installed data-only profiles from the bundled catalog (`GET /v1/schema` lists them; `available_profiles` lists what can be installed).

- **Install a profile:** a schema administrator creates a ChangeSet with one `{"kind": "install_profile", "profile": "<name>"}` operation; a reviewer approves and applies it. Profile and content operations cannot be mixed. Installation is deterministic: the installed classes and properties are exactly those of the bundled files (M13-T06 compares them).
- **Compatible changes:** a new profile version that only adds classes or optional properties is accepted.
- **Incompatible changes:** removing a class, changing storage identity or tightening cardinality is refused with `C1-PR-004 MigrationRequired`. C1 has no automatic data migration; an incompatible change needs a reviewed migration plan (a new profile version plus ChangeSets that rewrite affected records) and its own milestone.
- **Restores and schema:** a knowledge-only restore refuses a backup that lacks a profile installed later, or whose profile versions differ from the installed ones. Restore a compatible backup, then reinstall later profiles through ChangeSets.
- **Readiness:** C1 is unready when the installed profile set in TerminusDB differs from what the running process loaded (for example after an out-of-band change); restart after schema maintenance.
