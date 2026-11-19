import pytest
import tempfile
import os
import zipfile
import io
from security.path_validator import safe_extract_zip, safe_create_project_zip, PathValidationError


class TestArchiveExtraction:

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = os.path.join(self.tmpdir, "project")
        os.makedirs(self.project_root, exist_ok=True)

    def test_extract_valid_zip(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as zf:
            zf.writestr('main.py', 'print("hello")')
            zf.writestr('utils/helper.py', 'def help(): pass')
            zf.writestr('README.md', '# Test')
        buf.seek(0)

        extracted = safe_extract_zip(buf.getvalue(), self.project_root)
        assert 'main.py' in extracted
        assert 'utils/helper.py' in extracted
        assert 'README.md' in extracted

        # Verify files exist
        assert os.path.exists(os.path.join(self.project_root, 'main.py'))
        assert os.path.exists(os.path.join(self.project_root, 'utils/helper.py'))

    def test_extract_zip_with_traversal(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as zf:
            zf.writestr('../../outside.txt', 'malicious')
        buf.seek(0)

        with pytest.raises(PathValidationError, match="Unsafe path"):
            safe_extract_zip(buf.getvalue(), self.project_root)

    def test_extract_zip_skips_pycache(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as zf:
            zf.writestr('main.py', 'print(1)')
            zf.writestr('__pycache__/main.pyc', 'binary')
        buf.seek(0)

        extracted = safe_extract_zip(buf.getvalue(), self.project_root)
        assert 'main.py' in extracted
        assert '__pycache__/main.pyc' not in extracted

    def test_extract_zip_skips_blocked_extensions(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as zf:
            zf.writestr('script.py', 'print(1)')
            zf.writestr('malware.exe', 'binary')
        buf.seek(0)

        extracted = safe_extract_zip(buf.getvalue(), self.project_root)
        assert 'script.py' in extracted
        assert 'malware.exe' not in extracted

    def test_create_and_extract_zip(self):
        # Create files
        os.makedirs(os.path.join(self.project_root, 'src'), exist_ok=True)
        with open(os.path.join(self.project_root, 'main.py'), 'w') as f:
            f.write('print("hello")')
        with open(os.path.join(self.project_root, 'src/util.py'), 'w') as f:
            f.write('def util(): pass')

        # Create zip
        zip_path = os.path.join(self.tmpdir, 'test.zip')
        safe_create_project_zip(self.project_root, zip_path)
        assert os.path.exists(zip_path)

        # Extract to new location
        new_root = os.path.join(self.tmpdir, 'new_project')
        os.makedirs(new_root, exist_ok=True)
        with open(zip_path, 'rb') as f:
            extracted = safe_extract_zip(f.read(), new_root)

        assert 'main.py' in extracted
        assert 'src/util.py' in extracted
        assert os.path.exists(os.path.join(new_root, 'main.py'))
        assert os.path.exists(os.path.join(new_root, 'src/util.py'))

    def test_extract_oversized_zip(self):
        from security.path_validator import MAX_ARCHIVE_SIZE
        # Create a zip larger than MAX_ARCHIVE_SIZE is impractical in tests,
        # so we test the size check directly
        large_data = b'x' * (MAX_ARCHIVE_SIZE + 1)
        with pytest.raises(PathValidationError, match="maximum size"):
            safe_extract_zip(large_data, self.project_root)