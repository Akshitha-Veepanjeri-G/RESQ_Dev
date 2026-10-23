"""Safe patch application with AST syntax validation and workspace isolation."""

import ast
import difflib
import tempfile
from pathlib import Path
from typing import Optional


class PatchApplier:
    """Validates candidate patches via AST and applies them to isolated temporary workspaces.

    Guarantees:
    - AST validation runs before any filesystem operations.
    - Patches are applied ONLY to an isolated temporary copy.
    - The original user source code is IMMUTABLE and never modified on disk.
    - Produces a standard unified diff between original and patched code.
    """

    @staticmethod
    def validate_syntax(code: str) -> tuple[bool, Optional[str]]:
        """Parses the code into an AST to verify syntactical correctness.

        Returns:
            (True, None) if syntax is valid.
            (False, error_message) if syntax is invalid.
        """
        try:
            ast.parse(code)
            return True, None
        except SyntaxError as exc:
            return False, f"SyntaxError at line {exc.lineno}: {exc.msg}"
        except Exception as exc:
            return False, f"Parse error: {exc}"

    @staticmethod
    def generate_diff(original_code: str, patched_code: str, filename: str = "target.py") -> str:
        """Generates a standard unified diff between original and patched code."""
        orig_lines = original_code.splitlines(keepends=True)
        patch_lines = patched_code.splitlines(keepends=True)
        diff_lines = difflib.unified_diff(
            orig_lines,
            patch_lines,
            fromfile=f"a/{filename}",
            tofile=f"b/{filename}",
        )
        return "".join(diff_lines)

    def prepare_patch_workspace(
        self,
        workspace_source_dir: Path,
        patch_code: str,
        target_filename: str = "target.py",
        destination_dir: Optional[Path] = None,
    ) -> tuple[Path, str]:
        """Copies workspace files to a temporary directory and safely replaces target_filename with patch_code.

        Args:
            workspace_source_dir: Directory containing original unpatched files.
            patch_code: The candidate patch code.
            target_filename: The specific file to be replaced with the patch.
            destination_dir: Optional destination directory; if None, creates a new temp dir.

        Returns:
            tuple of (patch_workspace_path, unified_diff)

        Raises:
            SyntaxError: If patch_code fails AST syntax validation.
        """
        # Gate 0: Validate target_filename against path traversal, Alternate Data Streams, and directory climbing
        if not target_filename or not target_filename.strip():
            raise ValueError("SECURITY VIOLATION: Target filename cannot be empty or whitespace only.")

        target_path_obj = Path(target_filename)
        if (
            target_path_obj.is_absolute()
            or ".." in target_path_obj.parts
            or target_path_obj.name != target_filename
            or "/" in target_filename
            or "\\" in target_filename
            or ":" in target_filename
        ):
            raise ValueError(
                f"SECURITY VIOLATION: Invalid target filename '{target_filename}'. "
                "Target filename must be a single relative module name with no path separators, colons, or traversal components."
            )

        # Gate 1: Non-empty patch validation
        if not patch_code or not patch_code.strip():
            raise ValueError("Candidate patch code cannot be empty or whitespace only.")

        # Gate 2: Static AST validation
        is_valid, error_msg = self.validate_syntax(patch_code)
        if not is_valid:
            raise SyntaxError(error_msg or "Invalid Python syntax in candidate patch")

        # Create isolated temporary destination
        if destination_dir is None:
            temp_dir = Path(tempfile.mkdtemp(prefix="resq_patch_"))
        else:
            temp_dir = destination_dir
            temp_dir.mkdir(parents=True, exist_ok=True)

        temp_dir_resolved = temp_dir.resolve()
        dest_target_file = (temp_dir / target_filename).resolve()
        if not dest_target_file.is_relative_to(temp_dir_resolved):
            raise ValueError(
                f"SECURITY VIOLATION: Target path '{dest_target_file}' escapes temporary workspace '{temp_dir_resolved}'."
            )

        original_code = ""

        # Copy all files from source workspace to patch workspace
        for item in workspace_source_dir.glob("*"):
            if item.is_file():
                dest_file = temp_dir / item.name
                if item.name == target_filename:
                    original_code = item.read_text(encoding="utf-8")
                    dest_file.write_text(patch_code, encoding="utf-8")
                else:
                    dest_file.write_text(item.read_text(encoding="utf-8"), encoding="utf-8")

        # If target file wasn't present in source dir, write it directly
        if not (temp_dir / target_filename).exists():
            (temp_dir / target_filename).write_text(patch_code, encoding="utf-8")

        diff = self.generate_diff(original_code, patch_code, filename=target_filename)
        return temp_dir, diff
