# Audited scan findings

The first shared-manifest local check failed at the secret scan. Inspection found three false positives: the fixed `NOT_RUN_RETAINED` cleanup status in the fixture CLI helper and the public source-manifest and wheel checksums in the packaging inspection. These are status metadata and public artifact identifiers, not credentials. Only these actual finding fingerprints were added to the audited baseline as `is_secret: false`; detector and filter settings were unchanged.

The packaging inspection records the pre-audit source manifest. The audited source manifest is a separate snapshot because the baseline itself is an implementation input. Runtime code and wheel contents were unchanged by this audit.
