#!/usr/bin/env python3
"""
Analyze videos and save detection results to JSON.

This script only performs video analysis without classification.
Results are saved to a JSON file for later rule testing.

Usage:
    python analyze.py /path/to/videos
    python analyze.py /path/to/videos -o results.json
"""

import argparse
import json
import os
import sys
from datetime import datetime

from classifier import (
    classify_video,
    load_config,
    DEFAULT_CONFIG,
)
from nudenet import NudeDetector


def get_video_files(directory: str, extensions: list) -> list:
    """Get list of video files in directory."""
    files = []
    for f in os.listdir(directory):
        if os.path.splitext(f)[1].lower() in extensions:
            files.append(f)
    return sorted(files)


def analyze_videos(input_dir: str, config: dict, output_file: str):
    """Analyze all videos and save results to JSON."""
    extensions = config.get("video_extensions", DEFAULT_CONFIG["video_extensions"])
    threshold = config.get("threshold", DEFAULT_CONFIG["threshold"])
    num_frames = config.get("num_frames", DEFAULT_CONFIG["num_frames"])

    files = get_video_files(input_dir, extensions)

    if not files:
        print(f"No video files found in {input_dir}")
        return

    print(f"Found {len(files)} videos to analyze")
    print(f"Config: threshold={threshold}, num_frames={num_frames}")
    print(f"Output: {output_file}")
    print("-" * 60)

    # Initialize detector
    print("\nLoading NudeNet detector...")
    detector = NudeDetector()
    print("Ready!\n")

    results = {
        "metadata": {
            "input_dir": input_dir,
            "analyzed_at": datetime.now().isoformat(),
            "config": config,
            "total_files": len(files),
        },
        "videos": []
    }

    for i, filename in enumerate(files, 1):
        print(f"[{i}/{len(files)}] {filename}")
        video_path = os.path.join(input_dir, filename)

        try:
            classifications = classify_video(
                video_path,
                detector,
                threshold=threshold,
                num_frames=num_frames,
            )

            # Show results
            if classifications:
                labels_str = ", ".join([f"{k}: {v:.1f}%" for k, v in sorted(classifications.items())])
                print(f"  -> {labels_str}")
            else:
                print(f"  -> (nothing detected)")

            results["videos"].append({
                "filename": filename,
                "path": video_path,
                "classifications": classifications,
                "error": None,
            })

        except Exception as e:
            print(f"  -> ERROR: {e}")
            results["videos"].append({
                "filename": filename,
                "path": video_path,
                "classifications": {},
                "error": str(e),
            })

    # Save results
    with open(output_file, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\n{'=' * 60}")
    print(f"Analysis complete!")
    print(f"Results saved to: {output_file}")
    print(f"Total: {len(files)} videos analyzed")

    # Summary
    detected_count = sum(1 for v in results["videos"] if v["classifications"])
    error_count = sum(1 for v in results["videos"] if v["error"])
    print(f"With detections: {detected_count}")
    print(f"Errors: {error_count}")


def main():
    parser = argparse.ArgumentParser(
        description="Analyze videos and save detection results to JSON"
    )
    parser.add_argument(
        "input_dir",
        help="Directory containing videos to analyze"
    )
    parser.add_argument(
        "-o", "--output",
        default="analysis_results.json",
        help="Output JSON file (default: analysis_results.json)"
    )
    parser.add_argument(
        "-c", "--config",
        help="Path to config file (YAML or JSON)"
    )
    parser.add_argument(
        "-t", "--threshold",
        type=float,
        help="Detection threshold (overrides config)"
    )
    parser.add_argument(
        "-n", "--num-frames",
        type=int,
        help="Number of frames to analyze (overrides config)"
    )

    args = parser.parse_args()

    if not os.path.isdir(args.input_dir):
        print(f"Error: Directory not found: {args.input_dir}")
        sys.exit(1)

    # Load config
    config = load_config(args.config) if args.config else DEFAULT_CONFIG.copy()

    # Override with command line args
    if args.threshold is not None:
        config["threshold"] = args.threshold
    if args.num_frames is not None:
        config["num_frames"] = args.num_frames

    analyze_videos(args.input_dir, config, args.output)


if __name__ == "__main__":
    main()
