"""Load build-script argument defaults from build_config.toml."""

from __future__ import annotations

import argparse
import tomllib
from pathlib import Path


DEFAULT_CONFIG = Path(__file__).with_name("build_config.toml")


def apply_config(parser: argparse.ArgumentParser, section: str) -> None:
    """Use top-level keys and the ``[section]`` table as argument defaults.

    Keys are option names without the leading dashes. Relative paths resolve
    against the config file's directory. Command-line arguments still win.
    """
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help="TOML file providing argument defaults (default: %(default)s)",
    )
    preparser = argparse.ArgumentParser(add_help=False)
    preparser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    config_path: Path = preparser.parse_known_args()[0].config.resolve()
    if not config_path.is_file():
        if config_path != DEFAULT_CONFIG.resolve():
            parser.error(f"config file not found: {config_path}")
        return

    data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    section_values = data.get(section, {})
    values = {key: value for key, value in data.items() if not isinstance(value, dict)}
    values.update(section_values)

    actions = {action.dest: action for action in parser._actions}
    defaults = {}
    for key, value in values.items():
        action = actions.get(key.replace("-", "_"))
        if action is None or action.dest in {"help", "config"}:
            if key in section_values:
                parser.error(f"unknown option {key!r} in [{section}] of {config_path}")
            continue
        if action.type is Path:
            value = config_path.parent / value
        action.required = False
        defaults[action.dest] = value
    for group in parser._mutually_exclusive_groups:
        if any(action.dest in defaults for action in group._group_actions):
            group.required = False
    parser.set_defaults(**defaults)
