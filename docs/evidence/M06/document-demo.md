# M06 scoped-document demonstration

The authenticated fixture loader exited 0 after both revisions were applied.
`UV_CACHE_DIR=.uv-cache UV_OFFLINE=1 uv run --locked python scripts/demo_m06.py`
exited 0. Alice received three public parts; Carol received all seven ordered
parts. Both part ID sequences match their committed golden files exactly.
Alice's Markdown output matches its golden byte for byte. Carol's Markdown text
matches its golden after removing the golden file's one terminal newline; the
rendered content, including both code blocks, is unchanged.
The detailed log contains only synthetic IDs/text and ordinary audit fields.
No token, environment value, or confidential source was retained.
