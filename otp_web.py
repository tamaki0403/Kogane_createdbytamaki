"""Read-only OTP tournament projection shared by the Bot API and local preview.

This module does not advance a tournament.  It only translates the persisted
Bot state into public display data and intentionally omits Discord IDs,
operator IDs, channel IDs, and pending report contents.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import json
import os
import random


PUBLIC_RULES = [
    "全試合ガチエリアです。",
    "通常の対戦はBO3、決勝はBO5です。",
    "使用ブキは2026 Sizzle Seasonの個人使用率TOP3です。",
    "開始前または開始後15秒以内の回線落ちは、同じステージ・ブキ・ギアで再試合します。",
    "15秒を超えた回線落ちは原則続行です。",
    "判断に迷う場合はDiscordで運営に相談してください。",
]


_PUBLIC_LAYOUT_FIXTURES = {
    "all-teams-layout-test": os.path.join(
        os.path.dirname(__file__), "web", "fixtures", "all-teams-layout-test.json"
    ),
}

APPLICATION_LAYOUT_TOURNAMENT_ID = "all-teams-layout-test"


def load_public_layout_fixture(tournament_id: str) -> dict[str, Any] | None:
    """Load an explicitly named, sanitized layout test without touching Bot state."""
    path = _PUBLIC_LAYOUT_FIXTURES.get(tournament_id)
    if not path:
        return None
    try:
        with open(path, "r", encoding="utf-8") as file:
            fixture = json.load(file)
    except (OSError, json.JSONDecodeError):
        return None
    if fixture.get("tournament_id") != tournament_id:
        return None
    fixture["data_mode"] = "layout_test"
    fixture["live_updates"] = False
    return fixture


def list_public_layout_fixtures() -> list[dict[str, Any]]:
    result = []
    for tournament_id in _PUBLIC_LAYOUT_FIXTURES:
        fixture = load_public_layout_fixture(tournament_id)
        if not fixture:
            continue
        result.append({
            "tournament_id": tournament_id,
            "tournament_name": fixture.get("tournament_name") or "Kogane OTP杯",
            "status": fixture.get("status", "setup"),
            "phase": fixture.get("phase", "setup"),
            "updated_at": fixture.get("updated_at", ""),
            "data_mode": "layout_test",
        })
    return result


def qualifier_group_sizes(team_count: int) -> list[int] | None:
    """Return the existing Bot's preferred 4-team/3-team qualifier composition."""
    for four_count in range(team_count // 4, -1, -1):
        rest = team_count - four_count * 4
        if rest % 3 == 0:
            return [4] * four_count + [3] * (rest // 3)
    return None


def qualifier_section_counts(group_count: int) -> list[int]:
    """Distribute qualifier groups across the four fixed A-D sections."""
    base, extra = divmod(group_count, 4)
    counts = [base] * 4
    for index in (0, 2, 1, 3)[:extra]:
        counts[index] += 1
    return counts


def balanced_qualifier_group_sizes(team_count: int) -> list[int] | None:
    """Order 3/4-team groups so the fixed A-D section totals stay balanced."""
    sizes = qualifier_group_sizes(team_count)
    if sizes is None:
        return None
    counts = qualifier_section_counts(len(sizes))
    sections = [[4] * count for count in counts]
    three_count = sizes.count(3)
    for _ in range(three_count):
        candidates = [
            (sum(section), len(section), -index, index)
            for index, section in enumerate(sections)
            if 4 in section
        ]
        if not candidates:
            return None
        section_index = max(candidates)[-1]
        replace_index = sections[section_index].index(4)
        sections[section_index][replace_index] = 3
    return [size for section in sections for size in section]


def qualifier_section_label(group_index: int, group_count: int) -> str:
    """Return the fixed A-D section containing a one-based qualifier group."""
    cursor = 0
    for section_index, count in enumerate(qualifier_section_counts(group_count)):
        cursor += count
        if group_index <= cursor:
            return chr(ord("A") + section_index)
    return "D"


def application_layout_seed(state: dict, application_numbers: list[int]) -> str:
    """Return the persisted application draw seed, with a stable legacy fallback."""
    stored = state.get("otp_application_layout_seed")
    if stored is not None:
        return str(stored)
    return "otp-application-layout-initial:" + ",".join(
        str(number) for number in sorted(application_numbers)
    )


def build_seeded_qualifier_blocks(
    team_keys: list[str], application_number_by_key: dict[str, int], seed: str
) -> list[list[str]] | None:
    """Build the one canonical draw shared by the Web preview and Discord start."""
    sizes = balanced_qualifier_group_sizes(len(team_keys))
    if not sizes:
        return None
    shuffled = sorted(
        team_keys,
        key=lambda key: (application_number_by_key.get(key, 999999), key),
    )
    random.Random(str(seed)).shuffle(shuffled)
    blocks = []
    offset = 0
    for size in sizes:
        blocks.append(shuffled[offset:offset + size])
        offset += size
    return blocks


def build_single_elimination_slots(team_keys: list[str], rng=None) -> tuple[list[str | None], set[str]]:
    """Keep first-round pairs valid and spread played matches across the bracket."""
    if len(team_keys) <= 1:
        return team_keys[:], set()
    randomizer = rng or random
    size = 1
    while size < len(team_keys):
        size *= 2
    shuffled = team_keys[:]
    randomizer.shuffle(shuffled)
    if size == 2:
        return shuffled, set()
    bye_count = size - len(team_keys)
    bye_teams = shuffled[:bye_count]
    remaining = shuffled[bye_count:]
    single_pairs = []
    for team in bye_teams:
        pair = [team, None]
        randomizer.shuffle(pair)
        single_pairs.append(pair)
    match_pairs = []
    for index in range(0, len(remaining), 2):
        match_pairs.append(remaining[index:index + 2])

    # Each two source pairs feed one second-round card.  Distributing played
    # matches avoids a long block of seed-only rows followed by all matches.
    source_pair_count = size // 2
    second_round_count = max(1, size // 4)
    match_positions: list[int] = []
    if match_pairs:
        if len(match_pairs) <= second_round_count:
            match_positions = [
                min(second_round_count - 1, index * second_round_count // len(match_pairs)) * 2 + 1
                for index in range(len(match_pairs))
            ]
        else:
            match_positions = list(range(1, source_pair_count, 2))
            match_positions.extend(index for index in range(0, source_pair_count, 2))
            match_positions = match_positions[:len(match_pairs)]

    pairs: list[list[str | None] | None] = [None] * source_pair_count
    randomizer.shuffle(match_pairs)
    for position, pair in zip(match_positions, match_pairs):
        pairs[position] = pair
    randomizer.shuffle(single_pairs)
    singles = iter(single_pairs)
    for index, pair in enumerate(pairs):
        if pair is None:
            pairs[index] = next(singles)
    return [team for pair in pairs for team in pair], set(bye_teams)


def rank_qualifier_group(tournament: dict, group_index: int) -> list[str]:
    """The existing Bot tie-break order, factored for the public projection."""
    group_teams = tournament.get("blocks", [])[group_index - 1]
    teams = tournament.get("teams", {})
    stats = {
        team: {
            "match_wins": 0,
            "battle_wins": 0,
            "battle_losses": 0,
            "order": teams.get(team, {}).get("application_number") or 999999,
        }
        for team in group_teams
    }
    direct: dict[frozenset, str] = {}
    for match in tournament.get("matches", {}).values():
        if match.get("phase") != "qualifier" or match.get("block") != group_index or match.get("status") != "done":
            continue
        pair = match.get("teams", [])
        if len(pair) != 2 or pair[0] not in stats or pair[1] not in stats:
            continue
        a, b = pair
        aw = int(match.get("wins", {}).get(a, 0))
        bw = int(match.get("wins", {}).get(b, 0))
        stats[a]["battle_wins"] += aw
        stats[a]["battle_losses"] += bw
        stats[b]["battle_wins"] += bw
        stats[b]["battle_losses"] += aw
        winner = a if aw > bw else b
        stats[winner]["match_wins"] += 1
        direct[frozenset((a, b))] = winner

    def base(team: str):
        stat = stats[team]
        return (-stat["match_wins"], -stat["battle_wins"], stat["battle_losses"], stat["order"])

    ranked = sorted(group_teams, key=base)
    changed = True
    while changed:
        changed = False
        for index in range(len(ranked) - 1):
            a, b = ranked[index], ranked[index + 1]
            sa, sb = stats[a], stats[b]
            score_a = (sa["match_wins"], sa["battle_wins"], sa["battle_losses"])
            score_b = (sb["match_wins"], sb["battle_wins"], sb["battle_losses"])
            tied = [team for team in group_teams if (
                stats[team]["match_wins"], stats[team]["battle_wins"], stats[team]["battle_losses"]
            ) == score_a]
            if score_a == score_b and len(tied) == 2 and direct.get(frozenset((a, b))) == b:
                ranked[index], ranked[index + 1] = b, a
                changed = True
    return ranked


def _stats(tournament: dict, group_index: int) -> dict[str, dict[str, int]]:
    keys = tournament.get("blocks", [])[group_index - 1]
    result = {key: {"match_wins": 0, "match_losses": 0, "battle_wins": 0, "battle_losses": 0} for key in keys}
    for match in tournament.get("matches", {}).values():
        if match.get("phase") != "qualifier" or match.get("block") != group_index or match.get("status") != "done":
            continue
        pair = match.get("teams", [])
        if len(pair) != 2 or any(key not in result for key in pair):
            continue
        a, b = pair
        aw, bw = int(match.get("wins", {}).get(a, 0)), int(match.get("wins", {}).get(b, 0))
        result[a]["battle_wins"] += aw
        result[a]["battle_losses"] += bw
        result[b]["battle_wins"] += bw
        result[b]["battle_losses"] += aw
        winner, loser = (a, b) if aw > bw else (b, a)
        result[winner]["match_wins"] += 1
        result[loser]["match_losses"] += 1
    return result


def _public_member(member: dict) -> dict:
    return {
        "role": member.get("role"),
        "name": member.get("player_name") or "未入力",
        "circle": member.get("circle") or None,
        "weapons": [weapon for weapon in member.get("weapons", []) if weapon],
    }


def _report_state(match: dict) -> str:
    if match.get("status") == "done":
        return "confirmed"
    if match.get("status") == "hold":
        return "on_hold"
    if match.get("status") == "disputed" or match.get("mismatch_count"):
        return "mismatch"
    return "one_sided" if len(match.get("reports", {})) == 1 else "none"


def _public_match(match: dict, placement_by_team: dict[str, str]) -> dict:
    pair = list(match.get("teams", []))
    done = match.get("status") == "done"
    confirmed_battle_score = [int(match.get("wins", {}).get(key, 0)) for key in pair]
    return {
        "match_id": match.get("id"),
        "phase": match.get("phase"),
        "round": match.get("round"),
        "group_index": match.get("block"),
        "team_ids": pair,
        "team_positions": [placement_by_team.get(key) for key in pair],
        "best_of": match.get("best_of"),
        "status": match.get("status", "waiting"),
        "report_state": _report_state(match),
        "checked_in": bool(match.get("checked_in_once")),
        "checkin_count": len(match.get("checkins", {})),
        "score": confirmed_battle_score if done else None,
        "confirmed_battle_score": confirmed_battle_score,
        "winner_team_id": match.get("winner") if done else None,
        "battles": [
            {
                "battle": battle.get("battle"),
                "stage": battle.get("stage"),
                "winner_team_id": battle.get("winner"),
            }
            for battle in match.get("battles", [])
        ],
    }


def _timestamp(tournament: dict) -> str:
    values = [tournament.get(key) for key in ("updated_at", "started_at", "finished_at", "paused_at", "resumed_at", "board_updated_at")]
    for team in tournament.get("teams", {}).values():
        values.extend((team.get("updated_at"), team.get("approved_at")))
    for match in tournament.get("matches", {}).values():
        values.append(match.get("finished_at"))
        values.extend(battle.get("decided_at") for battle in match.get("battles", []))
    value = max((float(item) for item in values if isinstance(item, (int, float))), default=0)
    return datetime.fromtimestamp(value, timezone.utc).isoformat() if value else ""


def build_public_tournament(tournament: dict) -> dict[str, Any]:
    """Create one internally consistent, read-only snapshot for the Web UI."""
    teams = tournament.get("teams", {})
    raw_groups = tournament.get("blocks", [])
    counts = qualifier_section_counts(len(raw_groups))
    placement_by_team: dict[str, str] = {}
    range_by_group: dict[int, str] = {}
    qualifier_sections = []
    group_cursor = 0

    for section_index, count in enumerate(counts):
        if not count:
            continue
        section_label = chr(ord("A") + section_index)
        section_groups = []
        placement_counter = 1
        for local_group in range(count):
            source_index = group_cursor + 1
            team_keys = raw_groups[group_cursor]
            group_stats = _stats(tournament, source_index)
            stored_ranking = tournament.get("block_rankings", {}).get(str(source_index))
            ranked = list(stored_ranking or rank_qualifier_group(tournament, source_index))
            rank_by_team = {key: index + 1 for index, key in enumerate(ranked)}
            group_matches = [
                match for match_id in tournament.get("match_order", [])
                for match in [tournament.get("matches", {}).get(match_id)]
                if match and match.get("phase") == "qualifier" and match.get("block") == source_index
            ]
            confirmed = bool(group_matches) and all(match.get("status") == "done" for match in group_matches)
            display_teams = []
            for key in sorted(team_keys, key=lambda item: teams.get(item, {}).get("application_number") or 999999):
                position = f"{section_label}{placement_counter}"
                placement_counter += 1
                placement_by_team[key] = position
                rank = rank_by_team.get(key)
                display_teams.append({
                    "team_id": key,
                    "position": position,
                    "rank": rank,
                    "record": group_stats.get(key, {}),
                    "advancement": ("upper" if rank and rank <= 2 else "lower") if confirmed else None,
                    "provisional_advancement": ("upper" if rank and rank <= 2 else "lower") if not confirmed else None,
                    "advancement_confirmed": confirmed,
                })
            section_groups.append({
                "group_id": f"{section_label}{local_group + 1}",
                "source_group_index": source_index,
                "section": section_label,
                "start_position": display_teams[0]["position"] if display_teams else None,
                "end_position": display_teams[-1]["position"] if display_teams else None,
                "complete_matches": sum(match.get("status") == "done" for match in group_matches),
                "total_matches": len(group_matches),
                "advancement_confirmed": confirmed,
                "teams": display_teams,
                "matches": [_public_match(match, placement_by_team) for match in group_matches],
            })
            if display_teams:
                range_by_group[source_index] = f"{display_teams[0]['position']}〜{display_teams[-1]['position']}"
            group_cursor += 1
        qualifier_sections.append({
            "block_id": section_label,
            "team_count": sum(len(group["teams"]) for group in section_groups),
            "groups": section_groups,
        })

    public_teams = {}
    for key, team in teams.items():
        public_teams[key] = {
            "team_id": key,
            "application_id": team.get("application_id"),
            "application_number": team.get("application_number"),
            "placement_number": placement_by_team.get(key),
            "name": team.get("team_name") or "未定",
            "registration_type": team.get("registration_type") or (
                "test" if team.get("solo_test") or not any(member.get("discord_id") for member in team.get("members", [])) else "official"
            ),
            "members": [_public_member(member) for member in team.get("members", [])],
        }

    matches = [_public_match(match, placement_by_team) for match in tournament.get("matches", {}).values()]
    brackets = {}
    for bracket_name in ("upper", "lower"):
        bracket = tournament.get("brackets", {}).get(bracket_name)
        if not bracket:
            brackets[bracket_name] = None
            continue
        slots = list(bracket.get("slots", []))
        slot_sources = []
        for source in bracket.get("slot_sources", []):
            if not source:
                slot_sources.append(None)
                continue
            group_index = int(source.get("source_group_index", 0) or 0)
            rank = int(source.get("rank", 0) or 0)
            source_range = range_by_group.get(group_index) or source.get("range") or "予選"
            slot_sources.append({
                "source_group_index": group_index,
                "rank": rank,
                "label": source.get("label") or f"{source_range}・{rank}位",
            })
        bracket_matches = [match for match in matches if match.get("phase") == bracket_name]
        brackets[bracket_name] = {
            "league": bracket_name,
            "active_team_count": bracket.get("active_team_count", sum(bool(slot) for slot in slots)),
            "initial_slots": slots,
            "slot_sources": slot_sources,
            "auto_advancers": list(bracket.get("auto_advancers", [])),
            "matches": bracket_matches,
            "progression_complete": any((match.get("round") or 0) > 1 for match in bracket_matches),
        }

    return {
        "tournament_id": tournament.get("id"),
        "tournament_name": tournament.get("name") or "Kogane OTP杯",
        "status": tournament.get("status", "setup"),
        "phase": tournament.get("phase", "setup"),
        "updated_at": _timestamp(tournament),
        "team_count": sum(len(group) for group in raw_groups),
        "group_count": len(raw_groups),
        "qualifier_blocks": qualifier_sections,
        "teams": public_teams,
        "matches": matches,
        "upper_bracket": brackets["upper"],
        "lower_bracket": brackets["lower"],
        "rules": PUBLIC_RULES,
        "capabilities": {
            "result_correction": False,
            "bracket_progression": bool(brackets["upper"] and brackets["upper"]["progression_complete"]),
        },
    }


def list_public_tournaments(state: dict) -> list[dict]:
    items = [
        {
            "tournament_id": item.get("id", key),
            "tournament_name": item.get("name") or "Kogane OTP杯",
            "status": item.get("status", "setup"),
            "phase": item.get("phase", "setup"),
            "updated_at": _timestamp(item),
        }
        for key, item in state.get("otp_tournaments", {}).items()
    ]
    return sorted(items, key=lambda item: item.get("updated_at") or "", reverse=True)


def build_application_layout_preview(state: dict) -> dict[str, Any] | None:
    """Build the reserved read-only layout page from live OTP form applications."""
    applications = sorted(
        (
            team for team in state.get("otp_teams", {}).values()
            if (
                isinstance(team, dict)
                and str(team.get("number", "")).isdigit()
                and int(team["number"]) not in {1, 2}
            )
        ),
        key=lambda team: int(team["number"]),
    )
    fallback = load_public_layout_fixture("all-teams-layout-test")
    if not applications:
        return fallback

    tournament_id = APPLICATION_LAYOUT_TOURNAMENT_ID
    teams: dict[str, dict[str, Any]] = {}
    ordered_keys = []
    application_number_by_key = {}
    for application in applications:
        number = int(application["number"])
        application_id = f"OTP-{number:03d}"
        team_key = f"{tournament_id}:{application_id}"
        player_data = application.get("players", {})
        names = [
            application.get("leader_name") or "未入力",
            *((application.get("member_names") or []) + ["未入力"] * 3)[:3],
        ]
        circles = [
            application.get("leader_circle") or None,
            *((application.get("member_circles") or []) + [None] * 3)[:3],
        ]
        members = []
        for index, name in enumerate(names):
            player = player_data.get(str(index), {})
            members.append({
                "role": "リーダー" if index == 0 else f"メンバー{index}",
                "player_name": name,
                "circle": circles[index],
                "weapons": [weapon for weapon in player.get("weapons", []) if weapon],
            })
        teams[team_key] = {
            "application_id": application_id,
            "application_number": number,
            "team_name": str(application.get("team_name") or "").strip() or f"チーム{number}",
            "registration_type": "official",
            "members": members,
            "created_at": application.get("created_at"),
            "updated_at": application.get("updated_at"),
        }
        ordered_keys.append(team_key)
        application_number_by_key[team_key] = number

    grouping_seed = application_layout_seed(
        state, [int(application["number"]) for application in applications]
    )
    blocks = build_seeded_qualifier_blocks(
        ordered_keys, application_number_by_key, grouping_seed
    )
    if blocks is None:
        return fallback

    matches: dict[str, dict[str, Any]] = {}
    match_order = []
    match_number = 1
    for group_index, block in enumerate(blocks, start=1):
        for first_index, first in enumerate(block):
            for second in block[first_index + 1:]:
                match_id = f"Q{match_number:03d}"
                matches[match_id] = {
                    "id": match_id,
                    "phase": "qualifier",
                    "block": group_index,
                    "teams": [first, second],
                    "best_of": 3,
                    "status": "waiting",
                    "wins": {first: 0, second: 0},
                    "battles": [],
                    "reports": {},
                }
                match_order.append(match_id)
                match_number += 1

    upper_sources = [
        {"source_group_index": group_index, "rank": rank}
        for group_index, block in enumerate(blocks, start=1)
        for rank in range(1, min(2, len(block)) + 1)
    ]
    lower_sources = [
        {"source_group_index": group_index, "rank": rank}
        for group_index, block in enumerate(blocks, start=1)
        for rank in range(3, len(block) + 1)
    ]

    brackets = {}
    for league, sources in (("upper", upper_sources), ("lower", lower_sources)):
        if len(sources) < 2:
            continue
        fallback_bracket = (fallback or {}).get(f"{league}_bracket") or {}
        if len(ordered_keys) == 34 and fallback_bracket.get("slot_sources"):
            slot_sources = fallback_bracket["slot_sources"]
            slot_count = len(fallback_bracket.get("initial_slots", []))
        else:
            tokens = [f"{source['source_group_index']}:{source['rank']}" for source in sources]
            source_by_token = dict(zip(tokens, sources))
            token_slots, _ = build_single_elimination_slots(
                tokens, rng=random.Random(f"otp-layout:{league}:{len(ordered_keys)}")
            )
            slot_sources = [source_by_token.get(token) if token else None for token in token_slots]
            slot_count = len(token_slots)
        brackets[league] = {
            "slots": [None] * slot_count,
            "slot_sources": slot_sources,
            "auto_advancers": [],
            "active_team_count": len(sources),
        }

    timestamps = [
        value for application in applications
        for value in (application.get("updated_at"), application.get("created_at"))
        if isinstance(value, (int, float))
    ]
    raw_tournament = {
        "id": tournament_id,
        "name": f"Kogane OTP杯・{len(ordered_keys)}チーム表記テスト",
        "status": "registration",
        "phase": "qualifier",
        "updated_at": max(timestamps, default=0),
        "teams": teams,
        "blocks": blocks,
        "matches": matches,
        "match_order": match_order,
        "block_rankings": {},
        "brackets": brackets,
    }
    preview = build_public_tournament(raw_tournament)
    preview["data_mode"] = "application_layout_preview"
    preview["live_updates"] = True
    return preview


def list_public_application_layout_preview(state: dict) -> list[dict[str, Any]]:
    preview = build_application_layout_preview(state)
    if not preview:
        return []
    return [{
        "tournament_id": preview["tournament_id"],
        "tournament_name": preview["tournament_name"],
        "status": preview["status"],
        "phase": preview["phase"],
        "updated_at": preview.get("updated_at", ""),
        "data_mode": preview.get("data_mode"),
    }]
