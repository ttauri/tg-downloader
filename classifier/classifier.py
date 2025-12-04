"""
Video classifier using NudeNet AI detection.

Core classification logic for analyzing video content.

=============================================================================
HOW CLASSIFICATION WORKS
=============================================================================

1. FRAME EXTRACTION
   - Video is sampled at evenly-spaced intervals
   - Adaptive frame count based on video duration:
     * < 10 seconds:  ~5 frames/sec (min 10 frames)
     * 10-60 seconds: 50-100 frames (scales with duration)
     * > 60 seconds:  100 frames (configurable)

2. DETECTION
   - Each frame is analyzed by NudeNet AI detector
   - Detector returns labels with confidence scores (0.0-1.0)
   - Only detections above threshold (default 0.4) are counted
   - Each label counted once per frame (avoids >100% from multiple detections)

3. PERCENTAGE CALCULATION
   - For each label: (frames_with_label / total_frames_analyzed) * 100
   - Example: if 30 of 100 frames contain FEMALE_BREAST_EXPOSED -> 30%

=============================================================================
RULE MATCHING
=============================================================================

Rules are evaluated in order - first matching rule wins.
Each rule can have three types of conditions:

1. thresholds (AND logic)
   - ALL listed labels must meet or exceed their minimum percentage
   - Example: {"MALE_GENITALIA_EXPOSED": 3, "FEMALE_GENITALIA_EXPOSED": 3}
   - Matches only if BOTH labels are >= 3%

2. thresholds_any (OR logic)
   - ANY ONE of the listed labels must meet or exceed its minimum percentage
   - Example: {"FEMALE_GENITALIA_EXPOSED": 10, "ANUS_EXPOSED": 10}
   - Matches if EITHER label is >= 10%

3. exclude (exclusion logic)
   - Listed labels must be BELOW their maximum percentage
   - Example: {"MALE_GENITALIA_EXPOSED": 2}
   - Fails if MALE_GENITALIA_EXPOSED >= 2%

RULE EVALUATION ORDER:
   1. Check exclude conditions first (if any fail -> rule doesn't match)
   2. Check thresholds (AND) - all must pass
   3. Check thresholds_any (OR) - at least one must pass
   4. Rule must have at least one of: thresholds or thresholds_any

=============================================================================
EXAMPLE RULES
=============================================================================

Rule: Solo female explicit content
{
    "dir_name": "solo_f_explicit",
    "description": "Solo female explicit (genitalia/anus)",
    "thresholds_any": {
        "FEMALE_GENITALIA_EXPOSED": 10,    # OR
        "ANUS_EXPOSED": 10
    },
    "exclude": {
        "MALE_GENITALIA_EXPOSED": 2        # Must NOT have male content
    }
}

This rule matches if:
- (FEMALE_GENITALIA_EXPOSED >= 10% OR ANUS_EXPOSED >= 10%)
- AND MALE_GENITALIA_EXPOSED <= 2%

=============================================================================
AVAILABLE LABELS
=============================================================================

- FEMALE_GENITALIA_COVERED  - Covered female genitalia
- FEMALE_GENITALIA_EXPOSED  - Exposed female genitalia
- FEMALE_BREAST_EXPOSED     - Exposed female breasts
- BUTTOCKS_EXPOSED          - Exposed buttocks
- ANUS_EXPOSED              - Exposed anus
- MALE_GENITALIA_EXPOSED    - Exposed male genitalia
- MALE_BREAST_EXPOSED       - Exposed male chest
- FACE_MALE                 - Male face detected

=============================================================================
"""

import json
import os
import shutil
import tempfile
from typing import Callable, Dict, List, Optional

import cv2
import yaml
from nudenet import NudeDetector


# Detection labels that the classifier looks for
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
    "threshold": 0.4,
    "num_frames": 100,
    "video_extensions": [".mp4", ".avi", ".mov", ".mkv", ".webm"],
    "model_path": "",  # Empty = use default 320n model
    "model_resolution": 320,  # Must match model: 320 for 320n, 640 for 640m
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
                config.update(yaml.safe_load(f))
            else:
                config.update(json.load(f))
    return config


def save_config(config: dict, path: str):
    """Save config to a YAML or JSON file."""
    with open(path, "w") as f:
        if _is_yaml(path):
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)
        else:
            json.dump(config, f, indent=2)


def load_rules(path: str) -> List[dict]:
    """Load classification rules from a YAML or JSON file."""
    if not path or not os.path.exists(path):
        raise FileNotFoundError(f"Rules file not found: {path}")
    with open(path, "r") as f:
        if _is_yaml(path):
            data = yaml.safe_load(f)
            # YAML format has rules under 'rules' key
            return data.get('rules', data) if isinstance(data, dict) else data
        else:
            return json.load(f)


def save_rules(rules: List[dict], path: str):
    """Save classification rules to a YAML or JSON file."""
    with open(path, "w") as f:
        if _is_yaml(path):
            yaml.dump({'rules': rules}, f, default_flow_style=False, sort_keys=False)
        else:
            json.dump(rules, f, indent=2)


def classify_video(
    video_path: str,
    detector: NudeDetector,
    threshold: float = 0.4,
    num_frames: int = 100,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    include_all_labels: bool = False,
) -> Dict[str, float]:
    """
    Classify a video by analyzing frames.

    Args:
        video_path: Path to the video file
        detector: NudeNet detector instance
        threshold: Minimum confidence score for detections (0.0-1.0)
        num_frames: Max number of frames to analyze (adjusted for short videos)
        progress_callback: Optional callback(current_frame, total_frames)
        include_all_labels: If True, return dict with 'classifications' and 'metadata'

    Returns:
        If include_all_labels=False: Dict mapping label names to percentage of frames
        If include_all_labels=True: Dict with 'classifications' and 'metadata'
    """
    cap = cv2.VideoCapture(video_path)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS)

    if fps <= 0 or total_frames <= 0:
        cap.release()
        if include_all_labels:
            return {"classifications": {}, "metadata": {}}
        return {}

    duration = total_frames / fps

    # Adaptive frame count: for short videos use fewer frames
    # - Videos < 10s: ~5 frames per second
    # - Videos 10-60s: scale from 50 to 100 frames
    # - Videos > 60s: use num_frames (default 100)
    if duration < 10:
        actual_frames = max(10, int(duration * 5))
    elif duration < 60:
        actual_frames = max(50, min(num_frames, int(duration * 1.5)))
    else:
        actual_frames = num_frames

    classifications = {}  # All detected labels

    # Calculate time interval between frames
    time_interval = duration / actual_frames

    # Use temp file for frame extraction
    temp_fd, temp_path = tempfile.mkstemp(suffix=".jpg")
    os.close(temp_fd)

    analyzed_frames = 0
    try:
        for i in range(actual_frames):
            cap.set(cv2.CAP_PROP_POS_MSEC, i * time_interval * 1000)
            ret, frame = cap.read()
            if not ret:
                break

            cv2.imwrite(temp_path, frame)
            result = detector.detect(temp_path)

            # Track labels per frame (only above threshold)
            frame_labels = set()

            for detected_object in result:
                label = detected_object["class"]
                score = detected_object["score"]
                if label in ALLOWED_LABELS and score >= threshold:
                    frame_labels.add(label)

            # Increment counts
            for label in frame_labels:
                classifications[label] = classifications.get(label, 0) + 1

            analyzed_frames += 1

            if progress_callback:
                progress_callback(i + 1, actual_frames)

    finally:
        cap.release()
        if os.path.exists(temp_path):
            os.remove(temp_path)

    # Calculate percentages
    if analyzed_frames > 0:
        for label in classifications:
            classifications[label] = (classifications[label] / analyzed_frames) * 100

    if include_all_labels:
        return {
            "classifications": classifications,
            "metadata": {
                "duration": round(duration, 2),
                "total_frames": total_frames,
                "analyzed_frames": analyzed_frames,
                "fps": round(fps, 2),
            }
        }

    return classifications


def matches_rule(classifications: Dict[str, float], rule: dict) -> bool:
    """
    Check if classifications match a rule.

    Rule structure:
        - thresholds: ALL labels must meet minimum % (AND logic)
        - thresholds_any: ANY label must meet minimum % (OR logic)
        - exclude: labels must NOT exceed these values
    """
    # Check exclusions first - if any excluded label meets/exceeds threshold, rule fails
    if "exclude" in rule:
        for label, max_pct in rule["exclude"].items():
            if label in classifications and classifications[label] >= max_pct:
                return False

    # Check required thresholds (AND logic) - all must match
    if "thresholds" in rule:
        for label, min_pct in rule["thresholds"].items():
            if label not in classifications or classifications[label] < min_pct:
                return False

    # Check any thresholds (OR logic) - at least one must match
    if "thresholds_any" in rule:
        any_matched = False
        for label, min_pct in rule["thresholds_any"].items():
            if label in classifications and classifications[label] >= min_pct:
                any_matched = True
                break
        if not any_matched:
            return False

    # Rule must have at least one of thresholds or thresholds_any
    if "thresholds" not in rule and "thresholds_any" not in rule:
        return False

    return True


def get_matching_rule(
    classifications: Dict[str, float], rules: List[dict]
) -> Optional[dict]:
    """Find the first rule that matches the classifications."""
    for rule in rules:
        if matches_rule(classifications, rule):
            return rule
    return None


def classify_and_sort(
    input_dir: str,
    output_dir: str,
    rules: List[dict],
    config: Optional[dict] = None,
    dry_run: bool = False,
    on_video_start: Optional[Callable[[int, int, str], None]] = None,
    on_video_done: Optional[Callable[[str, dict, Optional[str]], None]] = None,
) -> dict:
    """
    Classify and sort all videos in a directory.

    Args:
        input_dir: Directory containing videos
        output_dir: Directory to move sorted videos to
        rules: Classification rules (required)
        config: Classification configuration (uses defaults if None)
        dry_run: If True, don't actually move files
        on_video_start: Callback(index, total, filename) when starting a video
        on_video_done: Callback(filename, classifications, category) when done

    Returns:
        Dict with 'processed', 'errors', 'by_category' stats
    """
    if config is None:
        config = DEFAULT_CONFIG.copy()

    extensions = config.get("video_extensions", DEFAULT_CONFIG["video_extensions"])
    threshold = config.get("threshold", DEFAULT_CONFIG["threshold"])
    num_frames = config.get("num_frames", DEFAULT_CONFIG["num_frames"])

    # Get list of video files
    files = [
        f for f in os.listdir(input_dir)
        if os.path.splitext(f)[1].lower() in extensions
    ]

    if not files:
        return {"processed": 0, "errors": 0, "by_category": {}}

    if not dry_run:
        os.makedirs(output_dir, exist_ok=True)

    # Initialize detector
    detector = NudeDetector()

    stats = {"processed": 0, "errors": 0, "by_category": {}}

    for i, filename in enumerate(files, 1):
        video_path = os.path.join(input_dir, filename)

        if on_video_start:
            on_video_start(i, len(files), filename)

        # Classify the video
        try:
            classifications = classify_video(
                video_path,
                detector,
                threshold=threshold,
                num_frames=num_frames,
            )
        except Exception as e:
            stats["errors"] += 1
            if on_video_done:
                on_video_done(filename, {}, f"ERROR: {e}")
            continue

        # Find matching rule
        matched_rule = get_matching_rule(classifications, rules)
        category = matched_rule["dir_name"] if matched_rule else "unclassified"

        # Move file
        rule_dir = os.path.join(output_dir, category)
        dest_path = os.path.join(rule_dir, filename)

        if not dry_run:
            os.makedirs(rule_dir, exist_ok=True)
            shutil.move(video_path, dest_path)

        stats["by_category"][category] = stats["by_category"].get(category, 0) + 1
        stats["processed"] += 1

        if on_video_done:
            on_video_done(filename, classifications, category)

    return stats
