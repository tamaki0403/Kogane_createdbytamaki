import random
import unittest

from otp_web import (
    build_public_tournament,
    build_single_elimination_slots,
    list_public_layout_fixtures,
    list_public_tournaments,
    load_public_layout_fixture,
    rank_qualifier_group,
)


def tournament_fixture(group_count=10):
    tournament = {
        "id": "demo-local",
        "name": "Kogane OTP杯 ローカル確認",
        "status": "running",
        "phase": "bracket",
        "started_at": 1_800_000_000,
        "teams": {},
        "blocks": [],
        "matches": {},
        "match_order": [],
        "block_rankings": {},
        "brackets": {},
    }
    match_no = 1
    for group_index in range(1, group_count + 1):
        keys = []
        for local_index in range(4):
            number = (group_index - 1) * 4 + local_index + 1
            key = f"demo-local:OTP-{number:03d}"
            keys.append(key)
            tournament["teams"][key] = {
                "key": key,
                "application_id": f"OTP-{number:03d}",
                "application_number": number,
                "team_name": f"チーム {number}",
                "status": "approved",
                "solo_test": number == 1,
                "members": [{
                    "role": "リーダー",
                    "player_name": f"選手 {number}",
                    "circle": "Kogane",
                    "discord_id": "" if number == 1 else str(100000000000000000 + number),
                    "weapons": ["スプラシューター"],
                }],
            }
        tournament["blocks"].append(keys)
        tournament["block_rankings"][str(group_index)] = keys
        for a_index in range(4):
            for b_index in range(a_index + 1, 4):
                a, b = keys[a_index], keys[b_index]
                match_id = f"Q{match_no:03d}"
                tournament["matches"][match_id] = {
                    "id": match_id,
                    "phase": "qualifier",
                    "block": group_index,
                    "teams": [a, b],
                    "best_of": 3,
                    "status": "done",
                    "wins": {a: 2, b: 0},
                    "winner": a,
                    "battles": [{"battle": 1, "stage": "ユノハナ大渓谷", "winner": a, "operator_id": "secret"}],
                    "reports": {a: {"reporter_id": "secret"}},
                }
                tournament["match_order"].append(match_id)
                match_no += 1
    upper = [group[0] for group in tournament["blocks"]] + [group[1] for group in tournament["blocks"]]
    lower = [group[2] for group in tournament["blocks"]] + [group[3] for group in tournament["blocks"]]
    for league, entrants in (("upper", upper), ("lower", lower)):
        size = 1
        while size < len(entrants):
            size *= 2
        slots = [None] * size
        if len(entrants) == 20:
            for index, entrant in enumerate(entrants[:12]):
                slots[index * 2] = entrant
            slots[24:32] = entrants[12:20]
        else:
            slots[:len(entrants)] = entrants
        tournament["brackets"][league] = {
            "slots": slots,
            "auto_advancers": [team for index, team in enumerate(slots) if team and not slots[index ^ 1]],
            "active_team_count": len(entrants),
        }
        pairs = [slots[index:index + 2] for index in range(24, 32, 2)] if len(entrants) == 20 else [entrants[:2]]
        for match_index, first in enumerate(pairs, start=1):
            match_id = f"{league[0].upper()}{match_index:03d}"
            tournament["matches"][match_id] = {
                "id": match_id,
                "phase": league,
                "round": 1,
                "teams": first,
                "best_of": 3,
                "status": "active",
                "wins": {first[0]: 1, first[1]: 0},
                "reports": {first[0]: {"winner": first[0], "reporter_id": "secret"}},
                "battles": [],
            }
    return tournament


class OtpWebProjectionTests(unittest.TestCase):
    def test_sanitized_34_team_layout_fixture(self):
        fixture = load_public_layout_fixture("all-teams-layout-test")
        self.assertIsNotNone(fixture)
        self.assertEqual(fixture["team_count"], 34)
        self.assertEqual(fixture["group_count"], 9)
        self.assertEqual(fixture["upper_bracket"]["active_team_count"], 18)
        self.assertEqual(fixture["lower_bracket"]["active_team_count"], 16)
        self.assertEqual(fixture["data_mode"], "layout_test")
        text = repr(fixture)
        for private_key in ("discord_id", "reporter_id", "operator_id", "channel_id", "corrected_xp"):
            self.assertNotIn(private_key, text)
        self.assertTrue(any(item["tournament_id"] == "all-teams-layout-test" for item in list_public_layout_fixtures()))

    def test_40_teams_are_split_3_2_3_2_and_positions_are_numeric(self):
        result = build_public_tournament(tournament_fixture())
        self.assertEqual([len(block["groups"]) for block in result["qualifier_blocks"]], [3, 2, 3, 2])
        first = result["qualifier_blocks"][0]["groups"][0]
        self.assertEqual([team["position"] for team in first["teams"]], ["A1", "A2", "A3", "A4"])

    def test_group_headings_adapt_to_six_qualifier_groups(self):
        result = build_public_tournament(tournament_fixture(6))
        self.assertEqual([len(block["groups"]) for block in result["qualifier_blocks"]], [2, 1, 2, 1])
        self.assertEqual(result["team_count"], 24)

    def test_planned_bracket_sources_use_display_ranges(self):
        fixture = tournament_fixture(1)
        fixture["brackets"]["upper"]["slots"] = [None, None]
        fixture["brackets"]["upper"]["slot_sources"] = [
            {"source_group_index": 1, "rank": 1},
            {"source_group_index": 1, "rank": 2},
        ]
        result = build_public_tournament(fixture)
        self.assertEqual(
            [source["label"] for source in result["upper_bracket"]["slot_sources"]],
            ["A1〜A4・1位", "A1〜A4・2位"],
        )

    def test_pending_report_is_not_exposed_as_a_confirmed_score(self):
        result = build_public_tournament(tournament_fixture())
        match = next(match for match in result["matches"] if match["match_id"] == "U001")
        self.assertEqual(match["report_state"], "one_sided")
        self.assertIsNone(match["score"])
        self.assertEqual(match["confirmed_battle_score"], [1, 0])
        self.assertIsNone(match["winner_team_id"])

    def test_public_data_omits_discord_and_operator_ids(self):
        text = repr(build_public_tournament(tournament_fixture()))
        self.assertNotIn("discord_id", text)
        self.assertNotIn("reporter_id", text)
        self.assertNotIn("operator_id", text)
        self.assertEqual(build_public_tournament(tournament_fixture())["teams"]["demo-local:OTP-001"]["registration_type"], "test")

    def test_leagues_remain_separate(self):
        result = build_public_tournament(tournament_fixture())
        self.assertEqual(result["upper_bracket"]["league"], "upper")
        self.assertEqual(result["lower_bracket"]["league"], "lower")
        self.assertNotEqual(result["upper_bracket"]["initial_slots"], result["lower_bracket"]["initial_slots"])
        self.assertEqual(len(result["upper_bracket"]["matches"]), 4)
        self.assertEqual(len(result["upper_bracket"]["auto_advancers"]), 12)

    def test_shared_ranking_uses_confirmed_matches_only(self):
        fixture = tournament_fixture(1)
        first_match = fixture["matches"]["Q001"]
        first_match["status"] = "active"
        first_match["wins"] = {first_match["teams"][0]: 1, first_match["teams"][1]: 0}
        ranked = rank_qualifier_group(fixture, 1)
        self.assertEqual(set(ranked), set(fixture["blocks"][0]))

    def test_20_team_bracket_has_four_matches_and_twelve_single_team_pairs(self):
        slots, byes = build_single_elimination_slots([f"team-{index}" for index in range(20)], random.Random(7))
        pairs = [slots[index:index + 2] for index in range(0, len(slots), 2)]
        self.assertEqual(sum(bool(a) and bool(b) for a, b in pairs), 4)
        self.assertEqual(sum(bool(a) ^ bool(b) for a, b in pairs), 12)
        self.assertEqual(len(byes), 12)
        self.assertFalse(any(not a and not b for a, b in pairs))
        self.assertEqual([index for index, (a, b) in enumerate(pairs) if a and b], [1, 5, 9, 13])

    def test_two_team_bracket_is_one_real_pair(self):
        slots, byes = build_single_elimination_slots(["a", "b"], random.Random(1))
        self.assertEqual(set(slots), {"a", "b"})
        self.assertEqual(byes, set())

    def test_tournament_list_is_newest_first(self):
        older = tournament_fixture(1)
        newer = tournament_fixture(1)
        older["id"], older["updated_at"] = "older", 2_000_000_000
        newer["id"], newer["updated_at"] = "newer", 2_100_000_000
        items = list_public_tournaments({"otp_tournaments": {"older": older, "newer": newer}})
        self.assertEqual([item["tournament_id"] for item in items], ["newer", "older"])


if __name__ == "__main__":
    unittest.main()
