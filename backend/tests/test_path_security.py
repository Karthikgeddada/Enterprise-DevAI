import os
import tempfile
import pytest
from security.path_validator import (
    resolve_safe_path, validate_file_path, PathValidationError,
    is_safe_filename, safe_extract_zip, safe_create_project_zip,
)


class TestPathValidation:

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = os.path.join(self.tmpdir, "project")
        os.makedirs(self.project_root, exist_ok=True)

    def test_resolve_safe_path_valid(self):
        result = resolve_safe_path(self.project_root, "src/main.py")
        assert result.startswith(self.project_root)
        assert result.endswith("src/main.py")

    def test_resolve_safe_path_traversal(self):
        with pytest.raises(PathValidationError, match="escapes project root"):
            resolve_safe_path(self.project_root, "../../../etc/passwd")

    def test_resolve_safe_path_absolute(self):
        with pytest.raises(PathValidationError, match="Absolute paths"):
            resolve_safe_path(self.project_root, "/etc/passwd")

    def test_resolve_safe_path_empty(self):
        with pytest.raises(PathValidationError, match="Path is empty"):
            resolve_safe_path(self.project_root, "")

    def test_validate_file_path_blocked_extension(self):
        with pytest.raises(PathValidationError, match="not allowed"):
            validate_file_path(self.project_root, "malware.exe")

    def test_validate_file_path_valid(self):
        result = validate_file_path(self.project_root, "src/app.py")
        assert result.endswith("src/app.py")

    def test_is_safe_filename_valid(self):
        assert is_safe_filename("hello.py")
        assert is_safe_filename("test.py")

    def test_is_safe_filename_traversal(self):
        assert not is_safe_filename("..")
        assert not is_safe_filename(".")

    def test_is_safe_filename_with_slash(self):
        assert not is_safe_filename("dir/file.py")

    def test_is_safe_filename_blocked(self):
        assert not is_safe_filename("script.sh")
        assert not is_safe_filename("binary.exe")

    def test_nested_traversal(self):
        with pytest.raises(PathValidationError):
            resolve_safe_path(self.project_root, "sub/../../outside.txt")

    def test_windows_style_traversal(self):
        with pytest.raises(PathValidationError):
            resolve_safe_path(self.project_root, "..\\..\\windows\\system32")