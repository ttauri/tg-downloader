"""
Timestamp generator - creates unsafe time ranges from analyzed video data.

Reads per-second detection data from JSON and applies configurable
criteria to determine which sections are "unsafe".
"""

from typing import Dict, List, Optional, Tuple


def format_timestamp(seconds: int) -> str:
    """Convert seconds to MM:SS or HH:MM:SS format."""
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def format_seconds_decimal(seconds: int) -> str:
    """Convert seconds to decimal format for ffmpeg (e.g., 65.0)."""
    return f"{seconds}.0"


def is_second_unsafe(
    detections: Dict[str, float],
    unsafe_labels: List[str],
    unsafe_threshold: float,
) -> bool:
    """
    Check if a second's detections match unsafe criteria.

    Args:
        detections: Dict of label -> confidence for this second
        unsafe_labels: Labels considered unsafe
        unsafe_threshold: Minimum confidence to count as detected

    Returns:
        True if any unsafe label detected above threshold
    """
    for label in unsafe_labels:
        if label in detections and detections[label] >= unsafe_threshold:
            return True
    return False


def merge_ranges(
    ranges: List[Tuple[int, int]],
    merge_gap: int,
) -> List[Tuple[int, int]]:
    """
    Merge time ranges that are close together.

    Args:
        ranges: List of (start, end) tuples in seconds
        merge_gap: Merge ranges if gap between them is <= this many seconds

    Returns:
        Merged list of (start, end) tuples
    """
    if not ranges:
        return []

    # Sort by start time
    sorted_ranges = sorted(ranges, key=lambda x: x[0])
    merged = [sorted_ranges[0]]

    for start, end in sorted_ranges[1:]:
        last_start, last_end = merged[-1]

        # If this range starts within merge_gap of last range's end, merge them
        if start <= last_end + merge_gap:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))

    return merged


def generate_unsafe_ranges(
    analysis: dict,
    unsafe_labels: List[str],
    unsafe_threshold: float = 0.5,
    merge_gap: int = 2,
) -> List[Tuple[int, int]]:
    """
    Generate list of unsafe time ranges from analysis data.

    Args:
        analysis: Video analysis dict with 'detections' key
        unsafe_labels: Labels to consider unsafe
        unsafe_threshold: Minimum confidence for detection
        merge_gap: Merge ranges closer than N seconds

    Returns:
        List of (start_second, end_second) tuples
    """
    detections = analysis.get("detections", {})
    total_seconds = analysis.get("total_seconds", 0)

    # Find all unsafe seconds
    unsafe_seconds: List[int] = []

    for second in range(total_seconds + 1):
        second_detections = detections.get(str(second), {})
        if is_second_unsafe(second_detections, unsafe_labels, unsafe_threshold):
            unsafe_seconds.append(second)

    if not unsafe_seconds:
        return []

    # Convert to ranges (consecutive seconds become a range)
    ranges: List[Tuple[int, int]] = []
    range_start = unsafe_seconds[0]
    range_end = unsafe_seconds[0]

    for second in unsafe_seconds[1:]:
        if second == range_end + 1:
            # Extend current range
            range_end = second
        else:
            # Start new range
            ranges.append((range_start, range_end))
            range_start = second
            range_end = second

    # Don't forget the last range
    ranges.append((range_start, range_end))

    # Merge close ranges
    if merge_gap > 0:
        ranges = merge_ranges(ranges, merge_gap)

    return ranges


def format_ranges_for_display(ranges: List[Tuple[int, int]]) -> List[str]:
    """Format ranges as human-readable strings."""
    return [
        f"{format_timestamp(start)} - {format_timestamp(end)}"
        for start, end in ranges
    ]


def format_ranges_for_ffmpeg(
    ranges: List[Tuple[int, int]],
    total_duration: float,
) -> str:
    """
    Generate ffmpeg filter_complex for cutting unsafe ranges.

    Creates a filter that keeps only the SAFE parts of the video.

    Args:
        ranges: List of unsafe (start, end) tuples
        total_duration: Total video duration in seconds

    Returns:
        ffmpeg filter_complex string
    """
    if not ranges:
        return ""

    # Calculate safe ranges (inverse of unsafe ranges)
    safe_ranges: List[Tuple[float, float]] = []
    current_pos = 0.0

    for unsafe_start, unsafe_end in ranges:
        if current_pos < unsafe_start:
            safe_ranges.append((current_pos, float(unsafe_start)))
        current_pos = float(unsafe_end + 1)

    # Add final safe range if video continues after last unsafe range
    if current_pos < total_duration:
        safe_ranges.append((current_pos, total_duration))

    if not safe_ranges:
        return "# No safe ranges - entire video is unsafe"

    # Build ffmpeg filter
    # Format: trim=start:end for each safe segment, then concat
    parts = []
    for i, (start, end) in enumerate(safe_ranges):
        parts.append(f"[0:v]trim={start}:{end},setpts=PTS-STARTPTS[v{i}];")
        parts.append(f"[0:a]atrim={start}:{end},asetpts=PTS-STARTPTS[a{i}];")

    # Concat all segments
    v_inputs = "".join(f"[v{i}]" for i in range(len(safe_ranges)))
    a_inputs = "".join(f"[a{i}]" for i in range(len(safe_ranges)))
    parts.append(f"{v_inputs}{a_inputs}concat=n={len(safe_ranges)}:v=1:a=1[outv][outa]")

    return "\n".join(parts)


def get_safe_ranges(
    ranges: List[Tuple[int, int]],
    total_duration: float,
) -> List[Tuple[float, float]]:
    """
    Calculate safe ranges (inverse of unsafe ranges).

    Args:
        ranges: List of unsafe (start, end) tuples
        total_duration: Total video duration in seconds

    Returns:
        List of safe (start, end) tuples
    """
    if not ranges:
        return [(0.0, total_duration)]

    safe_ranges: List[Tuple[float, float]] = []
    current_pos = 0.0

    for unsafe_start, unsafe_end in ranges:
        if current_pos < unsafe_start:
            safe_ranges.append((current_pos, float(unsafe_start)))
        current_pos = float(unsafe_end + 1)

    if current_pos < total_duration:
        safe_ranges.append((current_pos, total_duration))

    return safe_ranges


def generate_timestamps_report(
    analysis: dict,
    unsafe_labels: List[str],
    unsafe_threshold: float = 0.5,
    merge_gap: int = 2,
) -> dict:
    """
    Generate a complete timestamps report for a video.

    Returns dict with unsafe ranges, safe ranges, and statistics.
    """
    unsafe_ranges = generate_unsafe_ranges(
        analysis,
        unsafe_labels,
        unsafe_threshold,
        merge_gap,
    )

    total_duration = analysis.get("duration", 0)
    safe_ranges = get_safe_ranges(unsafe_ranges, total_duration)

    # Calculate statistics
    unsafe_seconds = sum(end - start + 1 for start, end in unsafe_ranges)
    safe_seconds = total_duration - unsafe_seconds

    return {
        "filename": analysis.get("filename", ""),
        "duration": total_duration,
        "unsafe_ranges": unsafe_ranges,
        "unsafe_ranges_formatted": format_ranges_for_display(unsafe_ranges),
        "safe_ranges": safe_ranges,
        "statistics": {
            "total_seconds": int(total_duration),
            "unsafe_seconds": unsafe_seconds,
            "safe_seconds": int(safe_seconds),
            "unsafe_percentage": round(unsafe_seconds / total_duration * 100, 1) if total_duration > 0 else 0,
        },
        "criteria": {
            "unsafe_labels": unsafe_labels,
            "unsafe_threshold": unsafe_threshold,
            "merge_gap": merge_gap,
        },
    }
