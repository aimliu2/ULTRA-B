import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ultrab.replayer import data_source


class ReplayDataRootResolutionTests(unittest.TestCase):
    def test_missing_configured_root_falls_back_to_ln_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fallback = tmp_path / "ln-data"
            fallback.mkdir()
            config_path = tmp_path / "src" / "ultrab" / "replayer" / "config.yaml"
            missing_root = tmp_path / "missing"

            with patch.object(data_source, "DEFAULT_DATA_ROOT", fallback):
                self.assertEqual(
                    data_source._resolve_data_root(missing_root, config_path),
                    fallback.resolve(),
                )

    def test_relative_root_can_resolve_from_project_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            project_root = tmp_path / "project"
            relative_root = project_root / "ln-data"
            relative_root.mkdir(parents=True)
            config_path = project_root / "src" / "ultrab" / "replayer" / "config.yaml"

            with patch.object(data_source, "PROJECT_ROOT", project_root):
                self.assertEqual(
                    data_source._resolve_data_root("ln-data", config_path),
                    relative_root.resolve(),
                )


class ReplayStartTimeResolutionTests(unittest.TestCase):
    def test_latest_window_start_time_resolves_to_session_default(self):
        self.assertIsNone(data_source.effective_start_time(None, "latest_window"))
        self.assertIsNone(data_source.effective_start_time("", "latest_window"))

    def test_request_start_time_overrides_configured_start_time(self):
        self.assertEqual(
            data_source.effective_start_time("2024-05-14T00:00:00Z", "latest_window"),
            "2024-05-14T00:00:00Z",
        )

    def test_configured_iso_start_time_is_used_when_request_is_missing(self):
        self.assertEqual(
            data_source.effective_start_time(None, "2024-05-14T00:00:00Z"),
            "2024-05-14T00:00:00Z",
        )

    def test_resolve_start_timestamp_uses_latest_window_default(self):
        config = data_source.replay_data_config(Path("src/ultrab/replayer/config.yaml"))
        full = data_source.load_full_ohlc(config)
        default_index = max(0, len(full) - config.window_bars)

        self.assertEqual(
            data_source.resolve_start_timestamp(full, None, default_index),
            full.index[default_index].isoformat(),
        )

    def test_resolve_start_timestamp_uses_explicit_start_time(self):
        config = data_source.replay_data_config(Path("src/ultrab/replayer/config.yaml"))
        full = data_source.load_full_ohlc(config)

        self.assertEqual(
            data_source.resolve_start_timestamp(full, "2024-05-14T00:00:00Z", 0),
            "2024-05-14T00:00:00+00:00",
        )


if __name__ == "__main__":
    unittest.main()
