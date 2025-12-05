"""
Video analyzer - per-second content detection using NudeNet.

Analyzes video frame-by-frame (1 frame per second) and stores
all detection data in JSON for later timestamp generation.
"""

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional

import cv2
import yaml
from nudenet import NudeDetector


# Detection labels from NudeNet
ALLOWED_LABELS = [
    "FEMALE_GENITALIA_COVERED",
    "BUTTOCKS_EXPOSED",
    "FEMALE_BREAST_EXPOSED",
    "FEMALE_GENITALIA_EXPOSED",
    "ANUS_EXPOSED",
    "MALE_GENITALIA_EXPOSED",
    "MALE_BREAST_EXPOSED",
    "FACE_MALE",
]

DEFAULT_CONFIG = {
    "threshold": 0.4,  # Minimum confidence for detection
    "video_extensions": [".mp4", ".avi", ".mov", ".mkv", ".webm"],
    "model_path": "",
    "model_resolution": 320,
    # Unsafe criteria (for timestamp generation)
    "unsafe_labels": [
        "FEMALE_GENITALIA_EXPOSED",
        "MALE_GENITALIA_EXPOSED",
        "ANUS_EXPOSED",
    ],
    "unsafe_threshold": 0.5,
    "merge_gap": 2,  # Merge ranges closer than N seconds
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


def get_data_dir() -> Path:
    """Get directory for storing analysis JSON files."""
    script_dir = Path(__file__).resolve().parent
    data_dir = script_dir / "data"
    data_dir.mkdir(exist_ok=True)
    return data_dir


def get_analysis_path(video_filename: str) -> Path:
    """Get path to analysis JSON file for a video."""
    base_name = Path(video_filename).stem
    return get_data_dir() / f"{base_name}.json"


def load_analysis(video_filename: str) -> Optional[dict]:
    """Load existing analysis for a video."""
    path = get_analysis_path(video_filename)
    if path.exists():
        with open(path, "r") as f:
            return json.load(f)
    return None


def save_analysis(video_filename: str, analysis: dict):
    """Save analysis to JSON file."""
    path = get_analysis_path(video_filename)
    with open(path, "w") as f:
        json.dump(analysis, f, indent=2)


def analyze_video(
    video_path: str,
    detector: NudeDetector,
    threshold: float = 0.4,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> dict:
    """
    Analyze video second-by-second.

    Args:
        video_path: Path to the video file
        detector: NudeNet detector instance
        threshold: Minimum confidence score for detections
        progress_callback: Optional callback(current_second, total_seconds)

    Returns:
        Dict with video metadata and per-second detections
    """
    cap = cv2.VideoCapture(video_path)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS)

    if fps <= 0 or total_frames <= 0:
        cap.release()
        return {
            "filename": os.path.basename(video_path),
            "path": video_path,
            "duration": 0,
            "fps": 0,
            "analyzed_at": datetime.now().isoformat(),
            "error": "Could not read video properties",
            "detections": {},
        }

    duration = total_frames / fps
    total_seconds = int(duration)

    # Store detections per second
    detections: Dict[str, Dict[str, float]] = {}

    # Use temp file for frame extraction
    temp_fd, temp_path = tempfile.mkstemp(suffix=".jpg")
    os.close(temp_fd)

    try:
        for second in range(total_seconds + 1):
            # Seek to this second
            cap.set(cv2.CAP_PROP_POS_MSEC, second * 1000)
            ret, frame = cap.read()

            if not ret:
                continue

            cv2.imwrite(temp_path, frame)
            result = detector.detect(temp_path)

            # Collect detections for this second
            second_detections: Dict[str, float] = {}

            for detected_object in result:
                label = detected_object["class"]
                score = detected_object["score"]

                if label in ALLOWED_LABELS and score >= threshold:
                    # Keep highest score if label appears multiple times
                    if label not in second_detections or score > second_detections[label]:
                        second_detections[label] = round(score, 3)

            # Only store if there are detections
            if second_detections:
                detections[str(second)] = second_detections

            if progress_callback:
                progress_callback(second + 1, total_seconds + 1)

    finally:
        cap.release()
        if os.path.exists(temp_path):
            os.remove(temp_path)

    return {
        "filename": os.path.basename(video_path),
        "path": video_path,
        "duration": round(duration, 2),
        "fps": round(fps, 2),
        "total_seconds": total_seconds,
        "analyzed_at": datetime.now().isoformat(),
        "threshold": threshold,
        "detections": detections,
    }


def get_video_files(directory: str, extensions: List[str]) -> List[str]:
    """Get list of video files in directory."""
    files = []
    for f in os.listdir(directory):
        if os.path.isfile(os.path.join(directory, f)):
            if os.path.splitext(f)[1].lower() in extensions:
                files.append(f)
    return sorted(files)
