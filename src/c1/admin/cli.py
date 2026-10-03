"""`c1-admin` entry point: host commands, and `internal` commands for the tools container."""

from __future__ import annotations

import argparse

from c1.admin import host


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="c1-admin", description="C1 deployment administration")
    sub = parser.add_subparsers(dest="command", required=True)
    host.build_parser(sub)
    internal = sub.add_parser("internal", help="inside the tools container only")
    from c1.admin import internal as internal_commands

    internal_commands.build_parser(internal)
    args = parser.parse_args(argv)
    if args.command == "internal":
        return internal_commands.run(args)
    return host.run(args)


if __name__ == "__main__":
    raise SystemExit(main())
