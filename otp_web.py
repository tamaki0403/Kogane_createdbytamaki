"""Read-only OTP tournament projection shared by the Bot API and local preview.

This module does not advance a tournament.  It only translates the persisted
Bot state into public display data and intentionally omits Discord IDs,
operator IDs, channel IDs, and pending report contents.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import random


PUBLIC_RULES = [
    "全試合ガチエリアです。",
    "通常の対戦はBO3、決勝はBO5です。",
    "使用ブキは2026 Sizzle Seasonの個人使用率TOP3です。",
    "開始前または開始後15秒以内の回線落ちは、同じステージ・ブキ・ギアで再試合します。",
    "15秒を超えた回線落ちは原則続行です。",
    "判断に迷う場合はDiscordで運営に相談してください。",
]


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


def _section_counts(group_count: int) -> list[int]:
    """Presentation-only A-D distribution; 10 groups becomes 3/2/3/2."""
    base, extra = divmod(group_count, 4)
    counts = [base] * 4
    for index in (0, 2, 1, 3)[:extra]:
        counts[index] += 1
    return counts


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
    counts = _section_counts(len(raw_groups))
    placement_by_team: dict[str, str] = {}
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
            "registration_type": "test" if team.get("solo_test") or not any(member.get("discord_id") for member in team.get("members", [])) else "official",
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
        bracket_matches = [match for match in matches if match.get("phase") == bracket_name]
        brackets[bracket_name] = {
            "league": bracket_name,
            "active_team_count": bracket.get("active_team_count", sum(bool(slot) for slot in slots)),
            "initial_slots": slots,
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
