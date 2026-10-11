"""One command catalog for parsing, help, validation and dispatch."""

import argparse
import os
import subprocess
import sys
from pathlib import Path

from . import ROOT, InfraError, __version__, data, operations, planning, settings
from .catalog import resolve
from .docker import Docker
from .instance import Instance
from .presentation import Presentation
from .registry import Registry, numbers


class Parser(argparse.ArgumentParser):
    def __init__(self, *args, presentation=None, **kwargs):
        self.presentation = presentation or Presentation("zh")
        kwargs.setdefault("allow_abbrev", False)
        super().__init__(*args, **kwargs)
        self._positionals.title = self.presentation.t("positionals")
        self._optionals.title = self.presentation.t("options")

    def format_help(self):
        return (
            super()
            .format_help()
            .replace("usage:", self.presentation.t("usage") + ":")
            .replace("show this help message and exit", self.presentation.t("help"))
        )

    def format_usage(self):
        return super().format_usage().replace("usage:", self.presentation.t("usage") + ":")

    def error(self, message):
        if self.presentation.language == "zh":
            message = (
                message.replace("unrecognized arguments:", "无法识别的参数：")
                .replace("invalid choice:", "无效选项：")
                .replace("choose from", "可选值")
                .replace("expected one argument", "需要一个参数")
                .replace("the following arguments are required:", "缺少必需参数：")
                .replace("argument ", "参数 ")
            )
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.presentation.t('arg_error')}: {message}\n")


def split_config(argv: list[str]) -> tuple[Path | None, list[str]]:
    path = None
    result = []
    index = 0
    while index < len(argv):
        token = argv[index]
        if token in ("compose", "--"):
            result.extend(argv[index:])
            break
        if token == "--config":
            index += 1
            if index >= len(argv):
                raise InfraError("invalid_config|--config")
            path = Path(argv[index])
        elif token.startswith("--config="):
            path = Path(token.partition("=")[2])
        else:
            result.append(token)
        index += 1
    return path, result


def catalog(presentation: Presentation):
    root = Parser(prog="dev-infra", description=presentation.t("title"), presentation=presentation)
    root.add_argument(
        "--version", action="version", version=__version__, help=presentation.t("version_arg")
    )
    root.add_argument("--config", help=presentation.t("preferences_arg"))
    commands = root.add_subparsers(dest="command", metavar=presentation.t("command"))
    parsers = {}
    for name in (
        "list",
        "show",
        "start",
        "stop",
        "restart",
        "remove",
        "logs",
        "check",
        "upgrade",
        "config",
        "data",
        "self",
        "compose",
        "help",
    ):
        command = commands.add_parser(
            name,
            help=presentation.t(name),
            description=presentation.t(name),
            presentation=presentation,
        )
        parsers[name] = command
        if name in (
            "list",
            "show",
            "start",
            "stop",
            "restart",
            "remove",
            "logs",
            "check",
            "upgrade",
        ):
            command.add_argument(
                "services",
                nargs="*",
                metavar=presentation.t("service"),
                help=presentation.t("services_arg"),
            )
        if name not in ("logs", "compose", "help"):
            command.add_argument("--json", action="store_true", help=presentation.t("json_arg"))
        if name == "show":
            command.add_argument(
                "--secrets", action="store_true", help=presentation.t("secrets_arg")
            )
            command.add_argument("--open", action="store_true", help=presentation.t("open_arg"))
        elif name == "logs":
            command.add_argument(
                "-f", "--follow", action="store_true", help=presentation.t("follow_arg")
            )
            command.add_argument(
                "-n", "--tail", type=int, default=200, help=presentation.t("tail_arg")
            )
        elif name == "check":
            command.add_argument(
                "--updates", action="store_true", help=presentation.t("updates_arg")
            )
        elif name == "upgrade":
            command.add_argument("--to", help=presentation.t("to_arg"))
            command.add_argument("--dry-run", action="store_true", help=presentation.t("dry_arg"))
            choice = command.add_mutually_exclusive_group()
            choice.add_argument(
                "--no-backup",
                dest="backup",
                action="store_false",
                default=None,
                help=presentation.t("no_backup_arg"),
            )
            choice.add_argument(
                "--backup", dest="backup", action="store_true", help=presentation.t("backup_arg")
            )
        elif name == "config":
            command.add_argument(
                "action",
                nargs="?",
                choices=("show", "edit", "check"),
                default="show",
                metavar=presentation.t("action"),
                help=presentation.t("config_actions"),
            )
            choice = command.add_mutually_exclusive_group()
            choice.add_argument(
                "--instance", action="store_true", help=presentation.t("instance_arg")
            )
            choice.add_argument(
                "--versions", action="store_true", help=presentation.t("versions_arg")
            )
        elif name == "data":
            command.add_argument(
                "action",
                nargs="?",
                choices=("list", "prune", "backup", "reset"),
                default="list",
                metavar=presentation.t("action"),
                help=presentation.t("data_actions"),
            )
            command.add_argument(
                "services",
                nargs="*",
                metavar=presentation.t("service"),
                help=presentation.t("services_arg"),
            )
            command.add_argument("--dry-run", action="store_true", help=presentation.t("dry_arg"))
            command.add_argument("--yes", action="store_true", help=presentation.t("yes_arg"))
        elif name == "self":
            command.add_argument(
                "action",
                nargs="?",
                choices=("status", "update"),
                default="status",
                metavar=presentation.t("action"),
                help=presentation.t("self_actions"),
            )
            command.add_argument("--source", help=presentation.t("source_arg"))
        elif name == "compose":
            command.add_argument("arguments", nargs=argparse.REMAINDER)
        elif name == "help":
            command.add_argument("topic", nargs="?", choices=tuple(parsers)[:-1])
    return root, parsers


def config_command(args, preferences, presentation):
    if args.instance or args.versions:
        root = (
            Path(rf"\\wsl.localhost\{preferences.distro}\opt\dev-infra")
            if os.name == "nt"
            else ROOT
        )
        path = root / ("versions.local.env" if args.versions else ".env")
        initial = (
            "# 本机版本覆盖；使用 upgrade 自动更新。\n"
            if args.versions
            else (root / ".env.example").read_text(encoding="utf-8")
        )
        if args.action == "edit":
            settings.edit(path, preferences, initial)
        instance = Instance(root)
        values = (
            instance.overrides
            if args.versions
            else {
                key: "***" if any(part in key for part in ("PASSWORD", "SECRET")) else value
                for key, value in instance.values.items()
                if key not in instance.overrides
            }
        )
        payload = {"path": str(path), "exists": path.exists(), "values": values, "state": "ok"}
        if args.json:
            presentation.output(payload, True)
        else:
            print(f"{presentation.t('path')}: {path}")
            if args.action != "check":
                print("\n".join(f"{key}={value}" for key, value in values.items()))
            else:
                print(presentation.t("ok"))
        return 0
    if args.action == "edit":
        settings.edit(preferences.path, preferences, settings.TEMPLATE)
        preferences = settings.load(preferences.path)
    payload = {
        "path": str(preferences.path),
        "exists": preferences.path.exists(),
        "values": preferences.data(),
        "state": "ok",
    }
    if args.json:
        presentation.output(payload, True)
    else:
        print(f"{presentation.t('path')}: {preferences.path}")
        print(presentation.t("ok") if args.action == "check" else settings.render(preferences))
    return 0


def dispatch(args, preferences, presentation, docker):
    targets = resolve(args.services) if hasattr(args, "services") else []
    if args.command == "list":
        payload = operations.overview(docker, targets)
    elif args.command == "show":
        payload = operations.details(docker, targets, secrets=args.secrets, open_page=args.open)
        payload["details"] = True
    elif args.command in ("start", "stop", "restart", "remove"):
        payload = operations.lifecycle(docker, preferences, args.command, targets)
    elif args.command == "logs":
        docker.require()
        docker.compose(
            "logs",
            "--tail",
            str(args.tail),
            *(["-f"] if args.follow else []),
            *targets,
            capture=False,
            timeout=None,
        )
        return 0
    elif args.command == "check":
        payload = (
            planning.plan(docker, Registry(), targets, to=None, backup=False)
            if args.updates
            else operations.check(docker)
        )
        if args.updates:
            payload["mode"] = "check"
    elif args.command == "upgrade":
        docker.require()
        proposal = planning.plan(
            docker,
            Registry(),
            targets,
            to=args.to,
            backup=preferences.backup if args.backup is None else args.backup,
        )
        if args.dry_run or not proposal["complete"] or proposal["blocked"]:
            presentation.output(proposal, args.json)
            return 1 if not proposal["complete"] or proposal["blocked"] else 0
        payload = operations.upgrade(docker, preferences, proposal)
    elif args.command == "data":
        docker.require()
        if args.action == "backup":
            targets = (
                ["mysql", "postgres"] if not args.services or args.services == ["all"] else targets
            )
            with docker.instance.lock():
                records = data.backup(docker, targets)
                payload = {
                    "backups": records,
                    "complete": all(r["state"] == "complete" for r in records),
                }
        elif args.action == "reset":
            payload = operations.reset(
                docker, preferences, targets, dry_run=args.dry_run, yes=args.yes
            )
        else:
            payload = {"volumes": data.volumes(docker, targets), "complete": True}
            if args.action == "prune" and not args.dry_run:
                if not args.yes:
                    raise InfraError("confirm_required")
                with docker.instance.lock():
                    payload["removed"] = data.prune(docker, payload["volumes"])
    elif args.command == "compose":
        docker.require()
        docker.compose(*args.arguments, capture=False, timeout=None)
        return 0
    else:
        raise InfraError("unknown_command")
    presentation.output(payload, args.json)
    return 0 if payload.get("complete", True) else 1


def forward(argv: list[str], preferences) -> int | None:
    if os.name != "nt":
        return None
    command = [
        "wsl.exe",
        "-d",
        preferences.distro,
        "-u",
        "root",
        "--exec",
        "env",
        f"DEV_INFRA_TRANSPORT_LANGUAGE={preferences.language}",
        f"DEV_INFRA_WAIT_TIMEOUT={preferences.wait_timeout}",
        f"DEV_INFRA_BACKUP={str(preferences.backup).lower()}",
        "/usr/local/bin/dev-infra",
        *argv,
    ]
    return subprocess.run(command, check=False).returncode


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    presentation = Presentation("zh")
    try:
        path, forwarded = split_config(argv)
        try:
            preferences = settings.load(path)
        except InfraError:
            if forwarded[:2] != ["config", "edit"]:
                raise
            preferences = settings.Settings((path or settings.default_path()).resolve())
        language = os.environ.get("DEV_INFRA_TRANSPORT_LANGUAGE", preferences.language)
        presentation = Presentation(language if language in ("zh", "en") else preferences.language)
        if sys.version_info[:2] != (3, 14):
            raise InfraError("python_required")
        parser, parsers = catalog(presentation)
        args = parser.parse_args(forwarded)
        args.command = args.command or "list"
        if args.command == "help":
            (parsers[args.topic] if args.topic else parser).print_help()
            return 0
        if args.command == "list" and not hasattr(args, "services"):
            args.services, args.json = [], False
        if hasattr(args, "services"):
            targets = resolve(args.services)
            if args.command == "upgrade" and args.to:
                if len(targets) != 1:
                    parser.error(presentation.t("one_target"))
                numbers(args.to)
            if args.command == "data" and args.action == "reset" and len(targets) != 1:
                parser.error(presentation.t("one_target"))
        if args.command == "logs" and args.tail < 0:
            parser.error(presentation.t("tail_arg"))
        if (
            args.command == "data"
            and args.action in ("list", "backup")
            and (args.yes or args.dry_run)
        ):
            parser.error(presentation.t("incompatible_options"))
        if (
            args.command == "data"
            and args.action == "backup"
            and args.services
            and args.services != ["all"]
            and any(name not in ("mysql", "postgres") for name in targets)
        ):
            parser.error(presentation.t("db_only"))
        if args.command == "self" and args.action == "status" and args.source:
            parser.error(presentation.t("incompatible_options"))
        if (
            args.command == "show"
            and args.open
            and (len(targets) != 1 or targets[0] not in ("s3", "mailpit"))
        ):
            parser.error(presentation.t("web_unavailable"))
        if args.command == "config":
            return config_command(args, preferences, presentation)
        if args.command == "self":
            presentation.output(
                operations.self_command(args.action, args.source, preferences), args.json
            )
            return 0
        remote = forward(forwarded, preferences)
        if remote is not None:
            return remote
        preferences.wait_timeout = int(
            os.environ.get("DEV_INFRA_WAIT_TIMEOUT", preferences.wait_timeout)
        )
        preferences.backup = (
            os.environ.get("DEV_INFRA_BACKUP", str(preferences.backup).lower()) == "true"
        )
        return dispatch(args, preferences, presentation, Docker(Instance(ROOT)))
    except (InfraError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(presentation.error(exc), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
