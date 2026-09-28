# M06 wheel check

After the document by-ID route fix, ran
`UV_CACHE_DIR=.uv-cache uv build --wheel --offline --out-dir /tmp/c1-m06-wheel`
(exit 0), producing `/tmp/c1-m06-wheel/c1-0.0.0.dev0-py3-none-any.whl`.
Inspection of the fresh 96-entry wheel found `c1/documents/` (service, renderer,
search, ordering, text, and validation), `c1/api/routes/documents.py`,
`c1/api/routes/history.py`, `c1/changes/history.py`, and all 10 `c1/query/*.py`
modules. The archived document routes include `GET /by-id` named
`document_read_by_id` with its `document_id` query parameter. There are no
packaged environment files, credentials, cache members, evidence files, or
deployment assets.

The build emits a warning that `.uv-cache` is inside the source tree and may be
included in distributions; archive inspection confirms it was not packaged. The
full output and warning are retained in `wheel-build.log`. No dependency or image
pin changed. No live service request was made.
