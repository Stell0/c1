# M04 reviewed-write demonstration

Command (pinned stack running):

```sh
UV_CACHE_DIR=/tmp/c1-uv-cache uv run --locked python -m scripts.demo_m04 > /tmp/c1-m04-demo-result.json 2> /tmp/c1-m04-demo-audit.jsonl
```

Exit code: `0`. The sanitized JSON result is [demo.json](demo.json). Its synthetic
ChangeSet ended `applied`; the knowledge log gained exactly one commit; the
commit receipt names that ChangeSet; and the authorized history page contains
the same ChangeSet ID in one revision entry. The script retrieved its base
revision through authenticated `GET /v1/instance` and used independent reviewer
credentials. It created and removed its own knowledge/workflow databases and
OpenFGA store. The script checked the receipt digest against the approved
payload. The generated SHA-256 value was omitted from the versioned JSON
because generic secret scanning flags long hex strings. Tokens and record
bodies are absent from the result. The audit stream was kept in `/tmp`, outside
the repository.
