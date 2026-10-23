"""Unit tests for PatchApplier verifying AST validation and original source immutability."""

import hashlib
from pathlib import Path
import pytest
from resq.engine.patch_applier import PatchApplier


class TestPatchApplier:
    """Verifies AST safety checks, diff generation, and source immutability."""

    def test_validate_syntax_valid(self):
        valid_code = "def add(a: int, b: int) -> int:\n    return a + b\n"
        is_valid, error = PatchApplier.validate_syntax(valid_code)
        assert is_valid is True
        assert error is None

    def test_validate_syntax_invalid(self):
        invalid_code = "def add(a, b\n    return a +\n"
        is_valid, error = PatchApplier.validate_syntax(invalid_code)
        assert is_valid is False
        assert error is not None
        assert "SyntaxError" in error

    def test_generate_diff(self):
        original = "def add(a, b):\n    return a - b\n"
        patched = "def add(a, b):\n    return a + b\n"
        diff = PatchApplier.generate_diff(original, patched, filename="math_ops.py")
        assert "--- a/math_ops.py" in diff
        assert "+++ b/math_ops.py" in diff
        assert "-    return a - b" in diff
        assert "+    return a + b" in diff

    def test_original_source_immutability_on_rejection(self, tmp_path):
        """CRITICAL INVARIANT TEST: Ensures candidate patch evaluation never mutates the original source."""
        # 1. Setup original source file on host
        original_code = "def subtract(a: int, b: int) -> int:\n    return a - b\n"
        source_dir = tmp_path / "source_workspace"
        source_dir.mkdir()
        target_file = source_dir / "target.py"
        target_file.write_text(original_code, encoding="utf-8")
        initial_hash = hashlib.sha256(target_file.read_bytes()).hexdigest()

        # 2. Attempt to prepare a workspace with a broken patch
        broken_patch = "def subtract(a: int, b: int) -> int:\n    return a * b\n"
        applier = PatchApplier()
        patch_dir, diff = applier.prepare_patch_workspace(
            source_dir,
            broken_patch,
            target_filename="target.py",
        )

        # 3. Verify patch was written ONLY to the temporary copy
        assert patch_dir != source_dir
        patched_file = patch_dir / "target.py"
        assert patched_file.read_text(encoding="utf-8") == broken_patch

        # 4. Assert original host source was NEVER modified
        current_hash = hashlib.sha256(target_file.read_bytes()).hexdigest()
        assert current_hash == initial_hash, "CRITICAL VIOLATION: Original source file was mutated!"
        assert target_file.read_text(encoding="utf-8") == original_code

    def test_prepare_patch_workspace_rejects_syntax_error(self, tmp_path):
        """Ensures that invalid syntax is rejected before touching the temporary workspace."""
        source_dir = tmp_path / "src_dir"
        source_dir.mkdir()
        (source_dir / "target.py").write_text("x = 1\n", encoding="utf-8")

        applier = PatchApplier()
        with pytest.raises(SyntaxError):
            applier.prepare_patch_workspace(
                source_dir,
                "def broken( :::",
                target_filename="target.py",
            )

    def test_prepare_patch_workspace_rejects_path_traversal(self, tmp_path):
        """Ensures target filenames containing traversal components are rejected before writing."""
        source_dir = tmp_path / "src_dir"
        source_dir.mkdir()
        destination_dir = tmp_path / "dest_dir"
        destination_dir.mkdir()
        applier = PatchApplier()

        with pytest.raises(ValueError, match="SECURITY VIOLATION"):
            applier.prepare_patch_workspace(
                source_dir,
                "x = 1\n",
                target_filename="../escape.py",
                destination_dir=destination_dir,
            )
        # Verify no candidate file was written
        assert list(destination_dir.iterdir()) == []

    def test_prepare_patch_workspace_rejects_windows_backslash_traversal(self, tmp_path):
        """Ensures Windows-style backslash traversal is rejected before writing."""
        source_dir = tmp_path / "src_dir"
        source_dir.mkdir()
        destination_dir = tmp_path / "dest_dir"
        destination_dir.mkdir()
        applier = PatchApplier()

        with pytest.raises(ValueError, match="SECURITY VIOLATION"):
            applier.prepare_patch_workspace(
                source_dir,
                "x = 1\n",
                target_filename="..\\escape.py",
                destination_dir=destination_dir,
            )
        assert list(destination_dir.iterdir()) == []

    def test_prepare_patch_workspace_rejects_windows_drive_path(self, tmp_path):
        """Ensures Windows drive absolute path is rejected before writing."""
        source_dir = tmp_path / "src_dir"
        source_dir.mkdir()
        destination_dir = tmp_path / "dest_dir"
        destination_dir.mkdir()
        applier = PatchApplier()

        with pytest.raises(ValueError, match="SECURITY VIOLATION"):
            applier.prepare_patch_workspace(
                source_dir,
                "x = 1\n",
                target_filename="C:\\escape.py",
                destination_dir=destination_dir,
            )
        assert list(destination_dir.iterdir()) == []

    def test_prepare_patch_workspace_rejects_colon_ads(self, tmp_path):
        """Ensures filenames with colons (NTFS Alternate Data Streams) are rejected before writing."""
        source_dir = tmp_path / "src_dir"
        source_dir.mkdir()
        destination_dir = tmp_path / "dest_dir"
        destination_dir.mkdir()
        applier = PatchApplier()

        with pytest.raises(ValueError, match="SECURITY VIOLATION"):
            applier.prepare_patch_workspace(
                source_dir,
                "x = 1\n",
                target_filename="target.py:stream",
                destination_dir=destination_dir,
            )
        assert list(destination_dir.iterdir()) == []

    def test_prepare_patch_workspace_rejects_absolute_path(self, tmp_path):
        """Ensures absolute target paths are rejected before writing."""
        source_dir = tmp_path / "src_dir"
        source_dir.mkdir()
        destination_dir = tmp_path / "dest_dir"
        destination_dir.mkdir()
        applier = PatchApplier()

        with pytest.raises(ValueError, match="SECURITY VIOLATION"):
            applier.prepare_patch_workspace(
                source_dir,
                "x = 1\n",
                target_filename="/etc/shadow.py",
                destination_dir=destination_dir,
            )
        assert list(destination_dir.iterdir()) == []

    def test_prepare_patch_workspace_rejects_empty_code(self, tmp_path):
        """Ensures empty or whitespace candidate patches are rejected."""
        source_dir = tmp_path / "src_dir"
        source_dir.mkdir()
        applier = PatchApplier()

        with pytest.raises(ValueError, match="cannot be empty"):
            applier.prepare_patch_workspace(
                source_dir,
                "   \n\t",
                target_filename="target.py",
            )
