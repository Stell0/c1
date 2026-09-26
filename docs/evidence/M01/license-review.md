# M01 installed dependency license review

Reviewed 2026-09-26 against [inventory.json](inventory.json) and the files in
`.venv/lib/python3.13/site-packages/`. The 42 installed Python distributions
have 48 recorded license files; all 48 files exist and their SHA-256 hashes
match the inventory. `colorama` is locked but not installed on this platform,
so it is outside this installed-artifact review. The four service images and
their upstream license artifacts are recorded separately in the inventory.

| Installed license family | Packages reviewed |
|---|---|
| MIT (16) | anyio, ast_serialize, attrs, charset-normalizer, h11, iniconfig, librt, mypy, mypy_extensions, pluggy, pyparsing, pytest, PyYAML, ruff, six, urllib3 |
| Apache-2.0 (10) | aiosignal, detect-secrets, frozenlist, multidict, openfga-sdk, opentelemetry-api, propcache, pyshacl, requests, yarl |
| BSD-3-Clause (5) | httpcore, httpx, idna, prettytable, rdflib |
| BSD-2-Clause (1) | Pygments |
| PSF-2.0 (2) | aiohappyeyeballs, typing_extensions |
| MPL-2.0 (2) | certifi, pathspec |
| Mixed or other (6) | aiohttp (Apache-2.0 and MIT), html5rdf (MIT text), owlrl (W3C Software and Document Notice and License), packaging (Apache-2.0 or BSD-2-Clause), python-dateutil (BSD-style text for all code, Apache-2.0 also for later/relicensed contributions), wcwidth (MIT plus Markus Kuhn permissive notice) |

The installed text resolves the inventory's metadata exceptions:

- `owlrl 7.6.2`, marked `W3C-20150513`, includes the W3C Software and
  Document Notice and License. It grants copying, modification, and
  distribution for any purpose without fee; redistribution requires the full
  notice, prior notices, and change notices. Its installed file is
  `owlrl-7.6.2.dist-info/LICENSE.txt`.
- `html5rdf 1.2.1` places the full MIT permission and notice text in its
  metadata `License` field and installed `html5rdf-1.2.1.dist-info/LICENSE`.
  The inventory's long expression is literal license text, not a new license.
- `pathspec 1.1.1` has no declared license expression in metadata, but its
  installed `pathspec-1.1.1.dist-info/licenses/LICENSE` is the full Mozilla
  Public License 2.0, including its source-form notice exhibit.
- `wcwidth 0.9.1` also lacks a declared expression. Its installed
  `wcwidth-0.9.1.dist-info/licenses/LICENSE` contains the MIT license with
  Jeff Quast's notice and a separate permissive Markus Kuhn notice for the
  Unicode width material.
- `python-dateutil 2.9.0.post0` says “Dual License” in metadata. Its installed
  `python_dateutil-2.9.0.post0.dist-info/LICENSE` gives BSD-style conditions
  for all code and Apache-2.0 terms for contributions after 2017-12-01 or
  re-licensed contributions. Preserve both portions when redistributing.
- `detect-secrets 1.5.0` says `UNKNOWN` in package metadata, but the installed
  `detect_secrets-1.5.0.dist-info/LICENSE` is Apache-2.0. M00 already reviewed
  this mismatch in [its dependency evidence](../M00/dependencies.json).

The remaining non-single-family records were checked against installed files:
`aiohttp` includes its own license and vendored `llhttp` license; `packaging`
includes Apache and BSD alternatives; `pyshacl` embeds the Apache-2.0 text in
metadata as well as in its license file. `propcache`, `requests`, and `yarl`
also ship recorded `NOTICE` files. The inventory retains exact paths and hashes
for each package, including these additional texts.

## Pinned service source notices

On 2026-09-26, HTTP GET of each source-tag root `NOTICE` and `NOTICE.txt`
candidate derived from [deployment/images.json](../../../deployment/images.json)
returned **404**. There was no source-root notice file at these exact URLs to
bundle or hash:

| Service tag | `NOTICE` | `NOTICE.txt` |
|---|---|---|
| TerminusDB `v12.0.7` | [404](https://raw.githubusercontent.com/terminusdb/terminusdb/v12.0.7/NOTICE) | [404](https://raw.githubusercontent.com/terminusdb/terminusdb/v12.0.7/NOTICE.txt) |
| OpenFGA `v1.21.0` | [404](https://raw.githubusercontent.com/openfga/openfga/v1.21.0/NOTICE) | [404](https://raw.githubusercontent.com/openfga/openfga/v1.21.0/NOTICE.txt) |
| Keycloak `26.7.4` | [404](https://raw.githubusercontent.com/keycloak/keycloak/26.7.4/NOTICE) | [404](https://raw.githubusercontent.com/keycloak/keycloak/26.7.4/NOTICE.txt) |
| PostgreSQL `REL_17_11` | [404](https://raw.githubusercontent.com/postgres/postgres/REL_17_11/NOTICE) | [404](https://raw.githubusercontent.com/postgres/postgres/REL_17_11/NOTICE.txt) |

The image-path checks in `inventory.json` likewise found no embedded notice
at the listed candidate paths. This records only those source-root and image
paths. It does not establish whether transitive components in the images carry
their own notices; inspect those before redistributing an image or assembling
a C1 distribution.

This is a bounded review of the installed M01 development/probe dependencies
and image-level upstream license artifacts. It supports choosing these
open-source components for the M01 probe. It does not establish a complete
redistribution notice bundle for container layers, platform packages, or a
future C1 release. M13 must assemble and verify the notices for artifacts
actually redistributed.
