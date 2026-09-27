# M04 ChangeSet fixture

`reviewed-assertions.json` selects the source, evidence, and two assertion
patterns in the versioned `core-knowledge/fixture.jsonld`. Integration tests
mint fresh IDs and scopes from this synthetic pattern for each isolated stack.
The imported assertion cites its evidence; the manual assertion names its
attributing principal and has no evidence.
