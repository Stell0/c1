# Storage maintenance

TerminusDB records every commit as a new delta layer. Reads walk the layers, so they slow down as commits accumulate. C1 commits to:
- its workflow journal at every workflow step;
- the knowledge database at every applied ChangeSet;
- TerminusDB's `_system` database on every database operation.

`optimize` squashes the layers. Content, commit IDs and history are unchanged.

## Command

```sh
uv run c1-admin maintenance optimize --dir deployment/reference --project c1-ref
```

The command optimizes the knowledge, workflow and `_system` databases in turn. It prints the time each one took and confirms that the knowledge and workflow heads did not change.

- It is safe while C1 serves: it creates no commit, and C1 does not have to stop.
- It needs no maintenance window. A quiesced backup stops the services, so a run that overlaps one fails without effect; schedule the two apart.

## Schedule

Run it **daily**. On an instance with more than a few hundred applied ChangeSets a day, run it **hourly**. The command is cheap: on the laptop after the M14 S corpus load (932 records, about 100 workflow commits), it took 0.4 s for the workflow database and 0.1 s for the knowledge database.

Example systemd units for the host that runs the reference deployment (adjust `WorkingDirectory` and the user):

```ini
# /etc/systemd/system/c1-optimize.service
[Unit]
Description=C1 storage maintenance (TerminusDB optimize)

[Service]
Type=oneshot
WorkingDirectory=/opt/c1
ExecStart=/usr/local/bin/uv run --locked c1-admin maintenance optimize --dir deployment/reference --project c1-ref

# /etc/systemd/system/c1-optimize.timer
[Unit]
Description=Run C1 storage maintenance daily

[Timer]
OnCalendar=daily
RandomizedDelaySec=15m
Persistent=true

[Install]
WantedBy=timers.target
```

Enable it with `systemctl enable --now c1-optimize.timer`. A cron entry that runs the same command works as well.

## Measured effect

| Situation | Effect |
|---|---|
| M13, makako, after about 700 workflow commits | Workflow listing 0.56 s → 0.15 s ([M13 report](../milestones/M13-report.md)) |
| M14b, laptop, right after the S corpus load | Warm simple reads 5–15% faster (for example alias lookup 196 → 182 ms, entity list 279 → 230 ms); `/v1/history` 1.13 → 1.06 s |

The gain grows with the number of commits since the last optimize. The [M14b report](../milestones/M14b-report.md) records the makako measurement.
