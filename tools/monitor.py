#!/usr/bin/env python3
"""Unified command line for Monitor.AI."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Mapping

import doctor
from monitor_config import MonitorConfig, config_path, write_example
import service_manager
import session_daemon
from session_hook import hook_health


def _parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", type=Path, default=None,
                        help="path to monitor.toml (default: per-user config)")
    parser = argparse.ArgumentParser(description=__doc__, parents=[common])
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", parents=[common], help="run the daemon")
    session_daemon.add_arguments(run)
    once = commands.add_parser("once", parents=[common], help="run one daemon cycle")
    session_daemon.add_arguments(once)

    diagnose = commands.add_parser("doctor", parents=[common], help="check local setup")
    diagnose.add_argument("--fixture", type=Path, help="explicit deterministic diagnostic fixture")
    diagnose.add_argument("--json", action="store_true", help="write JSON report")

    config = commands.add_parser("config", parents=[common], help="manage configuration")
    config_commands = config.add_subparsers(dest="config_command", required=True)
    init = config_commands.add_parser("init", help="write a safe example config")
    init.add_argument("--path", type=Path, default=None)
    config_commands.add_parser("show", help="show redacted configuration")

    hooks = commands.add_parser("hooks", parents=[common], help="inspect hook setup")
    hook_commands = hooks.add_subparsers(dest="hooks_command", required=True)
    hook_commands.add_parser("check", help="report Claude and Codex hook health")

    service = commands.add_parser("service", parents=[common], help="manage the per-user daemon")
    service_commands = service.add_subparsers(dest="service_command", required=True)
    for action in ("install", "remove", "status"):
        command = service_commands.add_parser(action, help="{} the user service".format(action))
        command.add_argument("--dry-run", action="store_true",
                             help="show the operation without changing service state")
    return parser


def _load_config(path: Path | None, environ: Mapping[str, str]) -> MonitorConfig:
    return MonitorConfig.load(path if path is not None else config_path(), environ=environ)


def _print_doctor(results: list[doctor.CheckResult], as_json: bool) -> None:
    if as_json:
        print(json.dumps(doctor.report(results), sort_keys=True))
        return
    for result in results:
        print("{:5} {:16} {}".format(result.status.upper(), result.code, result.message))


def main(argv: list[str] | None = None, environ: Mapping[str, str] = os.environ) -> int:
    args = _parser().parse_args(argv)
    source = args.config if args.config is not None else config_path()
    if args.command == "service":
        python_path = Path(sys.executable).resolve()
        repository_path = Path(__file__).resolve().parents[1]
        config_file = source.expanduser().resolve()
        if args.service_command == "install":
            result = service_manager.service_install(
                python_path, repository_path, config_file, dry_run=args.dry_run)
        elif args.service_command == "remove":
            result = service_manager.service_remove(dry_run=args.dry_run)
        else:
            result = service_manager.service_status(dry_run=args.dry_run)
        print(result.message)
        return result.returncode
    try:
        config = _load_config(args.config, environ)
    except ValueError as error:
        if args.command == "doctor":
            results = [doctor.CheckResult("config", doctor.FAIL, "configuration is invalid", {})]
            _print_doctor(results, getattr(args, "json", False))
            return doctor.exit_code(results)
        print("monitor: invalid configuration: {}".format(error), file=sys.stderr)
        return 2

    if args.command in {"run", "once"}:
        if args.command == "once":
            args.once = True
        return session_daemon.run(args, config)
    if args.command == "doctor":
        results = doctor.run_checks(config, args.fixture, source)
        _print_doctor(results, args.json)
        return doctor.exit_code(results)
    if args.command == "config":
        if args.config_command == "init":
            destination = args.path or source
            try:
                write_example(destination)
            except FileExistsError:
                print("monitor: configuration already exists: {}".format(destination), file=sys.stderr)
                return 2
            print(destination)
            return 0
        print(json.dumps(config.redacted_dict(), sort_keys=True, default=str))
        return 0
    if args.command == "hooks":
        health = hook_health()
        print(json.dumps(health, sort_keys=True))
        return 0 if all(health.values()) else 1
    raise AssertionError("unknown command")


if __name__ == "__main__":
    raise SystemExit(main())
