"""One command catalog for parsing, help, validation and dispatch."""

import argparse
import contextlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from . import ROOT, InfraError, __version__, data, operations, planning, settings
from .catalog import SERVICES, resolve
from .docker import Docker, compose_is_query
from .instance import Instance
from .presentation import JSON_SCHEMA_VERSION, Presentation
from .registry import Registry, numbers


@dataclass(frozen=True)
class Command:
    name: str
    group: str
    services: bool = False
    json: bool = True
    summary: str | None = None


COMMANDS = (
    Command("list", "common_commands", services=True),
    Command("show", "common_commands", services=True),
    Command("start", "common_commands", services=True),
    Command("stop", "common_commands", services=True),
    Command("restart", "common_commands", services=True),
    Command("logs", "common_commands", services=True, json=False),
    Command("check", "advanced_commands", services=True),
    Command("upgrade", "advanced_commands", services=True),
    Command("remove", "advanced_commands", services=True),
    Command("data", "advanced_commands", summary="data_summary"),
    Command("compose", "advanced_commands", json=False),
    Command("config", "auxiliary_commands", summary="config_summary"),
    Command("self", "auxiliary_commands", summary="self_summary"),
    Command("help", "auxiliary_commands", json=False),
)
ARGUMENT_ERRORS = {
    "invalid_arguments",
    "unknown_service",
    "invalid_version",
    "one_target",
    "incompatible_options",
    "updates_options_required",
    "db_only",
    "web_unavailable",
}


class Parser(argparse.ArgumentParser):
    def __init__(self, *args, presentation=None, **kwargs):
        self.presentation = presentation or Presentation("zh")
        kwargs.setdefault("allow_abbrev", False)
        kwargs.setdefault("formatter_class", argparse.RawDescriptionHelpFormatter)
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
        raise InfraError("invalid_arguments|" + message)


def json_requested(argv: list[str]) -> bool:
    """Recognize the output switch before parsing, including invalid configurations."""
    command = None
    skip_value = False
    requested = False
    for token in argv:
        if skip_value:
            skip_value = False
            if not token.startswith("-"):
                continue
        if token == "--":
            break
        if token in ("--config", "--source", "--to", "--tail", "-n"):
            skip_value = True
        elif token in ("-h", "--help", "-v", "--version"):
            return False
        elif token == "--json":
            requested = True
        elif command is None and not token.startswith("-"):
            command = token
            if command in ("logs", "compose", "help"):
                return False
    return requested


def result_code(payload: dict) -> int:
    return (
        1
        if payload.get("complete") is False
        or payload.get("blocked")
        or payload.get("state") == "error"
        else 0
    )


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
                raise InfraError("invalid_arguments|--config requires a path")
            if argv[index].startswith("-"):
                raise InfraError("invalid_arguments|--config requires a path")
            path = Path(argv[index])
        elif token.startswith("--config="):
            if not token.partition("=")[2]:
                raise InfraError("invalid_arguments|--config requires a path")
            path = Path(token.partition("=")[2])
        else:
            result.append(token)
        index += 1
    return path, result


def catalog(presentation: Presentation):
    root = Parser(prog="dev-infra", description=presentation.t("title"), presentation=presentation)
    root.add_argument(
        "-v",
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
        help=presentation.t("version_arg"),
    )
    root.add_argument(
        "--config", metavar=presentation.t("path"), help=presentation.t("preferences_arg")
    )
    commands = root.add_subparsers(
        dest="command",
        metavar=presentation.t("command"),
        help=presentation.t("command_arg"),
    )
    parsers = {}
    groups = {}
    for definition in COMMANDS:
        name = definition.name
        groups.setdefault(definition.group, []).append(
            (name, presentation.t(definition.summary or name))
        )
        command = commands.add_parser(
            name,
            description=presentation.t(name),
            presentation=presentation,
        )
        parsers[name] = command
        if definition.services:
            command.add_argument(
                "services",
                nargs="*",
                metavar=presentation.t("service"),
                help=presentation.t("services_arg"),
            )
        if definition.json:
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
        elif name in ("check", "upgrade"):
            if name == "check":
                command.add_argument(
                    "--updates", action="store_true", help=presentation.t("updates_arg")
                )
            command.add_argument("--to", help=presentation.t("to_arg"))
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
            command.add_argument("--yes", action="store_true", help=presentation.t("yes_arg"))
        elif name == "self":
            command.add_argument(
                "action",
                nargs="?",
                choices=("status", "update", "upgrade"),
                default="status",
                metavar=presentation.t("action"),
                help=presentation.t("self_actions"),
            )
            command.add_argument(
                "--source", metavar=presentation.t("path"), help=presentation.t("source_arg")
            )
        elif name == "compose":
            command.add_argument("arguments", nargs=argparse.REMAINDER)
        elif name == "help":
            command.add_argument(
                "topic",
                nargs="?",
                choices=tuple(item.name for item in COMMANDS if item.name != "help"),
                metavar=presentation.t("command"),
                help=presentation.t("help_topic_arg"),
            )
    lines = []
    for group, entries in groups.items():
        lines.append(presentation.t(group) + ":")
        lines.extend(f"  {name:<12} {description}" for name, description in entries)
        lines.append("")
    lines.extend((presentation.t("help_usage"), presentation.t("help_examples")))
    root.epilog = "\n".join(lines)
    return root, parsers


def instance_root(preferences):
    return Path(rf"\\wsl.localhost\{preferences.distro}\opt\dev-infra") if os.name == "nt" else ROOT


def config_command(args, preferences, presentation):
    if args.instance or args.versions:
        root = instance_root(preferences)
        path = root / ("versions.local.env" if args.versions else ".env")
        initial = (
            "# 本机版本覆盖；使用 upgrade 自动更新。\n"
            if args.versions
            else (root / ".env.example").read_text(encoding="utf-8")
        )
        if args.action == "edit":
            settings.edit(
                path, preferences, initial, **({"stdout": sys.stderr} if args.json else {})
            )
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
        settings.edit(
            preferences.path,
            preferences,
            settings.TEMPLATE,
            **({"stdout": sys.stderr} if args.json else {}),
        )
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
    elif args.command == "check" and not args.updates:
        payload = operations.check(docker)
    elif args.command in ("check", "upgrade"):
        docker.require()
        proposal = planning.plan(
            docker,
            Registry(),
            targets,
            to=args.to,
            backup=preferences.backup if args.backup is None else args.backup,
        )
        if args.command == "check":
            proposal["mode"] = "check"
        if args.command == "check" or not proposal["complete"] or proposal["blocked"]:
            presentation.output(proposal, args.json)
            return result_code(proposal)
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
            payload = operations.reset(docker, preferences, targets, yes=args.yes)
        else:
            payload = {"volumes": data.volumes(docker, targets), "complete": True}
            if args.action == "prune":
                if not args.yes:
                    raise InfraError("confirm_required")
                with docker.instance.lock():
                    payload["removed"] = data.prune(docker, payload["volumes"])
    elif args.command == "compose":
        docker.require()
        with (
            contextlib.nullcontext() if compose_is_query(args.arguments) else docker.instance.lock()
        ):
            docker.compose(*args.arguments, capture=False, timeout=None)
        return 0
    else:
        raise InfraError("unknown_command")
    presentation.output(payload, args.json)
    return result_code(payload)


def forward(argv: list[str], preferences, *, json_stream=None) -> int | None:
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
    if not json_requested(argv):
        return subprocess.run(command, check=False).returncode
    result = subprocess.run(
        command, check=False, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    try:
        payload = json.loads(result.stdout)
        if (
            not isinstance(payload, dict)
            or type(payload.get("schema_version")) is not int
            or payload["schema_version"] != JSON_SCHEMA_VERSION
            or result.returncode not in (0, 1, 2, 130)
            or result.returncode != 0
            and (
                not isinstance(payload.get("error"), dict)
                or not isinstance(payload["error"].get("code"), str)
                or not isinstance(payload["error"].get("message"), str)
                or not isinstance(payload["error"].get("details"), dict)
            )
        ):
            raise ValueError("Invalid backend result")
    except TypeError, ValueError:
        raise InfraError("transport_failed") from None
    print(json.dumps(payload, ensure_ascii=False, indent=2), file=json_stream)
    return result.returncode


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    as_json = json_requested(argv)
    json_stream = sys.stdout
    with contextlib.redirect_stdout(sys.stderr) if as_json else contextlib.nullcontext():
        return run_main(argv, as_json=as_json, json_stream=json_stream)


def run_main(argv: list[str], *, as_json: bool, json_stream) -> int:
    presentation = Presentation("zh", json_stream=json_stream)
    instance = None
    try:
        path, forwarded = split_config(argv)
        try:
            preferences = settings.load(path)
        except InfraError:
            if forwarded[:2] != ["config", "edit"]:
                raise
            preferences = settings.Settings((path or settings.default_path()).resolve())
        language = os.environ.get("DEV_INFRA_TRANSPORT_LANGUAGE", preferences.language)
        presentation = Presentation(
            language if language in ("zh", "en") else preferences.language, json_stream=json_stream
        )
        if sys.version_info[:2] != (3, 14):
            raise InfraError("python_required")
        parser, parsers = catalog(presentation)
        args = parser.parse_args(forwarded or ["help"])
        if args.command == "help":
            (parsers[args.topic] if args.topic else parser).print_help()
            return 0
        if hasattr(args, "services"):
            targets = resolve(args.services)
            if args.command in ("check", "upgrade") and args.to is not None:
                if len(targets) != 1:
                    raise InfraError("one_target")
                parts = len(numbers(args.to))
                service = SERVICES[targets[0]]
                if parts > service.scope_parts and parts != service.release_parts:
                    raise InfraError(f"invalid_version|{args.to}")
            if args.command == "data" and args.action == "reset" and len(targets) != 1:
                raise InfraError("one_target")
        if args.command == "logs" and args.tail < 0:
            raise InfraError("invalid_arguments|--tail must be nonnegative")
        if (
            args.command == "check"
            and not args.updates
            and (args.to is not None or args.backup is not None)
        ):
            raise InfraError("updates_options_required")
        if args.command == "data" and args.action in ("list", "backup") and args.yes:
            raise InfraError("incompatible_options")
        if args.command == "data" and args.action in ("reset", "prune") and not args.yes:
            raise InfraError("confirm_required")
        if (
            args.command == "data"
            and args.action == "backup"
            and args.services
            and args.services != ["all"]
            and any(name not in ("mysql", "postgres") for name in targets)
        ):
            raise InfraError("db_only")
        if args.command == "self" and args.action == "status" and args.source:
            raise InfraError("incompatible_options")
        if (
            args.command == "show"
            and args.open
            and (len(targets) != 1 or targets[0] not in ("s3", "mailpit"))
        ):
            raise InfraError("web_unavailable")
        if args.command == "config":
            return config_command(args, preferences, presentation)
        if args.command == "self":
            payload = operations.self_command(args.action, args.source, preferences)
            presentation.output(payload, args.json)
            return result_code(payload)
        remote = forward(forwarded, preferences, json_stream=json_stream)
        if remote is not None:
            return remote
        preferences.wait_timeout = int(
            os.environ.get("DEV_INFRA_WAIT_TIMEOUT", preferences.wait_timeout)
        )
        preferences.backup = (
            os.environ.get("DEV_INFRA_BACKUP", str(preferences.backup).lower()) == "true"
        )
        instance = Instance(ROOT)
        return dispatch(args, preferences, presentation, Docker(instance))
    except (InfraError, OSError, ValueError, subprocess.SubprocessError) as exc:
        if isinstance(exc, subprocess.TimeoutExpired):
            exc = InfraError("command_timeout")
        elif isinstance(exc, subprocess.SubprocessError):
            exc = InfraError("command_failed")
        diagnostic = operations._upgrade_error(exc, instance or SimpleNamespace(values={}))
        code, detail = diagnostic["code"], diagnostic["message"]
        if detail.startswith(code + "|"):
            detail = detail.partition("|")[2]
        if detail == code:
            detail = ""
        if code == "invalid_arguments" and presentation.language == "zh" and not as_json:
            detail = (
                detail.replace("unrecognized arguments:", "无法识别的参数：")
                .replace("invalid choice:", "无效选项：")
                .replace("choose from", "可选值")
                .replace("expected one argument", "需要一个参数")
                .replace("the following arguments are required:", "缺少必需参数：")
                .replace("argument ", "参数 ")
            )
        presentation.failure(code, detail, as_json=as_json)
        return 2 if code in ARGUMENT_ERRORS else 1
    except KeyboardInterrupt:
        presentation.failure("operation_interrupted", "", as_json=as_json)
        return 130
