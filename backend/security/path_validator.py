import os
import zipfile
import io
from typing import List

# Maximum individual file size: 10 MB
MAX_FILE_SIZE = 10 * 1024 * 1024
# Maximum total archive size: 50 MB
MAX_ARCHIVE_SIZE = 50 * 1024 * 1024
# Maximum number of files in an archive
MAX_ARCHIVE_ENTRIES = 5000

# File extensions that are always rejected
BLOCKED_EXTENSIONS = {
    '.exe', '.dll', '.so', '.dylib', '.bin', '.sh', '.bat', '.cmd',
    '.ps1', '.vbs', '.app', '.deb', '.rpm', '.msi', '.dmg', '.iso',
}


class PathValidationError(Exception):
    "Raised when a path fails validation checks."
    pass


def resolve_safe_path(project_root: str, relative_path: str) -> str:
    """
    Resolve a relative path within a project root, ensuring it stays contained.
    Returns the canonical absolute path.
    Raises PathValidationError if the path escapes the project root.
    """
    if not relative_path:
        raise PathValidationError("Path is empty")

    root = os.path.realpath(project_root)

    if os.path.isabs(relative_path):
        raise PathValidationError(f"Absolute paths are not allowed: {relative_path}")

    # Reject paths with backslash traversal (Windows-style)
    if '..\\' in relative_path or relative_path.startswith('..\\'):
        raise PathValidationError(f"Path escapes project root: {relative_path}")

    full_path = os.path.realpath(os.path.join(root, relative_path))

    if not full_path.startswith(root + os.sep) and full_path != root:
        raise PathValidationError(f"Path escapes project root: {relative_path}")

    return full_path


def validate_file_path(project_root: str, relative_path: str) -> str:
    """Validate a file path for safety and return the canonical absolute path."""
    full_path = resolve_safe_path(project_root, relative_path)
    _, ext = os.path.splitext(relative_path.lower())
    if ext in BLOCKED_EXTENSIONS:
        raise PathValidationError(f"File type not allowed: {ext}")
    return full_path


def validate_file_size(file_path: str, max_size: int = MAX_FILE_SIZE) -> None:
    """Validate that a file does not exceed the maximum size."""
    if not os.path.exists(file_path):
        return
    size = os.path.getsize(file_path)
    if size > max_size:
        raise PathValidationError(f"File exceeds maximum size of {max_size} bytes")


def safe_extract_zip(zip_data: bytes, project_root: str, max_entries: int = MAX_ARCHIVE_ENTRIES) -> List[str]:
    """
    Safely extract a ZIP archive into a project root.
    Returns list of extracted relative paths.
    """
    if len(zip_data) > MAX_ARCHIVE_SIZE:
        raise PathValidationError(f"Archive exceeds maximum size of {MAX_ARCHIVE_SIZE} bytes")

    extracted = []
    root = os.path.realpath(project_root)

    with zipfile.ZipFile(io.BytesIO(zip_data), 'r') as zf:
        entries = zf.infolist()
        if len(entries) > max_entries:
            raise PathValidationError(f"Archive has too many entries: {len(entries)} > {max_entries}")

        for entry in entries:
            if entry.is_dir():
                continue
            if '__pycache__' in entry.filename:
                continue

            try:
                full_path = resolve_safe_path(root, entry.filename)
            except PathValidationError:
                raise PathValidationError(f"Unsafe path in archive: {entry.filename}")

            if entry.file_size > MAX_FILE_SIZE:
                raise PathValidationError(f"File in archive too large: {entry.filename}")

            _, ext = os.path.splitext(entry.filename.lower())
            if ext in BLOCKED_EXTENSIONS:
                continue

            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, 'wb') as f:
                f.write(zf.read(entry.filename))
            extracted.append(entry.filename)

    return extracted


def safe_create_project_zip(project_root: str, output_path: str) -> str:
    """Create a ZIP archive of the project root, skipping __pycache__ and .git."""
    root = os.path.realpath(project_root)
    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in ('__pycache__', '.git')]
            for filename in filenames:
                file_path = os.path.join(dirpath, filename)
                arcname = os.path.relpath(file_path, root)
                zf.write(file_path, arcname)
    return output_path


def list_project_files(project_root: str, include_dirs: bool = False) -> List[dict]:
    """List all files in a project root, returning relative paths and metadata."""
    root = os.path.realpath(project_root)
    files = []
    if not os.path.exists(root):
        return files

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in ('__pycache__', '.git')]
        if include_dirs:
            for d in sorted(dirnames):
                full = os.path.join(dirpath, d)
                rel = os.path.relpath(full, root)
                files.append({'path': rel, 'type': 'dir'})
        for f in sorted(filenames):
            full = os.path.join(dirpath, f)
            rel = os.path.relpath(full, root)
            size = os.path.getsize(full)
            files.append({'path': rel, 'type': 'file', 'size': size})
    return files


def is_safe_filename(filename: str) -> bool:
    """Check if a filename is safe (no path separators, no traversal)."""
    if not filename or filename in ('.', '..'):
        return False
    if '/' in filename or '\\' in filename:
        return False
    if filename.startswith('/'):
        return False
    _, ext = os.path.splitext(filename.lower())
    if ext in BLOCKED_EXTENSIONS:
        return False
    return True