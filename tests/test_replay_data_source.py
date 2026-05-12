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


if __name__ == "__main__":
    unittest.main()
