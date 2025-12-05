"""
Video concatenation tool.

Concatenates multiple video files into a single output file,
normalizing resolution, framerate, and codecs.
"""

from .concat import (
    get_video_info,
    check_media_validity,
    normalize_video,
    concatenate_videos,
    process_videos,
    load_config,
    save_config,
    get_target_dimensions,
    DEFAULT_CONFIG,
    RESOLUTION_MAP,
)

__all__ = [
    "get_video_info",
    "check_media_validity",
    "normalize_video",
    "concatenate_videos",
    "process_videos",
    "load_config",
    "save_config",
    "get_target_dimensions",
    "DEFAULT_CONFIG",
    "RESOLUTION_MAP",
]
