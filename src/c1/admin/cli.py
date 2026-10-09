"""`c1-admin` entry point: host commands, and `internal` commands for the tools container."""

from __future__ import annotations

import argparse
import json
import sys
from typing import NoReturn

from c1.admin import application, host


class AdminParser(argparse.ArgumentParser):
    machine_errors = False

    def error(self, message: str) -> NoReturn:
        if self.machine_errors or self.prog.startswith("c1-admin application"):
            print(json.dumps({"contract_version": 1, "error": "invalid_arguments"}))
            raise SystemExit(2)
        super().error(message)


def main(argv: list[str] | None = None) -> int:
    parser = AdminParser(prog="c1-admin", description="C1 deployment administration")
    parser.machine_errors = "application" in (argv if argv is not None else sys.argv[1:])
    sub = parser.add_subparsers(dest="command", required=True)
    host.build_parser(sub)
    application.build_parser(sub)
    internal = sub.add_parser("internal", help="inside the tools container only")
    from c1.admin import internal as internal_commands

    internal_commands.build_parser(internal)
    args = parser.parse_args(argv)
    if args.command == "internal":
        return internal_commands.run(args)
    if args.command == "application":
        return application.run(args)
    return host.run(args)


if __name__ == "__main__":
    raise SystemExit(main())
