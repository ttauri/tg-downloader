"""
Video sorting core logic.

Provides functions to sort videos by:
- Orientation (horizontal vs vertical)
- Duration (short, medium, long)
- Quality/Bitrate (high, medium, low)
- Pipeline (combines all criteria into nested hierarchy)

Supports multiple categorization methods:
- fixed: Use fixed thresholds from config
- percentile: Split by percentiles (33rd, 66th)
- stddev: Use mean ± standard deviation
- kmeans: K-means clustering to find natural groups
- jenks: Jenks natural breaks optimization
"""

import json
import math
import os
import shutil
import subprocess
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import yaml


# Available categorization methods
CATEGORIZATION_METHODS = ["fixed", "percentile", "stddev", "kmeans", "jenks"]

DEFAULT_CONFIG = {
    "video_extensions": [".mp4", ".avi", ".mov", ".mkv", ".webm", ".flv", ".wmv"],
    # Categorization method: fixed, percentile, stddev, kmeans, jenks
    "duration_method": "fixed",
    "quality_method": "fixed",
    # Duration thresholds in seconds (for fixed method)
    "duration_short_max": 60,      # < 60s = short
    "duration_medium_max": 300,    # 60s - 5min = medium, > 5min = long
    # Quality ratio thresholds (actual_bitrate / optimal_bitrate) (for fixed method)
    "quality_high_min": 1.0,       # >= 100% of optimal = high
    "quality_medium_min": 0.5,     # >= 50% of optimal = medium, < 50% = low
    # Bitrate compression factor for optimal bitrate calculation
    "bitrate_factor": 0.13,        # For h264/h265 encoded video
    # Number of categories for dynamic methods (2 or 3)
    "num_categories": 3,
    # Simple bitrate threshold for low/normal sorting (in Kbps)
    "bitrate_threshold": 300,      # < 300 Kbps = low, >= 300 Kbps = normal
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
                "-show_entries", "format=duration,bit_rate",
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
            fps = float(fps_str) if fps_str else 0

        # Get duration from stream or format
        duration = stream.get("duration") or format_info.get("duration")

        # Get bitrate from stream or format
        bitrate = stream.get("bit_rate") or format_info.get("bit_rate")

        width = int(stream.get("width", 0))
        height = int(stream.get("height", 0))

        return {
            "width": width,
            "height": height,
            "fps": round(fps, 2) if fps else 0,
            "bitrate": int(bitrate) if bitrate else 0,
            "codec": stream.get("codec_name", ""),
            "duration": float(duration) if duration else 0,
            "orientation": "horizontal" if width >= height else "vertical",
        }
    except Exception:
        return None


def calculate_optimal_bitrate(width: int, height: int, fps: float, factor: float = 0.13) -> float:
    """
    Calculate optimal bitrate based on resolution and frame rate.

    Uses realistic bitrates for h264/h265 encoded video:
    - 1080p@30fps: ~8 Mbps optimal
    - 720p@30fps: ~3.6 Mbps optimal
    - 480p@30fps: ~1.6 Mbps optimal
    """
    if fps <= 0:
        fps = 30
    return width * height * fps * factor


# =============================================================================
# DYNAMIC CATEGORIZATION METHODS
# =============================================================================

def _percentile(values: List[float], p: float) -> float:
    """Calculate the p-th percentile of a list of numbers."""
    if not values:
        return 0
    sorted_values = sorted(values)
    k = (len(sorted_values) - 1) * p
    f = int(k)
    c = k - f
    if f + 1 < len(sorted_values):
        return sorted_values[f] * (1 - c) + sorted_values[f + 1] * c
    return sorted_values[f]


def _mean(values: List[float]) -> float:
    """Calculate mean of a list."""
    if not values:
        return 0
    return sum(values) / len(values)


def _stddev(values: List[float]) -> float:
    """Calculate standard deviation of a list."""
    if len(values) < 2:
        return 0
    mean = _mean(values)
    variance = sum((x - mean) ** 2 for x in values) / len(values)
    return math.sqrt(variance)


def calculate_thresholds_percentile(values: List[float], num_categories: int = 3) -> List[float]:
    """
    Calculate thresholds using percentiles.

    For 3 categories: 33rd and 66th percentile
    For 2 categories: 50th percentile (median)
    """
    if not values:
        return []

    if num_categories == 2:
        return [_percentile(values, 0.5)]
    else:
        return [_percentile(values, 0.33), _percentile(values, 0.66)]


def calculate_thresholds_stddev(values: List[float], num_categories: int = 3) -> List[float]:
    """
    Calculate thresholds using mean ± standard deviation.

    For 3 categories: mean - 0.5*std, mean + 0.5*std
    For 2 categories: mean
    """
    if not values:
        return []

    mean = _mean(values)
    std = _stddev(values)

    if num_categories == 2:
        return [max(0, mean)]
    else:
        # Ensure thresholds are non-negative
        lower = max(0, mean - 0.5 * std)
        upper = mean + 0.5 * std
        return [lower, upper]


def calculate_thresholds_kmeans(values: List[float], num_categories: int = 3, max_iter: int = 100) -> List[float]:
    """
    Calculate thresholds using K-means clustering.

    Simple 1D K-means implementation to find natural groupings.
    """
    if not values or len(values) < num_categories:
        return []

    sorted_values = sorted(values)

    # Initialize centroids evenly spaced
    min_val, max_val = min(values), max(values)
    if min_val == max_val:
        return []

    centroids = [min_val + (max_val - min_val) * (i + 0.5) / num_categories
                 for i in range(num_categories)]

    for _ in range(max_iter):
        # Assign points to nearest centroid
        clusters = [[] for _ in range(num_categories)]
        for v in values:
            distances = [abs(v - c) for c in centroids]
            nearest = distances.index(min(distances))
            clusters[nearest].append(v)

        # Update centroids
        new_centroids = []
        for i, cluster in enumerate(clusters):
            if cluster:
                new_centroids.append(_mean(cluster))
            else:
                new_centroids.append(centroids[i])

        # Check convergence
        if new_centroids == centroids:
            break
        centroids = new_centroids

    # Sort centroids and find midpoints as thresholds
    centroids = sorted(centroids)
    thresholds = []
    for i in range(len(centroids) - 1):
        thresholds.append((centroids[i] + centroids[i + 1]) / 2)

    return thresholds


def calculate_thresholds_jenks(values: List[float], num_categories: int = 3) -> List[float]:
    """
    Calculate thresholds using Jenks natural breaks optimization.

    Minimizes within-class variance while maximizing between-class variance.
    """
    if not values or len(values) < num_categories:
        return []

    sorted_values = sorted(values)
    n = len(sorted_values)

    if n <= num_categories:
        return sorted_values[:-1]

    # For small datasets, use simplified approach
    if n < 20:
        return calculate_thresholds_percentile(values, num_categories)

    # Jenks algorithm (simplified for performance)
    # Use dynamic programming approach

    # Build matrices
    lower_class_limits = [[0] * (num_categories + 1) for _ in range(n + 1)]
    variance_combinations = [[float('inf')] * (num_categories + 1) for _ in range(n + 1)]

    for i in range(1, num_categories + 1):
        lower_class_limits[1][i] = 1
        variance_combinations[1][i] = 0

    for l in range(2, n + 1):
        s1 = 0
        s2 = 0
        for m in range(1, l + 1):
            i = l - m + 1
            val = sorted_values[i - 1]
            s1 += val
            s2 += val * val
            v = s2 - (s1 * s1) / m

            if i > 1:
                for j in range(2, num_categories + 1):
                    if variance_combinations[l][j] >= v + variance_combinations[i - 1][j - 1]:
                        lower_class_limits[l][j] = i
                        variance_combinations[l][j] = v + variance_combinations[i - 1][j - 1]

        lower_class_limits[l][1] = 1
        variance_combinations[l][1] = v

    # Extract breaks
    breaks = []
    k = n
    for j in range(num_categories, 1, -1):
        idx = lower_class_limits[k][j] - 1
        if 0 <= idx < n:
            breaks.append(sorted_values[idx])
        k = lower_class_limits[k][j] - 1

    breaks = sorted(breaks)
    return breaks if len(breaks) == num_categories - 1 else calculate_thresholds_percentile(values, num_categories)


def calculate_dynamic_thresholds(
    values: List[float],
    method: str = "percentile",
    num_categories: int = 3
) -> Tuple[List[float], Dict]:
    """
    Calculate thresholds using the specified method.

    Returns:
        Tuple of (thresholds list, info dict with method details)
    """
    if not values:
        return [], {"method": method, "error": "No values"}

    if method == "fixed":
        return [], {"method": "fixed", "message": "Using fixed thresholds from config"}

    elif method == "percentile":
        thresholds = calculate_thresholds_percentile(values, num_categories)
        return thresholds, {
            "method": "percentile",
            "description": f"Split at {100//num_categories}% intervals",
        }

    elif method == "stddev":
        thresholds = calculate_thresholds_stddev(values, num_categories)
        mean = _mean(values)
        std = _stddev(values)
        return thresholds, {
            "method": "stddev",
            "description": f"Mean={mean:.1f}, StdDev={std:.1f}",
            "mean": mean,
            "stddev": std,
        }

    elif method == "kmeans":
        thresholds = calculate_thresholds_kmeans(values, num_categories)
        return thresholds, {
            "method": "kmeans",
            "description": "K-means clustering",
        }

    elif method == "jenks":
        thresholds = calculate_thresholds_jenks(values, num_categories)
        return thresholds, {
            "method": "jenks",
            "description": "Jenks natural breaks",
        }

    else:
        # Fallback to percentile
        thresholds = calculate_thresholds_percentile(values, num_categories)
        return thresholds, {
            "method": "percentile",
            "description": "Fallback to percentile",
        }


def categorize_by_thresholds(value: float, thresholds: List[float], labels: List[str]) -> str:
    """
    Categorize a value based on thresholds.

    For 3 categories with thresholds [t1, t2]:
        value < t1 -> labels[0] (e.g., "short")
        t1 <= value < t2 -> labels[1] (e.g., "medium")
        value >= t2 -> labels[2] (e.g., "long")
    """
    if not thresholds:
        return labels[1] if len(labels) > 1 else labels[0]

    for i, threshold in enumerate(thresholds):
        if value < threshold:
            return labels[i]
    return labels[-1]


def categorize_video(info: Dict, config: dict) -> Dict:
    """
    Categorize a video based on orientation, duration, and quality.

    Returns dict with: orientation, duration_cat, quality_cat
    """
    # Orientation
    orientation = info.get("orientation", "horizontal")

    # Duration category
    duration = info.get("duration", 0)
    short_max = config.get("duration_short_max", 60)
    medium_max = config.get("duration_medium_max", 300)

    if duration < short_max:
        duration_cat = "short"
    elif duration < medium_max:
        duration_cat = "medium"
    else:
        duration_cat = "long"

    # Quality category
    bitrate = info.get("bitrate", 0)
    width = info.get("width", 0)
    height = info.get("height", 0)
    fps = info.get("fps", 30)
    factor = config.get("bitrate_factor", 0.13)

    optimal = calculate_optimal_bitrate(width, height, fps, factor)

    high_min = config.get("quality_high_min", 1.0)
    medium_min = config.get("quality_medium_min", 0.5)

    if optimal > 0 and bitrate > 0:
        quality_ratio = bitrate / optimal
        if quality_ratio >= high_min:
            quality_cat = "high"
        elif quality_ratio >= medium_min:
            quality_cat = "medium"
        else:
            quality_cat = "low"
    else:
        quality_cat = "unknown"

    return {
        "orientation": orientation,
        "duration_cat": duration_cat,
        "quality_cat": quality_cat,
        "duration": duration,
        "bitrate": bitrate,
        "optimal_bitrate": optimal,
    }


def analyze_videos(
    directory: str,
    config: Optional[dict] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
) -> Dict:
    """
    Analyze all videos in directory and collect raw metadata.

    This is the first step before categorization - collects all video info
    so we can calculate dynamic thresholds.
    """
    if config is None:
        config = DEFAULT_CONFIG.copy()

    extensions = config.get("video_extensions", DEFAULT_CONFIG["video_extensions"])

    # Get video files
    files = sorted([
        f for f in os.listdir(directory)
        if os.path.isfile(os.path.join(directory, f))
        and os.path.splitext(f)[1].lower() in extensions
    ])

    if not files:
        return {"files": [], "errors": [], "total": 0}

    analyzed = []
    errors = []

    for i, filename in enumerate(files):
        filepath = os.path.join(directory, filename)

        if on_progress:
            on_progress(i + 1, len(files), filename)

        info = get_video_info(filepath)
        if not info:
            errors.append(filename)
            continue

        # Calculate quality ratio
        factor = config.get("bitrate_factor", 0.13)
        optimal = calculate_optimal_bitrate(info["width"], info["height"], info["fps"], factor)
        quality_ratio = info["bitrate"] / optimal if optimal > 0 and info["bitrate"] > 0 else 0

        analyzed.append({
            "filename": filename,
            "filepath": filepath,
            **info,
            "optimal_bitrate": optimal,
            "quality_ratio": quality_ratio,
        })

    return {
        "files": analyzed,
        "errors": errors,
        "total": len(files),
    }


def preview_videos(
    directory: str,
    config: Optional[dict] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
) -> Dict:
    """
    Preview videos in directory - analyze and categorize without moving.

    Uses dynamic thresholds based on the configured method.
    Returns dict with file list, categorization stats, and threshold info.
    """
    if config is None:
        config = DEFAULT_CONFIG.copy()

    # First, analyze all videos
    analysis = analyze_videos(directory, config, on_progress)
    files = analysis["files"]

    if not files:
        return {"files": [], "stats": {}, "errors": analysis["errors"], "total": 0}

    # Get methods from config
    duration_method = config.get("duration_method", "fixed")
    quality_method = config.get("quality_method", "fixed")
    num_categories = config.get("num_categories", 3)

    # Calculate dynamic thresholds for duration
    durations = [f["duration"] for f in files if f["duration"] > 0]
    if duration_method != "fixed":
        duration_thresholds, duration_info = calculate_dynamic_thresholds(
            durations, duration_method, num_categories
        )
    else:
        duration_thresholds = [
            config.get("duration_short_max", 60),
            config.get("duration_medium_max", 300),
        ]
        duration_info = {"method": "fixed", "thresholds": duration_thresholds}

    # Calculate dynamic thresholds for quality
    quality_ratios = [f["quality_ratio"] for f in files if f["quality_ratio"] > 0]
    if quality_method != "fixed":
        quality_thresholds, quality_info = calculate_dynamic_thresholds(
            quality_ratios, quality_method, num_categories
        )
    else:
        quality_thresholds = [
            config.get("quality_medium_min", 0.5),
            config.get("quality_high_min", 1.0),
        ]
        quality_info = {"method": "fixed", "thresholds": quality_thresholds}

    # Define labels based on number of categories
    # Include threshold info in folder names for clarity
    if num_categories == 2:
        if duration_thresholds:
            t = duration_thresholds[0]
            duration_labels = [f"short_under_{int(t)}s", f"long_over_{int(t)}s"]
        else:
            duration_labels = ["short", "long"]

        if quality_thresholds:
            t = quality_thresholds[0]
            quality_labels = [f"low_under_{int(t*100)}pct", f"high_over_{int(t*100)}pct"]
        else:
            quality_labels = ["low", "high"]
    else:
        if len(duration_thresholds) >= 2:
            t1, t2 = duration_thresholds[0], duration_thresholds[1]
            duration_labels = [
                f"short_under_{int(t1)}s",
                f"medium_{int(t1)}s-{int(t2)}s",
                f"long_over_{int(t2)}s"
            ]
        else:
            duration_labels = ["short", "medium", "long"]

        if len(quality_thresholds) >= 2:
            t1, t2 = quality_thresholds[0], quality_thresholds[1]
            quality_labels = [
                f"low_under_{int(t1*100)}pct",
                f"medium_{int(t1*100)}-{int(t2*100)}pct",
                f"high_over_{int(t2*100)}pct"
            ]
        else:
            quality_labels = ["low", "medium", "high"]

    # Now categorize each video using calculated thresholds
    stats = {
        "orientation": {"horizontal": 0, "vertical": 0},
        "duration": {label: 0 for label in duration_labels},
        "quality": {label: 0 for label in quality_labels},
    }
    stats["quality"]["unknown"] = 0

    for vid in files:
        # Orientation (always binary)
        vid["orientation"] = "horizontal" if vid["width"] >= vid["height"] else "vertical"

        # Duration category
        vid["duration_cat"] = categorize_by_thresholds(
            vid["duration"], duration_thresholds, duration_labels
        )

        # Quality category
        if vid["quality_ratio"] > 0:
            vid["quality_cat"] = categorize_by_thresholds(
                vid["quality_ratio"], quality_thresholds, quality_labels
            )
        else:
            vid["quality_cat"] = "unknown"

        # Update stats
        stats["orientation"][vid["orientation"]] += 1
        stats["duration"][vid["duration_cat"]] += 1
        stats["quality"][vid["quality_cat"]] += 1

    return {
        "files": files,
        "stats": stats,
        "errors": analysis["errors"],
        "total": analysis["total"],
        "thresholds": {
            "duration": {
                "method": duration_method,
                "values": duration_thresholds,
                "info": duration_info,
                "labels": duration_labels,
            },
            "quality": {
                "method": quality_method,
                "values": quality_thresholds,
                "info": quality_info,
                "labels": quality_labels,
            },
        },
    }


def sort_by_orientation(
    directory: str,
    config: Optional[dict] = None,
    dry_run: bool = False,
    on_progress: Optional[Callable[[int, int, str, str], None]] = None,
) -> Dict:
    """
    Sort videos by orientation into horizontal/ and vertical/ subdirectories.
    """
    if config is None:
        config = DEFAULT_CONFIG.copy()

    preview = preview_videos(directory, config)
    files = preview["files"]

    if not files:
        return {"moved": 0, "errors": 0, "stats": {}}

    moved = 0
    stats = {"horizontal": 0, "vertical": 0}

    for i, vid in enumerate(files):
        orientation = vid["orientation"]
        dest_dir = os.path.join(directory, orientation)
        dest_path = os.path.join(dest_dir, vid["filename"])

        if on_progress:
            on_progress(i + 1, len(files), vid["filename"], orientation)

        if not dry_run:
            os.makedirs(dest_dir, exist_ok=True)
            shutil.move(vid["filepath"], dest_path)

        stats[orientation] += 1
        moved += 1

    return {"moved": moved, "errors": len(preview["errors"]), "stats": stats}


def sort_by_duration(
    directory: str,
    config: Optional[dict] = None,
    dry_run: bool = False,
    on_progress: Optional[Callable[[int, int, str, str], None]] = None,
) -> Dict:
    """
    Sort videos by duration into short/, medium/, long/ subdirectories.
    """
    if config is None:
        config = DEFAULT_CONFIG.copy()

    preview = preview_videos(directory, config)
    files = preview["files"]

    if not files:
        return {"moved": 0, "errors": 0, "stats": {}}

    moved = 0
    stats = {"short": 0, "medium": 0, "long": 0}

    for i, vid in enumerate(files):
        duration_cat = vid["duration_cat"]
        dest_dir = os.path.join(directory, duration_cat)
        dest_path = os.path.join(dest_dir, vid["filename"])

        if on_progress:
            on_progress(i + 1, len(files), vid["filename"], duration_cat)

        if not dry_run:
            os.makedirs(dest_dir, exist_ok=True)
            shutil.move(vid["filepath"], dest_path)

        stats[duration_cat] += 1
        moved += 1

    return {"moved": moved, "errors": len(preview["errors"]), "stats": stats}


def sort_by_quality(
    directory: str,
    config: Optional[dict] = None,
    dry_run: bool = False,
    on_progress: Optional[Callable[[int, int, str, str], None]] = None,
) -> Dict:
    """
    Sort videos by quality into high/, medium/, low/ subdirectories.
    """
    if config is None:
        config = DEFAULT_CONFIG.copy()

    preview = preview_videos(directory, config)
    files = preview["files"]

    if not files:
        return {"moved": 0, "errors": 0, "stats": {}}

    moved = 0
    stats = {"high": 0, "medium": 0, "low": 0, "unknown": 0}

    for i, vid in enumerate(files):
        quality_cat = vid["quality_cat"]
        dest_dir = os.path.join(directory, quality_cat)
        dest_path = os.path.join(dest_dir, vid["filename"])

        if on_progress:
            on_progress(i + 1, len(files), vid["filename"], quality_cat)

        if not dry_run:
            os.makedirs(dest_dir, exist_ok=True)
            shutil.move(vid["filepath"], dest_path)

        stats[quality_cat] += 1
        moved += 1

    return {"moved": moved, "errors": len(preview["errors"]), "stats": stats}


def sort_by_bitrate(
    directory: str,
    config: Optional[dict] = None,
    dry_run: bool = False,
    on_progress: Optional[Callable[[int, int, str, str], None]] = None,
) -> Dict:
    """
    Sort videos by bitrate into low/ and normal/ subdirectories.

    Simple threshold-based sorting:
    - < threshold Kbps = low (bad quality, maybe exclude from concat)
    - >= threshold Kbps = normal (good enough for concat)
    """
    if config is None:
        config = DEFAULT_CONFIG.copy()

    preview = preview_videos(directory, config)
    files = preview["files"]

    if not files:
        return {"moved": 0, "errors": 0, "stats": {}, "threshold": 0}

    threshold = config.get("bitrate_threshold", 300) * 1000  # Convert to bps

    moved = 0
    stats = {"low": 0, "normal": 0}

    for i, vid in enumerate(files):
        bitrate = vid.get("bitrate", 0)
        if bitrate > 0 and bitrate < threshold:
            category = f"low_under_{config.get('bitrate_threshold', 300)}kbps"
        else:
            category = f"normal_over_{config.get('bitrate_threshold', 300)}kbps"

        dest_dir = os.path.join(directory, category)
        dest_path = os.path.join(dest_dir, vid["filename"])

        if on_progress:
            on_progress(i + 1, len(files), vid["filename"], category)

        if not dry_run:
            os.makedirs(dest_dir, exist_ok=True)
            shutil.move(vid["filepath"], dest_path)

        if bitrate > 0 and bitrate < threshold:
            stats["low"] += 1
        else:
            stats["normal"] += 1
        moved += 1

    return {
        "moved": moved,
        "errors": len(preview["errors"]),
        "stats": stats,
        "threshold": config.get("bitrate_threshold", 300),
    }


def sort_by_pipeline(
    directory: str,
    config: Optional[dict] = None,
    dry_run: bool = False,
    on_progress: Optional[Callable[[int, int, str, str], None]] = None,
) -> Dict:
    """
    Sort videos by pipeline: orientation -> duration -> bitrate.

    Creates nested directory structure:
        horizontal/
            short_under_60s/
                normal_over_300kbps/
                low_under_300kbps/
            medium_60s-300s/
                ...
            long_over_300s/
                ...
        vertical/
            ...
    """
    if config is None:
        config = DEFAULT_CONFIG.copy()

    preview = preview_videos(directory, config)
    files = preview["files"]

    if not files:
        return {"moved": 0, "errors": 0, "stats": {}}

    # Get bitrate threshold
    bitrate_threshold = config.get("bitrate_threshold", 300) * 1000  # to bps
    thresh_kbps = config.get("bitrate_threshold", 300)

    moved = 0
    stats = {}

    for i, vid in enumerate(files):
        # Determine bitrate category
        bitrate = vid.get("bitrate", 0)
        if bitrate > 0 and bitrate < bitrate_threshold:
            bitrate_cat = f"low_under_{thresh_kbps}kbps"
        else:
            bitrate_cat = f"normal_over_{thresh_kbps}kbps"

        path_parts = [
            vid["orientation"],
            vid["duration_cat"],
            bitrate_cat,
        ]
        rel_path = "/".join(path_parts)

        dest_dir = os.path.join(directory, *path_parts)
        dest_path = os.path.join(dest_dir, vid["filename"])

        if on_progress:
            on_progress(i + 1, len(files), vid["filename"], rel_path)

        if not dry_run:
            os.makedirs(dest_dir, exist_ok=True)
            shutil.move(vid["filepath"], dest_path)

        stats[rel_path] = stats.get(rel_path, 0) + 1
        moved += 1

    return {"moved": moved, "errors": len(preview["errors"]), "stats": stats}


def split_into_folders(
    directory: str,
    files_per_folder: int = 100,
    config: Optional[dict] = None,
    dry_run: bool = False,
    on_progress: Optional[Callable[[int, int, str, str], None]] = None,
) -> Dict:
    """
    Split videos into numbered folders with N files per folder.
    """
    if config is None:
        config = DEFAULT_CONFIG.copy()

    extensions = config.get("video_extensions", DEFAULT_CONFIG["video_extensions"])

    # Get video files
    files = sorted([
        f for f in os.listdir(directory)
        if os.path.isfile(os.path.join(directory, f))
        and os.path.splitext(f)[1].lower() in extensions
    ])

    if not files:
        return {"moved": 0, "folders": 0, "stats": {}}

    if len(files) <= files_per_folder:
        return {"moved": 0, "folders": 0, "message": "Not enough files to split"}

    import math
    num_folders = math.ceil(len(files) / files_per_folder)

    moved = 0
    stats = {}

    for i, filename in enumerate(files):
        folder_num = (i // files_per_folder) + 1
        folder_name = str(folder_num)

        filepath = os.path.join(directory, filename)
        dest_dir = os.path.join(directory, folder_name)
        dest_path = os.path.join(dest_dir, filename)

        if on_progress:
            on_progress(i + 1, len(files), filename, f"folder {folder_num}")

        if not dry_run:
            os.makedirs(dest_dir, exist_ok=True)
            shutil.move(filepath, dest_path)

        stats[folder_name] = stats.get(folder_name, 0) + 1
        moved += 1

    return {"moved": moved, "folders": num_folders, "stats": stats}


def reset_sorting(
    directory: str,
    config: Optional[dict] = None,
    dry_run: bool = False,
    on_progress: Optional[Callable[[int, int, str, str], None]] = None,
) -> Dict:
    """
    Move all videos from subdirectories back to the main directory.

    Flattens the directory structure by moving all video files from
    any subdirectory back to the root directory.
    """
    if config is None:
        config = DEFAULT_CONFIG.copy()

    extensions = set(config.get("video_extensions", DEFAULT_CONFIG["video_extensions"]))

    # Find all video files in subdirectories
    files_to_move = []
    for root, dirs, files in os.walk(directory):
        # Skip the root directory itself
        if root == directory:
            continue

        for filename in files:
            if os.path.splitext(filename)[1].lower() in extensions:
                files_to_move.append({
                    "filename": filename,
                    "source": os.path.join(root, filename),
                    "relative": os.path.relpath(root, directory),
                })

    if not files_to_move:
        return {"moved": 0, "errors": 0}

    moved = 0
    errors = 0

    for i, file_info in enumerate(files_to_move):
        filename = file_info["filename"]
        source = file_info["source"]
        dest = os.path.join(directory, filename)

        if on_progress:
            on_progress(i + 1, len(files_to_move), filename, file_info["relative"])

        # Handle filename collision
        if os.path.exists(dest):
            base, ext = os.path.splitext(filename)
            counter = 1
            while os.path.exists(dest):
                dest = os.path.join(directory, f"{base}_{counter}{ext}")
                counter += 1

        if not dry_run:
            try:
                shutil.move(source, dest)
                moved += 1
            except Exception:
                errors += 1
        else:
            moved += 1

    # Remove empty directories
    if not dry_run:
        for root, dirs, files in os.walk(directory, topdown=False):
            if root == directory:
                continue
            try:
                if not os.listdir(root):
                    os.rmdir(root)
            except OSError:
                pass

    return {"moved": moved, "errors": errors}
