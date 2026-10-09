"""C1 fixture processes may reach application backends and public OIDC only.

The real provider's administrative API and deployment engines remain reachable
by the supervisor fixture, but are denied to C1 initialization/runtime processes.
"""

from __future__ import annotations

import sys
from typing import Any


def install(*, runtime: bool = False) -> None:
    ports = {26363, 28080, 27363, 28081, *([29090] if runtime else [])}

    def audit(event: str, arguments: tuple[Any, ...]) -> None:
        if event != "socket.connect":
            return
        address = arguments[1]
        if (
            not isinstance(address, tuple)
            or len(address) < 2
            or address[0] not in {"127.0.0.1", "::1"}
            or address[1] not in ports
        ):
            raise PermissionError("C1 external fixture forbids this network dependency")

    sys.addaudithook(audit)
