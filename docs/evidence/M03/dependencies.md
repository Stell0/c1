# M03 runtime dependency review

Reviewed on 2026-09-27 against the exact versions installed by
`UV_CACHE_DIR=.uv-cache UV_PYTHON_INSTALL_DIR=.uv-python
UV_PYTHON_BIN_DIR=.uv-python/bin uv sync --locked`. The machine-readable
[artifact list](dependencies.json) records each installed license file and its
SHA-256. Every listed file was present and readable. PyPI metadata for these
exact versions was checked through its versioned JSON endpoints.

| Added distribution | Pin | Installed license expression | License files |
|---|---:|---|---:|
| [FastAPI](https://pypi.org/pypi/fastapi/0.141.1/json) | 0.141.1 | MIT | 1 |
| [Starlette](https://pypi.org/pypi/starlette/1.7.0/json) | 1.7.0 | BSD-3-Clause | 1 |
| [Uvicorn](https://pypi.org/pypi/uvicorn/0.54.0/json) | 0.54.0 | BSD-3-Clause | 1 |
| [PyJWT](https://pypi.org/pypi/PyJWT/2.15.0/json) | 2.15.0 | MIT | 1 |
| [cryptography](https://pypi.org/pypi/cryptography/50.0.1/json) | 50.0.1 | Apache-2.0 OR BSD-3-Clause | 3 |
| [cffi](https://pypi.org/pypi/cffi/2.1.1/json) | 2.1.1 | MIT-0 | 1 |
| [pycparser](https://pypi.org/pypi/pycparser/3.0/json) | 3.0 | BSD-3-Clause | 1 |
| [Click](https://pypi.org/pypi/click/8.5.0/json) | 8.5.0 | BSD-3-Clause | 1 |
| [annotated-doc](https://pypi.org/pypi/annotated-doc/0.0.5/json) | 0.0.5 | MIT | 1 |

`openfga-sdk==0.10.4` remains a development-only dependency for the M01 probes;
its installed Apache-2.0 license was reviewed in
[M01's license evidence](../M01/license-review.md). The services retain their
M01 digest pins; this review adds no image. All listed Python licenses are
open-source and suitable as mandatory dependencies. This is an installed
artifact review, not a complete redistribution notice bundle for a release.
