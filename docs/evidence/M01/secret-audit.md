# M01 offline detector audit

**Date:** 2026-09-26
**Detector:** pinned `detect-secrets` 1.5.0
**Result:** PASS; no new findings and no baseline changes.

The scan enumerated Git-cached files and nonignored untracked files, including
the new M01 deployment, probe, test, inventory, and evidence files. The direct
scan used the pinned detector's default plugins, thresholds, and filters with
network verification disabled. The final repeat examined 93 files and reported
28 findings;
all 28 matched previously audited baseline findings. The baseline file itself
was handled by `scripts/check_secrets.py`, which validates its detector settings
against the pinned offline defaults and scans its content with fingerprint
fields removed.

The inherited findings remain unchanged: the M00 dependency inventory contains
public license/notice digests; M01 planning prose and a public source revision
identifier produce text/entropy detections. Their audited false-positive
records remain in `.secrets.baseline`. The M01 image inventory, vendored public
license texts, and synthetic interchange fixtures introduced no additional
findings, so there were no candidate image, license, or fixture digests to add
or classify.

`make secrets` passed after the M01 files were present. Its offline check scans
tracked and nonignored untracked files, validates existing exceptions, and
rejects detector/filter configuration drift. No detector, filter, threshold,
or exclusion was changed for this audit.
