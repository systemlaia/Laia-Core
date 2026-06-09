import os
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent


class IngestScanCliTests(unittest.TestCase):
    def run_laia(self, *args):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_scanimage = tmp_path / "scanimage"
            fake_scanimage.write_text(
                textwrap.dedent(
                    """\
                    #!/usr/bin/env sh
                    if [ "$1" = "-L" ]; then
                      echo "device \\`canon_dr:libusb:001:002' is a CANON DR-3010C scanner"
                      exit 0
                    fi
                    if [ "$1" = "--help" ]; then
                      echo "--source ADF Front|ADF Back|ADF Duplex"
                      echo "--mode Lineart|Halftone|Gray|Color"
                      echo "--resolution"
                      exit 0
                    fi
                    echo "unexpected scanimage call: $@" >&2
                    exit 2
                    """
                ),
                encoding="utf-8",
            )
            fake_scanimage.chmod(fake_scanimage.stat().st_mode | stat.S_IXUSR)

            env = os.environ.copy()
            env["PATH"] = f"{tmp_path}{os.pathsep}{env.get('PATH', '')}"
            result = subprocess.run(
                [str(ROOT / "bin" / "laia"), *args],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            return result

    def test_ingest_scan_test_is_registered(self):
        result = self.run_laia("ingest", "scan", "--test")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("LAIA Scan Test", result.stdout)
        self.assertIn("CANON DR-3010C", result.stdout)

    def test_ingest_scan_list_options_is_registered(self):
        result = self.run_laia("ingest", "scan", "--list-options")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--source", result.stdout)
        self.assertIn("ADF Duplex", result.stdout)

    def test_ingest_scan_dry_run_is_registered(self):
        result = self.run_laia(
            "ingest",
            "scan",
            "--profile",
            "document",
            "--project",
            "Inbox",
            "--dry-run",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("LAIA Scan Dry Run", result.stdout)
        self.assertIn("--source ADF Duplex", result.stdout)
        self.assertIn("--mode Gray", result.stdout)
        self.assertIn("--swdespeck=2", result.stdout)
        self.assertNotIn("--swdespeck=yes", result.stdout)

    def test_ingest_scan_rejects_boolean_swdespeck(self):
        bad_profile = ROOT / "core" / "ingest" / "profiles" / "bad-swdespeck.yaml"
        bad_profile.write_text(
            textwrap.dedent(
                """\
                id: bad-swdespeck
                label: Bad Despeckle
                source: ADF Duplex
                mode: Gray
                dpi: 300
                format: tiff
                ocr: false
                swdespeck: yes
                """
            ),
            encoding="utf-8",
        )
        try:
            result = self.run_laia(
                "ingest",
                "scan",
                "--profile",
                "bad-swdespeck",
                "--project",
                "Inbox",
                "--dry-run",
            )
        finally:
            bad_profile.unlink(missing_ok=True)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Invalid profile value for swdespeck", result.stderr)


if __name__ == "__main__":
    unittest.main()
