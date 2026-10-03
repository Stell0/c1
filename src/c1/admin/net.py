"""HTTP access to a deployment's TLS endpoint by name, without editing /etc/hosts.

Requests for a mapped host name connect to the mapped address, while TLS
server-name indication and certificate verification still use the name.
"""

from __future__ import annotations

import ssl
from pathlib import Path

import httpx


class MappedTransport(httpx.AsyncBaseTransport):
    def __init__(self, mapping: dict[str, str], ca_file: Path | None) -> None:
        self.mapping = mapping
        verify: ssl.SSLContext | bool = (
            ssl.create_default_context(cafile=str(ca_file)) if ca_file else True
        )
        self._inner = httpx.AsyncHTTPTransport(verify=verify, trust_env=False)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        target = self.mapping.get(host)
        if target is not None:
            request.extensions = {**request.extensions, "sni_hostname": host}
            request.url = request.url.copy_with(host=target)
        return await self._inner.handle_async_request(request)

    async def aclose(self) -> None:
        await self._inner.aclose()


def mapped_client(
    base_url: str, *, mapping: dict[str, str], ca_file: Path | None, timeout: float = 120
) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=base_url,
        transport=MappedTransport(mapping, ca_file),
        timeout=timeout,
        trust_env=False,
    )
