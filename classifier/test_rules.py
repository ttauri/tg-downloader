#!/usr/bin/env python3
"""
Test classification rules against saved analysis results.

This script reads video analysis from JSON and applies rules
to see how videos would be classified. No actual file moving.

Usage:
    python test_rules.py analysis_results.json
    python test_rules.py analysis_results.json -r ../configs/classifier_rules.yaml
    python test_rules.py --reset /path/to/videos  # Move all files back to root
"""

import argparse
import json
import os
import shutil
import sys
from collections import defaultdict

from pathlib import Path

from classifier import load_rules, matches_rule, get_matching_rule


def load_analysis(path: str) -> dict:
    """Load analysis results from JSON."""
    with open(path, "r") as f:
        return json.load(f)


def test_rules(analysis: dict, rules: list, verbose: bool = True):
    """Test rules against analysis results."""
    videos = analysis.get("videos", [])

    if not videos:
        print("No videos in analysis file")
        return

    print(f"Testing {len(rules)} rules against {len(videos)} videos")
    print("=" * 70)

    # Category counts
    by_category = defaultdict(list)

    for video in videos:
        filename = video["filename"]
        classifications = video["classifications"]

        if video.get("error"):
            by_category["_error"].append(filename)
            if verbose:
                print(f"\n{filename}")
                print(f"  ERROR: {video['error']}")
            continue

        # Find matching rule
        matched_rule = get_matching_rule(classifications, rules)
        category = matched_rule["dir_name"] if matched_rule else "unclassified"

        by_category[category].append(filename)

        if verbose:
            print(f"\n{filename}")
            if classifications:
                labels = ", ".join([f"{k}: {v:.1f}%" for k, v in sorted(classifications.items())])
                print(f"  Detected: {labels}")
            else:
                print(f"  Detected: (nothing)")
            print(f"  -> {category}")

            # Show why rule matched (or didn't)
            if matched_rule:
                print(f"     Rule: {matched_rule.get('description', matched_rule['dir_name'])}")
            else:
                print(f"     No rule matched")

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY BY CATEGORY")
    print("=" * 70)

    for category in sorted(by_category.keys()):
        files = by_category[category]
        print(f"\n{category}: {len(files)} files")
        for f in files[:5]:  # Show first 5
            print(f"  - {f}")
        if len(files) > 5:
            print(f"  ... and {len(files) - 5} more")

    return by_category


def reset_sorting(directory: str, dry_run: bool = False):
    """
    Move all video files from subdirectories back to the root directory.
    This undoes the classification sorting.
    """
    if not os.path.isdir(directory):
        print(f"Error: Directory not found: {directory}")
        return

    video_extensions = {".mp4", ".avi", ".mov", ".mkv", ".webm"}
    moved = 0
    skipped = 0
    errors = 0

    print(f"Resetting sorting in: {directory}")
    if dry_run:
        print("DRY RUN - no files will be moved")
    print("-" * 60)

    # Find all subdirectories
    for subdir in os.listdir(directory):
        subdir_path = os.path.join(directory, subdir)

        # Skip if not a directory or if it's a special folder
        if not os.path.isdir(subdir_path):
            continue
        if subdir.startswith('.'):
            continue

        # Find video files in subdirectory
        for filename in os.listdir(subdir_path):
            file_path = os.path.join(subdir_path, filename)

            # Skip non-files and non-videos
            if not os.path.isfile(file_path):
                continue
            ext = os.path.splitext(filename)[1].lower()
            if ext not in video_extensions:
                continue

            dest_path = os.path.join(directory, filename)

            # Handle name collision
            if os.path.exists(dest_path):
                base, ext = os.path.splitext(filename)
                counter = 1
                while os.path.exists(dest_path):
                    dest_path = os.path.join(directory, f"{base}_{counter}{ext}")
                    counter += 1

            try:
                if dry_run:
                    print(f"  Would move: {subdir}/{filename} -> {os.path.basename(dest_path)}")
                else:
                    shutil.move(file_path, dest_path)
                    print(f"  Moved: {subdir}/{filename} -> {os.path.basename(dest_path)}")
                moved += 1
            except Exception as e:
                print(f"  Error moving {filename}: {e}")
                errors += 1

    # Remove empty subdirectories
    if not dry_run:
        for subdir in os.listdir(directory):
            subdir_path = os.path.join(directory, subdir)
            if os.path.isdir(subdir_path) and not subdir.startswith('.'):
                try:
                    # Only remove if empty
                    if not os.listdir(subdir_path):
                        os.rmdir(subdir_path)
                        print(f"  Removed empty dir: {subdir}/")
                except OSError:
                    pass  # Directory not empty

    print("-" * 60)
    print(f"{'Would move' if dry_run else 'Moved'}: {moved} files")
    if skipped:
        print(f"Skipped: {skipped}")
    if errors:
        print(f"Errors: {errors}")


def test_single_video(analysis: dict, rules: list, filename: str):
    """Test rules against a single video with detailed output."""
    video = None
    for v in analysis.get("videos", []):
        if v["filename"] == filename or filename in v["filename"]:
            video = v
            break

    if not video:
        print(f"Video not found: {filename}")
        print("Available videos:")
        for v in analysis.get("videos", [])[:10]:
            print(f"  - {v['filename']}")
        return

    print(f"Video: {video['filename']}")
    print("-" * 60)

    # Show video metadata if available
    video_metadata = video.get("video_metadata", {})
    if video_metadata:
        print(f"Duration: {video_metadata.get('duration', '?')}s, "
              f"Frames analyzed: {video_metadata.get('analyzed_frames', '?')}, "
              f"Threshold: {video_metadata.get('threshold', '?')}")
        print("-" * 60)

    classifications = video["classifications"]

    if not classifications:
        print("No detections")
        return

    print("Detections:")
    for label, pct in sorted(classifications.items(), key=lambda x: -x[1]):
        print(f"  {label}: {pct:.1f}%")

    print("\nRule evaluation:")
    print("-" * 60)

    for i, rule in enumerate(rules, 1):
        result = matches_rule(classifications, rule)
        status = "MATCH" if result else "no match"
        print(f"\n[{i}] {rule['dir_name']} -> {status}")
        print(f"    {rule.get('description', '')}")

        # Show threshold checks
        if "thresholds" in rule:
            print(f"    thresholds (AND):")
            for label, min_pct in rule["thresholds"].items():
                actual = classifications.get(label, 0)
                check = "OK" if actual >= min_pct else "FAIL"
                print(f"      {label}: need >={min_pct}%, got {actual:.1f}% [{check}]")

        if "thresholds_any" in rule:
            print(f"    thresholds_any (OR):")
            any_matched = False
            for label, min_pct in rule["thresholds_any"].items():
                actual = classifications.get(label, 0)
                check = "OK" if actual >= min_pct else "FAIL"
                if actual >= min_pct:
                    any_matched = True
                print(f"      {label}: need >={min_pct}%, got {actual:.1f}% [{check}]")
            if not any_matched:
                print(f"      -> None matched (need at least one)")

        if "exclude" in rule:
            print(f"    exclude:")
            for label, max_pct in rule["exclude"].items():
                actual = classifications.get(label, 0)
                check = "OK" if actual <= max_pct else "BLOCKED"
                print(f"      {label}: need <={max_pct}%, got {actual:.1f}% [{check}]")

        if result:
            print(f"\n*** FIRST MATCH: {rule['dir_name']} ***")
            break


def main():
    parser = argparse.ArgumentParser(
        description="Test classification rules against saved analysis"
    )
    parser.add_argument(
        "analysis_file",
        nargs="?",
        help="JSON file with analysis results (from analyze.py)"
    )
    parser.add_argument(
        "-r", "--rules",
        help="Path to rules file (YAML or JSON)"
    )
    parser.add_argument(
        "-v", "--video",
        help="Test single video (partial filename match)"
    )
    parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="Only show summary"
    )
    parser.add_argument(
        "--reset",
        metavar="DIR",
        help="Reset sorting: move all videos from subdirs back to root"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without moving files (for --reset)"
    )

    args = parser.parse_args()

    # Handle reset mode
    if args.reset:
        reset_sorting(args.reset, dry_run=args.dry_run)
        return

    # Normal mode requires analysis file
    if not args.analysis_file:
        parser.print_help()
        print("\nError: analysis_file is required (unless using --reset)")
        sys.exit(1)

    if not os.path.exists(args.analysis_file):
        print(f"Error: File not found: {args.analysis_file}")
        sys.exit(1)

    # Load analysis
    analysis = load_analysis(args.analysis_file)
    print(f"Loaded analysis from: {args.analysis_file}")
    print(f"Analyzed at: {analysis.get('metadata', {}).get('analyzed_at', 'unknown')}")

    # Load rules
    if args.rules:
        rules_path = args.rules
    else:
        # Default to configs/classifier_rules.yaml
        script_dir = Path(__file__).resolve().parent
        rules_path = str(script_dir.parent / "configs" / "classifier_rules.yaml")

    try:
        rules = load_rules(rules_path)
        print(f"Using rules from: {rules_path}")
    except FileNotFoundError:
        print(f"Error: Rules file not found: {rules_path}")
        sys.exit(1)

    print()

    if args.video:
        test_single_video(analysis, rules, args.video)
    else:
        test_rules(analysis, rules, verbose=not args.quiet)


if __name__ == "__main__":
    main()
