"""
Video concatenation core logic.

Provides functions to:
1. Probe video files for metadata (resolution, fps, bitrate, duration)
2. Validate video files for corruption
3. Normalize videos to common format (resolution, fps, codec)
4. Concatenate multiple videos into one output file
"""

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Dict, List, Optional

import yaml


DEFAULT_CONFIG = {
    "target_fps": 30,
    "target_resolution": "1080p",  # Options: 720p, 1080p, 1440p, 4k, source
    "aspect_ratio": "16:9",
    "video_codec": "libx264",
    "audio_codec": "aac",
    "audio_bitrate": "192k",
    "crf": 18,  # Quality: 0-51, lower = better, 18 is visually lossless
    "preset": "fast",  # Encoding speed: ultrafast, fast, medium, slow
    "video_extensions": [".mp4", ".avi", ".mov", ".mkv", ".webm"],
}

RESOLUTION_MAP = {
    "720p": (1280, 720),
    "1080p": (1920, 1080),
    "1440p": (2560, 1440),
    "4k": (3840, 2160),
}


def _is_yaml(path: str) -> bool:
    """Check if file is YAML based on extension."""
    return path.endswith(('.yaml', '.yml'))


def load_config(path: Optional[str] = None) -> dict:
    """Load config from a YAML or JSON file, or return defaults."""
    config = DEFAULT_CONFIG.copy()
    if path and os.path.exists(path):
        with open(path, "r") as f:
            if _is_yaml(path):
                loaded = yaml.safe_load(f)
            else:
                loaded = json.load(f)
            if loaded:
                config.update(loaded)
    return config


def save_config(config: dict, path: str):
    """Save config to a YAML or JSON file."""
    with open(path, "w") as f:
        if _is_yaml(path):
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)
        else:
            json.dump(config, f, indent=2)


def get_video_info(filepath: str) -> Optional[Dict]:
    """
    Get video metadata using ffprobe.

    Returns dict with: width, height, duration, fps, bitrate, codec
    """
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height,bit_rate,r_frame_rate,codec_name,duration",
                "-show_entries", "format=duration",
                "-of", "json",
                filepath,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
        )

        if result.returncode != 0:
            return None

        data = json.loads(result.stdout.decode())

        stream = data.get("streams", [{}])[0]
        format_info = data.get("format", {})

        # Parse framerate (e.g., "30/1" or "30000/1001")
        fps_str = stream.get("r_frame_rate", "0/1")
        if "/" in fps_str:
            num, den = fps_str.split("/")
            fps = float(num) / float(den) if float(den) > 0 else 0
        else:
            fps = float(fps_str)

        # Get duration from stream or format
        duration = stream.get("duration") or format_info.get("duration")

        return {
            "width": int(stream.get("width", 0)),
            "height": int(stream.get("height", 0)),
            "fps": round(fps, 2),
            "bitrate": int(stream.get("bit_rate", 0)) if stream.get("bit_rate") else None,
            "codec": stream.get("codec_name", ""),
            "duration": float(duration) if duration else None,
        }
    except Exception:
        return None


def check_media_validity(filepath: str) -> bool:
    """
    Check if a video file is valid and not corrupted.

    Uses ffmpeg to decode the entire file and check for errors.
    """
    try:
        result = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", filepath, "-c", "copy", "-f", "null", "-"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120,
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        return False
    except Exception:
        return False


def get_target_dimensions(
    source_width: int,
    source_height: int,
    target_resolution: str = "1080p",
    aspect_ratio: str = "16:9",
) -> tuple:
    """
    Calculate target dimensions based on config.

    Args:
        source_width: Original video width
        source_height: Original video height
        target_resolution: Target resolution (720p, 1080p, etc. or "source")
        aspect_ratio: Target aspect ratio (16:9, 4:3, or "source")

    Returns:
        (width, height) tuple
    """
    # Parse aspect ratio
    if aspect_ratio == "source":
        target_ratio = source_width / source_height if source_height > 0 else 16/9
    else:
        parts = aspect_ratio.split(":")
        target_ratio = float(parts[0]) / float(parts[1])

    # Get base resolution
    if target_resolution == "source":
        base_width, base_height = source_width, source_height
    else:
        base_width, base_height = RESOLUTION_MAP.get(target_resolution, (1920, 1080))

    # Adjust for aspect ratio
    if base_width / base_height > target_ratio:
        # Too wide, adjust width
        width = int(base_height * target_ratio)
        height = base_height
    else:
        # Too tall, adjust height
        width = base_width
        height = int(base_width / target_ratio)

    # Ensure even dimensions (required by most codecs)
    width = width + (width % 2)
    height = height + (height % 2)

    return width, height


def normalize_video(
    input_path: str,
    output_path: str,
    target_width: int,
    target_height: int,
    target_fps: int = 30,
    config: Optional[dict] = None,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> bool:
    """
    Normalize a video to target resolution, fps, and codec.

    Returns True if successful, False otherwise.
    """
    if config is None:
        config = DEFAULT_CONFIG

    video_codec = config.get("video_codec", "libx264")
    audio_codec = config.get("audio_codec", "aac")
    audio_bitrate = config.get("audio_bitrate", "192k")
    crf = config.get("crf", 18)
    preset = config.get("preset", "fast")

    # Video filter: scale with padding to maintain aspect ratio
    filter_complex = (
        f"scale={target_width}:{target_height}:force_original_aspect_ratio=decrease,"
        f"pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2,"
        f"setsar=1,format=yuv420p"
    )

    cmd = [
        "ffmpeg",
        "-i", input_path,
        "-vf", filter_complex,
        "-r", str(target_fps),
        "-c:v", video_codec,
        "-preset", preset,
        "-crf", str(crf),
        "-c:a", audio_codec,
        "-b:a", audio_bitrate,
        "-y",
        output_path,
    ]

    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=600,  # 10 minute timeout per video
        )

        if result.returncode != 0:
            # Try without audio
            if progress_callback:
                progress_callback("Retrying without audio...")

            cmd_no_audio = [
                "ffmpeg",
                "-i", input_path,
                "-vf", filter_complex,
                "-r", str(target_fps),
                "-c:v", video_codec,
                "-preset", preset,
                "-crf", str(crf),
                "-an",  # No audio
                "-y",
                output_path,
            ]

            result = subprocess.run(
                cmd_no_audio,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=600,
            )

        return result.returncode == 0

    except subprocess.TimeoutExpired:
        return False
    except Exception:
        return False


def concatenate_videos(
    input_files: List[str],
    output_path: str,
    config: Optional[dict] = None,
) -> bool:
    """
    Concatenate pre-normalized videos into a single file.

    All input files must have the same resolution, fps, and codec.
    """
    if not input_files:
        return False

    if config is None:
        config = DEFAULT_CONFIG

    audio_codec = config.get("audio_codec", "aac")
    audio_bitrate = config.get("audio_bitrate", "192k")

    # Create concat list file
    concat_list = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False)
    try:
        for f in input_files:
            # Escape single quotes in filenames
            escaped = f.replace("'", "'\\''")
            concat_list.write(f"file '{escaped}'\n")
        concat_list.close()

        cmd = [
            "ffmpeg",
            "-f", "concat",
            "-safe", "0",
            "-i", concat_list.name,
            "-c:v", "copy",
            "-c:a", audio_codec,
            "-b:a", audio_bitrate,
            "-af", "aresample=async=1000",
            "-vsync", "vfr",
            "-max_muxing_queue_size", "1024",
            "-shortest",
            "-y",
            output_path,
        ]

        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=1800,  # 30 minute timeout for concat
        )

        return result.returncode == 0

    finally:
        os.unlink(concat_list.name)


def process_videos(
    input_dir: str,
    output_file: str,
    config: Optional[dict] = None,
    on_progress: Optional[Callable[[int, int, str, str], None]] = None,
    validate: bool = True,
) -> dict:
    """
    Process all videos in a directory and concatenate them.

    Args:
        input_dir: Directory containing video files
        output_file: Output file path
        config: Configuration dict (uses defaults if None)
        on_progress: Callback(current, total, filename, status)
        validate: If True, validate files before processing

    Returns:
        Dict with stats: processed, skipped, errors, output_path
    """
    if config is None:
        config = DEFAULT_CONFIG.copy()

    extensions = config.get("video_extensions", DEFAULT_CONFIG["video_extensions"])
    target_fps = config.get("target_fps", 30)
    target_resolution = config.get("target_resolution", "1080p")
    aspect_ratio = config.get("aspect_ratio", "16:9")

    # Get video files
    files = sorted([
        os.path.join(input_dir, f)
        for f in os.listdir(input_dir)
        if os.path.splitext(f)[1].lower() in extensions
    ])

    if not files:
        return {"processed": 0, "skipped": 0, "errors": 0, "output_path": None}

    stats = {"processed": 0, "skipped": 0, "errors": 0, "output_path": None}

    # Determine target dimensions
    # Use first valid video as reference if target_resolution is "source"
    if target_resolution == "source":
        for f in files:
            info = get_video_info(f)
            if info and info["width"] and info["height"]:
                target_width, target_height = get_target_dimensions(
                    info["width"], info["height"], "source", aspect_ratio
                )
                break
        else:
            target_width, target_height = 1920, 1080
    else:
        target_width, target_height = get_target_dimensions(
            1920, 1080, target_resolution, aspect_ratio
        )

    # Create temp directory for normalized videos
    temp_dir = tempfile.mkdtemp(prefix="concat_")
    temp_files = []

    try:
        # Phase 1: Validate and normalize videos
        for i, filepath in enumerate(files):
            filename = os.path.basename(filepath)

            if on_progress:
                on_progress(i + 1, len(files), filename, "Checking...")

            # Validate
            if validate and not check_media_validity(filepath):
                if on_progress:
                    on_progress(i + 1, len(files), filename, "Skipped (invalid)")
                stats["skipped"] += 1
                continue

            # Normalize
            if on_progress:
                on_progress(i + 1, len(files), filename, "Normalizing...")

            temp_file = os.path.join(temp_dir, f"temp_{i:04d}.mp4")

            success = normalize_video(
                filepath,
                temp_file,
                target_width,
                target_height,
                target_fps,
                config,
            )

            if success and os.path.exists(temp_file):
                temp_files.append(temp_file)
                stats["processed"] += 1
                if on_progress:
                    on_progress(i + 1, len(files), filename, "Done")
            else:
                stats["errors"] += 1
                if on_progress:
                    on_progress(i + 1, len(files), filename, "Error")

        # Phase 2: Concatenate
        if temp_files:
            if on_progress:
                on_progress(len(files), len(files), "Concatenating...", "")

            success = concatenate_videos(temp_files, output_file, config)

            if success:
                stats["output_path"] = output_file
            else:
                stats["errors"] += 1

    finally:
        # Cleanup temp directory
        shutil.rmtree(temp_dir, ignore_errors=True)

    return stats
