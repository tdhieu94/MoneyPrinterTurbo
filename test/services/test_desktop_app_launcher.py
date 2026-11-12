import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent.parent
LAUNCHER = ROOT_DIR / "scripts" / "desktop_app.ps1"
SHORTCUT_SCRIPT = ROOT_DIR / "scripts" / "create_desktop_shortcut.ps1"
INSTALLER = ROOT_DIR / "install_desktop_app.bat"
ICON = ROOT_DIR / "resource" / "desktop_app.ico"


class TestDesktopAppLauncher(unittest.TestCase):
    def test_scripts_are_ascii_for_windows_powershell(self):
        # Windows PowerShell 5.1 and cmd read BOM-less files in the ANSI code
        # page, so a non-ASCII character would corrupt the script there.
        for path in (LAUNCHER, SHORTCUT_SCRIPT, INSTALLER):
            with self.subTest(path=path.name):
                path.read_bytes().decode("ascii")

    def test_installer_runs_the_shortcut_script(self):
        text = INSTALLER.read_text(encoding="ascii")
        self.assertIn("sync --frozen", text)
        self.assertIn(r"scripts\create_desktop_shortcut.ps1", text)

    def test_shortcut_points_at_the_launcher_and_icon(self):
        text = SHORTCUT_SCRIPT.read_text(encoding="ascii")
        self.assertIn("desktop_app.ps1", text)
        self.assertIn(r"resource\desktop_app.ico", text)
        self.assertTrue(ICON.is_file())

    def test_launcher_runs_headless_and_stops_the_server_tree(self):
        text = LAUNCHER.read_text(encoding="ascii")
        self.assertIn("--server.headless=true", text)
        self.assertIn("--app=$url", text)
        self.assertIn('"/T"', text)


if __name__ == "__main__":
    unittest.main()
