# M12 dependency review

Reviewed on 2026-10-03 against the exact versions that `uv sync --locked`
installed. [`dependencies.json`](dependencies.json) records each installed
license file and its SHA-256. The license file of every distribution listed
below was present and readable.

| Distribution | Pin | Use | License (installed metadata or file) |
|---|---:|---|---|
| [Jinja2](https://pypi.org/pypi/Jinja2/3.1.6/json) | 3.1.6 | Runtime | BSD-3-Clause (`LICENSE.txt`; the metadata classifier says BSD License) |
| [MarkupSafe](https://pypi.org/pypi/MarkupSafe/3.0.4/json) | 3.0.4 | Runtime (Jinja2 dependency) | BSD-3-Clause |
| [playwright](https://pypi.org/pypi/playwright/1.63.0/json) | 1.63.0 | Development and tests only | Apache-2.0, with the bundled driver's NOTICE and ThirdPartyNotices |
| [pyee](https://pypi.org/pypi/pyee/13.0.1/json) | 13.0.1 | Development (Playwright dependency) | MIT |
| [greenlet](https://pypi.org/pypi/greenlet/3.5.6/json) | 3.5.6 | Development (Playwright dependency) | MIT AND PSF-2.0 |
| typing_extensions | 4.16.0 | Development (already locked) | PSF-2.0 |

**Browser binary.** Playwright 1.63.0 downloads Chrome Headless Shell
153.0.8010.12 (Playwright build `chromium-headless-shell` 1243) into the
ignored `.playwright/` directory. It is a test tool only: it is not committed,
not shipped, and not used by C1 at runtime.

**axe-core.** Version 4.13.0 (MPL-2.0) is vendored for tests under
`tests/browser/vendor/axe-core-4.13.0/`, with its unchanged `LICENSE` and a
[provenance record](../../../tests/browser/vendor/axe-core-4.13.0/PROVENANCE.json).
Its tarball integrity matches the npm registry value. It is injected only into a
test browser context and is never included in the wheel or served by C1.

**makako.** The Chromium runtime libraries come from the standard Rocky Linux 9
repositories ([package list](makako-chromium-deps.txt)).

Only Jinja2 and MarkupSafe join the mandatory runtime. Both are open-source and
suitable as mandatory dependencies. This is an installed-artifact review, not a
release notice bundle (M13).
