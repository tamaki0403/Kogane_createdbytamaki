"""Versioned tournament configuration loaded from repository JSON files.

Tournament progression remains in bot.py.  These files only describe one
supported OTP-style tournament, so adding an event does not require copying
the progression code or hard-coding another set of Discord IDs.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


CONFIG_DIR = Path(__file__).with_name("tournaments")
SUPPORTED_FORMAT = "otp_round_robin_single_elimination"


def _validate_config(config: dict[str, Any], filename: str) -> None:
    if config.get("format") != SUPPORTED_FORMAT:
        raise ValueError(
            f"{filename}: unsupported format {config.get('format')!r}"
        )
    qualifier = config.get("qualifier", {})
    if qualifier.get("group_sizes") != [3, 4]:
        raise ValueError(f"{filename}: the current format requires group_sizes [3, 4]")
    if qualifier.get("section_labels") != ["A", "B", "C", "D"]:
        raise ValueError(f"{filename}: the current Web layout requires sections A-D")
    if qualifier.get("upper_places") != [1, 2]:
        raise ValueError(f"{filename}: the current progression requires upper places 1 and 2")
    if config.get("bracket", {}).get("type") != "single_elimination":
        raise ValueError(f"{filename}: the current format requires single elimination")
    default_members = int(config.get("team_members", 4))
    min_members = int(config.get("min_team_members", default_members))
    max_members = int(config.get("max_team_members", default_members))
    if min_members < 1 or max_members < min_members or max_members > 4:
        raise ValueError(f"{filename}: team member range must be within 1..4")


def load_tournament_configs(config_dir: Path = CONFIG_DIR) -> dict[str, dict[str, Any]]:
    configs: dict[str, dict[str, Any]] = {}
    if not config_dir.exists():
        return configs
    for path in sorted(config_dir.glob("*.json")):
        with path.open("r", encoding="utf-8") as file:
            config = json.load(file)
        tournament_id = str(config.get("id") or "").strip()
        if not tournament_id:
            raise ValueError(f"{path.name}: id is required")
        if tournament_id in configs:
            raise ValueError(f"duplicate tournament id: {tournament_id}")
        _validate_config(config, path.name)
        configs[tournament_id] = config
    return configs


def get_active_tournament_config(
    configs: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    available = configs if configs is not None else load_tournament_configs()
    active = [config for config in available.values() if config.get("active_operator_panel")]
    if len(active) != 1:
        raise ValueError(
            "exactly one tournament config must set active_operator_panel=true"
        )
    return active[0]


def get_operator_panel_configs(
    configs: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Return every event that should maintain its own Discord control panel."""
    available = configs if configs is not None else load_tournament_configs()
    return [
        config
        for config in available.values()
        if config.get("active_operator_panel")
    ]


def get_main_tournament_config(
    configs: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return the production event without conflating it with rehearsal panels."""
    available = configs if configs is not None else load_tournament_configs()
    main = [config for config in available.values() if config.get("kind") == "main"]
    if len(main) != 1:
        raise ValueError("exactly one tournament config must set kind=main")
    return main[0]
