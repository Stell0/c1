# Scoped document fixture

This synthetic fixture exercises a shared Handbook whose seven flat parts use
three current AccessScopes. Alice can read the public scope, Bob can also read
team material, and Carol can read all three scopes. The separate Notes document
is legal-only and contains `zebra-token` to check authorized search selection.

The `revision1` records create both documents and all parts through one
ChangeSet. `revision2.changes` describes two ordinary replacements: it edits
the public text and moves the final public part between the public and team
parts. `scripts/load_fixture.py --fixture scoped-document` applies both
revisions through the authenticated API. The loader uses stable scope IDs with
the `scoped_document_` prefix and must target an isolated fixture database.

Golden `expected/*.json` files record visible part order and revision-2 text;
`*.md` and `*.txt` files record revision-2 rendering for each principal. No
fixture text or identifier is taken from a real customer source.
