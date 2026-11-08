import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime" / "lib"))
from volume_scan import scan_volume


class VolumeScanTest(unittest.TestCase):
    def test_thresholds_protection_and_project_pruning(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = ("setup.msi", "other.exe", "photo.raw", "small.zip",
                     "team/.git/config", "team/archive.zip", "docs/archive.zip", "private/archive.zip",
                     ".hidden/archive.zip")
            for rel in files:
                p = root / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(b"x" * (7 if rel == "small.zip" else 20))
            cfg = {"protect": [str(root / "private")]}
            with patch("volume_scan.load_rules", return_value={}):
                result = scan_volume(root, cfg, package_min=8, other_min=16)
            rows = {Path(it["path"]).relative_to(root).as_posix(): it["tier"] for it in result["items"]}
            self.assertEqual(rows, {"setup.msi": "optional", "other.exe": "keep",
                                    "photo.raw": "keep", "docs/archive.zip": "optional"})
            self.assertFalse(result["partial"])

    def test_time_and_result_caps_are_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "a.zip").write_bytes(b"x" * 10)
            (root / "b.zip").write_bytes(b"x" * 20)
            with patch("volume_scan.load_rules", return_value={}):
                timed = scan_volume(root, {}, seconds=0, package_min=1)
                limited = scan_volume(root, {}, limit=1, package_min=1)
            self.assertTrue(timed["partial"])
            self.assertTrue(limited["truncated"])
            self.assertEqual(Path(limited["items"][0]["path"]).name, "b.zip")


if __name__ == "__main__":
    unittest.main()
