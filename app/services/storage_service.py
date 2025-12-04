import hashlib
import os
from pathlib import Path
from typing import Optional
from collections import defaultdict

from app.config import settings
from app.services.helper_functions import sanitize_dirname


CHUNK_SIZE = 1024 * 1024  # 1MB for partial hash


def compute_file_hash(file_path: str) -> Optional[str]:
    """
    Compute SHA256 hash of first 1MB + last 1MB of file.
    For files smaller than 2MB, hash the entire file.
    Returns None if file doesn't exist or can't be read.
    """
    try:
        file_size = os.path.getsize(file_path)
        hasher = hashlib.sha256()

        with open(file_path, 'rb') as f:
            if file_size <= CHUNK_SIZE * 2:
                # Small file - hash entire content
                hasher.update(f.read())
            else:
                # Large file - hash first and last 1MB
                hasher.update(f.read(CHUNK_SIZE))
                f.seek(-CHUNK_SIZE, 2)  # Seek to last 1MB
                hasher.update(f.read(CHUNK_SIZE))

        # Include file size in hash to differentiate files with same start/end
        hasher.update(str(file_size).encode())
        return hasher.hexdigest()
    except (IOError, OSError):
        return None


def get_channel_folder_path(channel_name: str) -> str:
    """Get the full path to a channel's media folder."""
    folder_name = sanitize_dirname(channel_name)
    return os.path.join(settings.media_download_path, folder_name)


def get_folder_stats(folder_path: str) -> dict:
    """
    Get statistics about files in a folder.
    Returns dict with file count, total size, extension breakdown, and file list.
    """
    stats = {
        'exists': False,
        'path': folder_path,
        'file_count': 0,
        'total_size': 0,
        'extensions': defaultdict(lambda: {'count': 0, 'size': 0}),
        'files': [],
    }

    if not os.path.exists(folder_path):
        return stats

    stats['exists'] = True

    try:
        for entry in os.scandir(folder_path):
            if entry.is_file() and not entry.name.startswith('.'):
                try:
                    file_stat = entry.stat()
                    file_size = file_stat.st_size
                    ext = Path(entry.name).suffix.lower() or '(no ext)'

                    stats['file_count'] += 1
                    stats['total_size'] += file_size
                    stats['extensions'][ext]['count'] += 1
                    stats['extensions'][ext]['size'] += file_size

                    stats['files'].append({
                        'name': entry.name,
                        'size': file_size,
                        'extension': ext,
                        'path': entry.path,
                    })
                except OSError:
                    continue
    except OSError:
        pass

    # Convert defaultdict to regular dict and sort files by name
    stats['extensions'] = dict(stats['extensions'])
    stats['files'].sort(key=lambda x: x['name'].lower())

    return stats


def get_orphaned_folder_path(channel_name: str) -> str:
    """Get the path to the _orphaned subfolder for a channel."""
    channel_folder = get_channel_folder_path(channel_name)
    return os.path.join(channel_folder, '_orphaned')


def ensure_orphaned_folder(channel_name: str) -> str:
    """Create the _orphaned folder if it doesn't exist and return its path."""
    orphaned_path = get_orphaned_folder_path(channel_name)
    os.makedirs(orphaned_path, exist_ok=True)
    return orphaned_path


def move_to_orphaned(file_path: str, channel_name: str) -> Optional[str]:
    """
    Move a file to the _orphaned folder.
    Returns new path or None if failed.
    """
    try:
        orphaned_folder = ensure_orphaned_folder(channel_name)
        filename = os.path.basename(file_path)
        new_path = os.path.join(orphaned_folder, filename)

        # Handle name collision
        counter = 1
        base, ext = os.path.splitext(filename)
        while os.path.exists(new_path):
            new_path = os.path.join(orphaned_folder, f"{base}_{counter}{ext}")
            counter += 1

        os.rename(file_path, new_path)
        return new_path
    except OSError:
        return None


def format_size(size_bytes: int) -> str:
    """Format size in bytes to human readable string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.2f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"
