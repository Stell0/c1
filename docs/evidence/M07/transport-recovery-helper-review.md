# Controlled transport recovery — prepared, not executed

`run-transport-recovery.sh` prepares the lead's accepted operational restart using the existing pinned stack commands and retained volumes. It has not executed. The earlier corrected gate remains FAIL: 68 passed, one M05 directory failure, and ten not run. The raw HTTP stream disconnect's root cause remains unknown. A later successful restart and gate would demonstrate recovery, not establish the cause or prove the restart fixed it.

The wrapper requires terminal `transport-diagnostic-m05-exit.txt` fields `pytest_exit=0`, `tee_exit=0`, and `script_exit=0`. It refuses existing output paths, including dangling symlinks, and requires the existing regular `deployment/.env` without reading or printing its contents. This prevents the existing stack-up helper from generating absent configuration. Outputs are reserved through exclusive shell descriptors before any stack command; subsequent logging and exit recording use those descriptors rather than reopening paths.

After lead review, the exact reproduction is:

```text
bash docs/evidence/M07/run-transport-recovery.sh
```

The command sequence is `make stack-down`, then `make stack-up` only if both stack-down and its tee succeed. Both commands unset the same six provider-key variables and use offline UV with `.uv-cache`. Inspection of `scripts/stack.py` confirms ordinary down calls compose down without `--volumes`; only stack reset uses volume deletion. The wrapper invokes neither reset nor volume deletion. Up uses the existing readiness/bootstrap path and unchanged configuration/pins. No source, test, configuration, credential, pin, or volume change was made during preparation.

New files are `recovery-stack-down.log`, `recovery-stack-down-exit.txt`, `recovery-stack-up.log`, and `recovery-stack-up-exit.txt`. Each exit artifact distinguishes `make_exit`, `tee_exit`, `step_exit`, and overall `script_exit`; a stage never reached remains `NOT_RUN`. The EXIT trap records failure independently of command output. A nonzero down command or tee stops before up. Failed evidence writing makes the wrapper fail. Logs contain the existing stack command output and need the usual confidentiality review before publication.

Static checks executed:

```text
bash -n docs/evidence/M07/run-transport-recovery.sh docs/evidence/M07/run-final-m01-probe.sh
UV_CACHE_DIR=.uv-cache UV_OFFLINE=1 uv run --locked python docs/evidence/M07/verify-manifest.py
```

Both exited 0. The manifest reported 345 frozen implementation inputs unchanged. No service operation, API request, live test, or full gate was run by this preparation. Whitespace checks had no diagnostics. Script SHA-256:

```text
5d50cb5c42211e55eb03786be0660c16e9ec10929a81b0a3e71b93640d614618
```

The closure helpers now require the distinct future post-transport gate: the fixture CLI checks all four zero exit fields, JUnit counts/no failure/no skip, and equality with all 79 expected node identities; the final M01 probe requires the post-transport gate exit fields and the intervening CLI's successful child/cleanup/wrapper results. Earlier failure artifacts are preserved. The lead owns authorization to execute the restart, review of the resulting operational evidence, and validation of the complete future 79-case gate and closure checks. Preparation is not a passing milestone gate.
