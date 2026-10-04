"""M13 reference-deployment session: one clean bootstrap, all fixtures loaded over TLS."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pytest

from scripts import software_producer as sp
from tests.integration.m05.test_t01_directory import _setup_directory
from tests.integration.m06.conftest import install_scoped_document
from tests.integration.m07.conftest import install_batteries
from tests.integration.m12.conftest import directory_fixture
from tests.integration.m13 import reference as ref
from tests.integration.software import CaseLoader, fresh_tokens


class ReferenceLoader(CaseLoader):
    """The software loader, with every user token from the reference identity provider."""

    async def user_token(self, username: str) -> str:
        return str((await self.case.token_source.user(username)).access)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if "/integration/m13/" in str(item.path):
            item.add_marker(pytest.mark.integration)
            if not ref.reference_enabled():
                item.add_marker(
                    pytest.mark.skip(reason="M13 reference deployment requires C1_REFERENCE=1")
                )


@dataclass
class Reference:
    runner: asyncio.Runner
    case: Any  # duck-types the M03 LiveCase interface the loaders use
    bootstrap: dict[str, Any]
    identities: dict[str, Any]
    scoped: dict[str, Any]
    batteries: dict[str, Any]
    software: dict[str, Any]

    def run(self, coroutine: Any) -> Any:
        return self.runner.run(coroutine)


@pytest.fixture(scope="session")
def reference() -> Iterator[Reference]:
    for name in ref.AI_VARIABLES:
        assert name not in os.environ, "M13 acceptance requires AI provider variables unset"
    with asyncio.Runner() as runner:
        saved = ref.DIR / "state/loaded.json"
        if os.environ.get("C1_REFERENCE_REUSE") == "1" and saved.is_file():
            # Development convenience only: reuse the loaded deployment. Gates never set it.
            import json

            state = json.loads(saved.read_text())
            identities = json.loads((ref.DIR / "state/test-identities.json").read_text())
            case = ref.ReferenceCase(identities)
            try:
                yield Reference(
                    runner,
                    case,
                    state["bootstrap"],
                    identities,
                    state["scoped"],
                    state["batteries"],
                    {},
                )
            finally:
                runner.run(case.close())
            return
        bootstrap = ref.fresh_deployment()
        identities = ref.provision_identities()
        case = ref.ReferenceCase(identities)

        async def load() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
            await ref.instance_roles(case)
            await _setup_directory(case, directory_fixture())  # type: ignore[arg-type]
            fixture, scopes, revision1, revision2 = await install_scoped_document(
                case  # type: ignore[arg-type]
            )
            scoped = {"scopes": scopes, "revision1": revision1, "revision2": revision2}
            batteries = await install_batteries(case)  # type: ignore[arg-type]
            fresh_tokens(case)  # type: ignore[arg-type]
            software = await sp.load_software_integration(
                ReferenceLoader(case)  # type: ignore[arg-type]
            )
            return scoped, batteries, software

        try:
            scoped, batteries, software = runner.run(load())
            import json

            saved.write_text(
                json.dumps(
                    {
                        "bootstrap": bootstrap,
                        "scoped": scoped,
                        "batteries": {
                            k: v for k, v in batteries.items() if k in {"revision", "principals"}
                        },
                    },
                    default=str,
                )
            )
            saved.chmod(0o600)
            yield Reference(runner, case, bootstrap, identities, scoped, batteries, software)
        finally:
            runner.run(case.close())
