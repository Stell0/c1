# M02 additional runtime dependency review

All four new installed distributions are locked in `uv.lock`; each declares
MIT and has an installed license containing the MIT permission text.
`dependencies.json` records versions, artifact-relative license paths, source
URLs, and SHA-256 hashes. Pydantic 2.13.5 and pydantic-core 2.46.5 require
Python >=3.9; annotated-types 0.8.0 and typing-inspection 0.4.4 require >=3.10.
No optional Pydantic AI, telemetry, or settings package is installed.
Existing RDFLib/pySHACL/httpx runtime artifacts were already inventoried in M01.

The installed and [official pySHACL 0.40.1 metadata](https://pypi.org/pypi/pyshacl/0.40.1/json)
require Python >=3.9, with Python classifiers through 3.13. This corrects the
M02 plan's claimed 3.13 upper bound. Python 3.14 has not been tested. C1 retains
its declared Python 3.13 runtime without claiming incompatibility with 3.14.
Preserve the installed notices when redistributing these dependencies.
