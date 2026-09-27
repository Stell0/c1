# M04 no-AI path check

The repository search
`rg -n 'OPENAI|ANTHROPIC|GEMINI|LLM_|EMBEDDING_|AI_API_KEY' src/c1 deployment scripts`
found only `scripts/clean_start.sh:12`, which unsets optional provider variables
before a clean run. M04's API routes, ChangeSet service, storage, packaged
profiles, and demo use the pinned local services and authenticated API; they
introduce no model runtime, provider egress, or mandatory AI credential.
