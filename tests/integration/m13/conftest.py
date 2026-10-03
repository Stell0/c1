"""M13 reference-deployment session: one clean bootstrap, all fixtures loaded over TLS."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pytest

from tests.integration.m05.test_t01_directory import _setup_directory
from tests.integration.m06.conftest import install_scoped_document
from tests.integration.m07.conftest import install_batteries
from tests.integration.m12.conftest import directory_fixture
from tests.integration.m13 import reference as ref
from tests.integration.software import load as load_software


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
            software = await load_software(case)  # type: ignore[arg-type]
            return scoped, batteries, software

        try:
            scoped, batteries, software = runner.run(load())
            yield Reference(runner, case, bootstrap, identities, scoped, batteries, software)
        finally:
            runner.run(case.close())
