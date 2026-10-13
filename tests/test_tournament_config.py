import json
import tempfile
import unittest
from pathlib import Path

from tournament_config import (
    SUPPORTED_FORMAT,
    get_main_tournament_config,
    get_operator_panel_configs,
    load_tournament_configs,
)


class TournamentConfigTests(unittest.TestCase):
    def test_repository_has_main_and_rehearsal_panels(self):
        config = get_main_tournament_config()
        self.assertEqual(config["id"], "otp-20261024")
        self.assertEqual(config["format"], SUPPORTED_FORMAT)
        self.assertEqual(config["public_alias"], "all-teams-layout-test")
        self.assertEqual(config["qualifier"]["section_labels"], ["A", "B", "C", "D"])
        panel_ids = {item["id"] for item in get_operator_panel_configs()}
        self.assertEqual(
            panel_ids,
            {"otp-20261024", "otp-rehearsal-20261014"},
        )
        rehearsal = next(
            item for item in get_operator_panel_configs()
            if item["id"] == "otp-rehearsal-20261014"
        )
        self.assertEqual(rehearsal["participant_source"], "isolated_manual_registration")
        self.assertEqual(rehearsal["min_team_members"], 1)
        self.assertEqual(rehearsal["max_team_members"], 4)
        self.assertEqual(rehearsal["discord"]["admin_channel_id"], "1559647960772644934")
        self.assertEqual(
            set(rehearsal["discord"]["match_categories"]["qualifier"]),
            {"A", "B", "C", "D"},
        )
        self.assertNotEqual(
            rehearsal["discord"]["admin_channel_id"],
            config["discord"]["admin_channel_id"],
        )

    def test_loader_supports_multiple_isolated_operator_panels(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index in (1, 2):
                (root / f"event-{index}.json").write_text(
                    json.dumps({
                        "id": f"event-{index}",
                        "format": SUPPORTED_FORMAT,
                        "active_operator_panel": True,
                        "qualifier": {
                            "group_sizes": [3, 4],
                            "section_labels": ["A", "B", "C", "D"],
                            "upper_places": [1, 2],
                        },
                        "bracket": {"type": "single_elimination"},
                    }),
                    encoding="utf-8",
                )
            configs = load_tournament_configs(root)
            self.assertEqual(len(get_operator_panel_configs(configs)), 2)


if __name__ == "__main__":
    unittest.main()
