"""
Video sorting tool.

Sorts video files into subdirectories based on various criteria:
- Orientation (horizontal vs vertical)
- Duration (short, medium, long)
- Quality/Bitrate (high, medium, low)
- Pipeline (combines orientation -> duration -> quality)
"""

from .sorter import (
    get_video_info,
    sort_by_orientation,
    sort_by_duration,
    sort_by_quality,
    sort_by_bitrate,
    sort_by_pipeline,
    split_into_folders,
    preview_videos,
    reset_sorting,
    load_config,
    save_config,
    DEFAULT_CONFIG,
    CATEGORIZATION_METHODS,
)

__all__ = [
    "get_video_info",
    "sort_by_orientation",
    "sort_by_duration",
    "sort_by_quality",
    "sort_by_bitrate",
    "sort_by_pipeline",
    "split_into_folders",
    "preview_videos",
    "reset_sorting",
    "load_config",
    "save_config",
    "DEFAULT_CONFIG",
    "CATEGORIZATION_METHODS",
]
