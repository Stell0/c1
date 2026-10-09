"""Run the real enrollment/browser/API workflow against the built release image."""

import json
import os
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

import httpx

from tests.integration.m14c.conftest import External
from tests.integration.m14c.test_external_browser import (
    test_t01_t02_t04_t05_t07_t09_external_browser,
)


class ImageExternal(External):
    def __init__(self, directory):
        super().__init__(directory)
        self.name = "c1-m14c-image-" + uuid.uuid4().hex[:10]
        self.image = os.environ.get("C1_RELEASE_IMAGE", "localhost/c1:0.1.0rc2")

    def base(self):
        env_file = self.directory / "container.env"
        env_file.write_text(
            "".join(k + "=" + v + "\n" for k, v in self.env.items() if k.startswith("C1_"))
        )
        env_file.chmod(0o600)
        return [
            "docker",
            "run",
            "--rm",
            "--network",
            "host",
            "--read-only",
            "--user",
            str(os.getuid()) + ":" + str(os.getgid()),
            "--env-file",
            str(env_file),
            "-v",
            str(self.directory) + ":" + str(self.directory),
        ]

    def operator(self, *arguments, expected=0):
        result = subprocess.run(
            self.base()
            + ["--entrypoint", "/opt/c1/bin/c1-admin", self.image, "application", *arguments],
            capture_output=True,
        )
        assert result.returncode == expected, "container operator exit " + str(result.returncode)
        return json.loads(result.stdout)

    def start_server(self, boundary=None):
        assert boundary is None
        log = self.directory / "container.log"
        log.touch(mode=0o600)
        with log.open("ab") as stream:
            self.process = subprocess.Popen(
                self.base()
                + [
                    "--name",
                    self.name,
                    "--entrypoint",
                    "/opt/c1/bin/python",
                    self.image,
                    "-m",
                    "uvicorn",
                    "c1.web:from_env",
                    "--factory",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "29095",
                    "--no-access-log",
                ],
                stdout=stream,
                stderr=stream,
            )
        for _ in range(60):
            try:
                with httpx.Client(trust_env=False, timeout=2) as client:
                    client.get(self.env["C1_EXPLORER_ORIGIN"] + "/v1/readyz")
                return
            except httpx.HTTPError:
                assert self.process.poll() is None, "container exited"
                time.sleep(0.5)
        raise RuntimeError("container startup deadline")

    def stop_server(self):
        if self.process is not None and self.process.poll() is None:
            subprocess.run(
                ["docker", "stop", "-t", "15", self.name], capture_output=True, check=True
            )
            self.process.wait(timeout=20)


with tempfile.TemporaryDirectory(prefix="c1-m14c-release-image-") as path:
    directory = Path(path)
    directory.chmod(0o700)
    fixture = ImageExternal(directory)
    try:
        fixture.start()
        test_t01_t02_t04_t05_t07_t09_external_browser(fixture)
        assert fixture.operator("contract")["contract_version"] == 1
        print(
            json.dumps(
                {
                    "result": "PASS",
                    "workflow": "image enrollment/browser/API/ChangeSet/context/revocation",
                    "image_id": subprocess.check_output(
                        ["docker", "image", "inspect", "--format", "{{.Id}}", fixture.image],
                        text=True,
                    ).strip(),
                    "container_user": os.getuid(),
                    "read_only_rootfs": True,
                }
            )
        )
    finally:
        fixture.close()
