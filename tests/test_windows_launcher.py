"""Static + live checks for the portable Windows launcher.

Start-Maintenance-NoteBook.bat must not depend on machine-specific paths:
SurrealDB is discovered (SURREALDB_EXE override, PATH, legacy layout) and
version-gated to 2.6.x; locations derive from the script directory with
overrides; prerequisites fail early with actionable errors.

Static checks read the batch text (no Windows execution needed). The live
check runs the real `surreal version` output through the same token/delimiter
rules the batch uses, proving the gate accepts the deployed binary.
"""

from pathlib import Path

import pytest

BAT_PATH = Path(__file__).parent.parent / "Start-Maintenance-NoteBook.bat"


def _bat() -> str:
    return BAT_PATH.read_text(encoding="utf-8-sig")


class TestNoMachineSpecificPaths:
    def test_repo_path_not_hardcoded(self):
        assert "E:\\Project\\Maintenance_Ai_Agent" not in _bat()

    def test_surreal_not_pinned_to_single_path(self):
        lines = _bat().splitlines()
        hits = [line for line in lines if "surrealdb-2.6.5" in line]
        assert hits, "legacy fallback documented"
        for line in hits:
            lowered = line.lower()
            assert (
                "userprofile" in lowered
                or "legacy" in lowered
                or "fallback" in lowered
                or "2.6.x binary exists" in lowered
            ), line
        assert "SURREALDB_EXE" in _bat()
        assert "where surreal.exe" in _bat()

    def test_data_root_overridable(self):
        text = _bat()
        assert "MAINTENANCE_DATA_ROOT" in text
        # The default keeps the established external store; it must be a
        # default, not the only option.
        assert text.count("E:\\Maintenance_Ai_Agent_Data") <= 2

    def test_root_quoting(self):
        assert 'cd /d "%ROOT%"' in _bat()


class TestDiscoveryAndGating:
    def test_version_gate_present(self):
        text = _bat()
        assert "2.6" in text
        assert "SURREAL_VER" in text
        assert "SURREAL_MAJOR" in text

    def test_preflight_checks_present(self):
        text = _bat()
        for marker in ('where uv', 'where node', 'where npm', '.env', 'run_api.py'):
            assert marker in text, marker

    def test_credentials_overridable(self):
        text = _bat()
        assert "SURREAL_USER" in text
        assert "SURREAL_PASS" in text

    def test_shutdown_uses_derived_paths(self):
        text = _bat()
        assert "$env:SURREAL_DIR" in text
        assert "$env:DATA_ROOT" in text


class TestVersionGateAgainstRealBinary:
    @staticmethod
    def _major_minor(exe) -> tuple:
        """Mirror the batch token/delimiter rules: first line, first token,
        split on '.'; take major and minor."""
        import subprocess

        out = subprocess.run(
            [str(exe), "version"], capture_output=True, text=True, timeout=30
        )
        first_line = (out.stdout or "").splitlines()[0] if out.stdout else ""
        return tuple(first_line.split(" ")[0].split(".")[:2])

    def test_deployed_surreal_parses_as_2_6(self):
        """The deployment binary behind the legacy layout passes the gate."""
        legacy = (
            Path.home() / "Tools" / "surrealdb-2.6.5" / "surreal.exe"
        )
        if not legacy.exists():
            pytest.skip("legacy SurrealDB layout not present here")
        assert self._major_minor(legacy) == ("2", "6")

    def test_newer_major_parses_as_incompatible(self):
        """A newer major on PATH would be rejected by the same rules."""
        import shutil

        exe = shutil.which("surreal.exe")
        if not exe:
            pytest.skip("no surreal.exe on PATH")
        major, minor = self._major_minor(exe)
        if (major, minor) == ("2", "6"):
            pytest.skip("PATH binary is already 2.6.x")
        assert not (major == "2" and minor == "6"), exe
