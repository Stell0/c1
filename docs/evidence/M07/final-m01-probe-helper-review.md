# Final M01 probe wrapper — prepared, not executed

`run-final-m01-probe.sh` replaces the planned weak capture in `/tmp/M07-M01-probe-closure.sh.txt` with a versioned wrapper derived from `run-corrected-live-gate.sh`. The helper has not executed; no probe, service, API, container, or source/test/configuration change occurred during preparation.

Run only after the post-transport 79-case gate and fixture CLI have completed successfully:

```text
bash docs/evidence/M07/run-final-m01-probe.sh
```

The script requires all four `post-transport-live-exit.txt` fields to be zero and the fixture CLI exit fields to show child return code zero, cleanup PASS, and wrapper return code zero. It then executes the existing named M01 command `uv run --locked pytest -s -m integration tests/integration/m01` with the diagnostics plugin, `--tb=line`, `--show-capture=no`, and no pytest cache. Six provider keys are unset, `C1_STACK=1`, and UV is offline using `.uv-cache`. The ten test functions include three crash parameters, giving the planned 12 cases; actual collection/results remain NOT_RUN and must be checked in the new JUnit artifact.

New destinations are `final-m01-probe.log`, `final-m01-probe-junit.xml`, `final-m01-probe-exit.txt`, and, when inventory bytes change, `final-m01-generated-inventory.json` / `.md`. Existing destinations, including dangling symlinks, are refused before execution. Only `docs/evidence/M01/inventory.json` and `inventory.md` are backed up and restored. The EXIT trap saves changed generated inventory before restoring the original bytes and metadata; initially absent inventory is removed after capture. Unexpected inventory symlinks/non-regular files fail restoration rather than being followed. Generated destinations are checked again before copying. Restoration failure retains backups and reports their path.

`PIPESTATUS` preserves pytest and tee exits independently. The exit artifact records `pytest_exit`, `tee_exit`, `restore_exit`, and `script_exit`; tee or restore failures cannot turn a failed wrapper into a success. No M03 API log or unrelated evidence file is backed up, removed, or restored.

Static checks executed:

- `bash -n docs/evidence/M07/run-final-m01-probe.sh` — exit 0.
- `git diff --no-index -- docs/evidence/M07/run-corrected-live-gate.sh docs/evidence/M07/run-final-m01-probe.sh` — exit 1, expected because the reviewed adaptation differs from the template.
- `git diff --no-index --check -- /dev/null docs/evidence/M07/run-final-m01-probe.sh` — exit 1 for the new-file difference, with no whitespace diagnostics.

Final script SHA-256 from `sha256sum docs/evidence/M07/run-final-m01-probe.sh`:

```text
e7e2cec6092f914fb3262b7454f84a0ca02c52d3374d2ebfce6cc02d7ee87049
```

Remaining uncertainty: the probe, generated-inventory capture, and trap restoration paths have not executed. Static review is not evidence that the 12-case probe passed. The lead owns execution and final result validation after the preceding gates.


The final prerequisite-only adjustment points at the future post-transport terminal gate. The intervening fixture CLI validates `post-transport-live-junit.xml` against all 79 expected node identities and records success only after its child and cleanup pass. The final probe's environment, test flags, inventory capture, and restoration behavior were not changed. `bash -n` was rerun and exited 0; no probe or service operation executed.
