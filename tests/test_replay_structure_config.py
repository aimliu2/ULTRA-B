import unittest

from ultrab.replayer.replay_session import _structure_dual_display


class ReplayStructureConfigTests(unittest.TestCase):
    def test_dual_display_accepts_explicit_targets(self):
        self.assertEqual(_structure_dual_display({"dual_display": "higher"}), "higher")
        self.assertEqual(_structure_dual_display({"dual_display": "lower"}), "lower")
        self.assertEqual(_structure_dual_display({"dual_display": "both"}), "both")
        self.assertEqual(_structure_dual_display({"dual_display": "projected"}), "projected")
        self.assertEqual(_structure_dual_display({"dual_display": "dual"}), "dual")

    def test_dual_display_normalizes_case_and_spacing(self):
        self.assertEqual(_structure_dual_display({"dual_display": " Both "}), "both")

    def test_dual_display_defaults_to_higher(self):
        self.assertEqual(_structure_dual_display({}), "higher")
        self.assertEqual(_structure_dual_display({"dual_display": "unknown"}), "higher")

    def test_dual_display_preserves_legacy_ltf_enabled(self):
        self.assertEqual(_structure_dual_display({"ltf_enabled": True}), "both")
        self.assertEqual(_structure_dual_display({"ltf_enabled": False}), "higher")


if __name__ == "__main__":
    unittest.main()
