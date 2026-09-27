# Core knowledge fixture v1

`fixture.jsonld` contains synthetic records under the bundled core context. The
names Tesla, Ada Example, and Battery Pack v1 are test labels only; the amounts,
employment claims, documents, and source excerpts are invented and make no
claim about a real company or person.

The fixture has three entities, two independently identified and conflicting
revenue assertions, two distinct `worksFor` assertions for one person, and an
attributed manual statement without external evidence. Two different synthetic
sources and import activities retain separate provenance. Named keyword and
time nodes avoid blank nodes in the supported interchange profile. The known,
unknown, and unbounded boundaries have different meanings. A synthetic document
has two ordered parts; the profile records their structure without reconstructing
them in this milestone.

The `rdf:value` assertions deliberately exercise all twelve supported literal
datatypes. Their lexical forms include `1` for boolean, `+001` for integer,
`1.2300` for decimal, and `-0.0` for double. The checked-in expected files list
these spellings, stable identities, keyword normalization, and temporal bounds.
The test compares those values independently of RDF graph isomorphism, since
some RDF parsers normalize numeric lexical spellings.

The IDs are fixed UUIDv4-shaped test identifiers. They do not encode producer,
project, access scope, or storage key. Source revisions are named synthetic
revisions rather than purported content hashes.
