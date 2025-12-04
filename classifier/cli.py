#!/usr/bin/env python3
"""
Interactive CLI for the video classifier.

Workflow:
1. Select directory with videos
2. Analyze - detect content in videos, save results to JSON
3. Apply Rules - move files based on saved analysis
4. Reset - move all files back to source directory
"""

import json
import os
import shutil
from datetime import datetime
from pathlib import Path

from classifier import (
    ALLOWED_LABELS,
    DEFAULT_CONFIG,
    classify_video,
    load_config,
    load_rules,
    save_config,
    save_rules,
    matches_rule,
    get_matching_rule,
)
from nudenet import NudeDetector


# Analysis results filename (stored in media root directory)
ANALYSIS_FILE = "_analysis.json"
# Folder names
NEW_FOLDER = "_unsorted"        # Where webapp downloads new files
CLASSIFIED_FOLDER = "_classified"  # Where classifier moves files


def get_analysis_path():
    """Get path to analysis file in media directory."""
    media_dir = find_media_directory()
    if media_dir:
        return media_dir / ANALYSIS_FILE
    return Path.cwd() / ANALYSIS_FILE


def clear_screen():
    """Clear terminal screen."""
    os.system("cls" if os.name == "nt" else "clear")


def print_header():
    """Print app header."""
    print("=" * 60)
    print("  VIDEO CLASSIFIER - NudeNet AI Content Detection")
    print("=" * 60)
    print()


def print_menu(title, options):
    """Print a menu and get user choice."""
    print(f"\n{title}")
    print("-" * 40)
    for key, label in options.items():
        print(f"  [{key}] {label}")
    print()
    return input("Select option: ").strip().lower()


def find_media_directory():
    """Try to find the media directory automatically."""
    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent

    candidates = [
        project_root / "media",
        Path.cwd() / "media",
        Path.home() / "media",
    ]

    for path in candidates:
        if path.exists() and path.is_dir():
            return path

    return None


def browse_directory(start_path=None, video_extensions=None):
    """Simple directory browser."""
    if video_extensions is None:
        video_extensions = DEFAULT_CONFIG["video_extensions"]

    if start_path is None:
        media_dir = find_media_directory()
        start_path = media_dir if media_dir else os.getcwd()

    current = Path(start_path).resolve()

    while True:
        clear_screen()
        print_header()
        print(f"Current: {current}\n")

        try:
            dirs = sorted(
                [d for d in current.iterdir() if d.is_dir() and not d.name.startswith(".")]
            )
        except PermissionError:
            print("Permission denied!")
            input("\nPress Enter to go back...")
            current = current.parent
            continue

        print("Directories:")
        print("  [..] Parent directory")
        for i, d in enumerate(dirs[:20], 1):
            print(f"  [{i:2}] {d.name}/")

        if len(dirs) > 20:
            print(f"  ... and {len(dirs) - 20} more")

        videos = [
            f for f in current.iterdir()
            if f.is_file() and f.suffix.lower() in video_extensions
        ]
        print(f"\nVideo files in this directory: {len(videos)}")

        # Check for existing analysis
        analysis_path = current / ANALYSIS_FILE
        if analysis_path.exists():
            print(f"  Analysis file found: {ANALYSIS_FILE}")

        print("\n  [s] SELECT this directory")
        print("  [p] Enter PATH manually")
        print("  [q] Cancel")

        choice = input("\nChoice: ").strip().lower()

        if choice == "q":
            return None
        elif choice == "s":
            return str(current)
        elif choice == "p":
            path = input("Enter path: ").strip()
            if path and os.path.isdir(path):
                return path
            else:
                print("Invalid path!")
                input("Press Enter...")
        elif choice == "..":
            current = current.parent
        elif choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(dirs):
                current = dirs[idx]


def get_video_files(directory, extensions):
    """Get list of video files in directory."""
    return sorted([
        f for f in os.listdir(directory)
        if os.path.isfile(os.path.join(directory, f))
        and os.path.splitext(f)[1].lower() in extensions
    ])


def load_analysis():
    """Load analysis results from media directory."""
    path = get_analysis_path()
    if path.exists():
        with open(path, "r") as f:
            return json.load(f)
    return None


def save_analysis(analysis):
    """Save analysis results to media directory."""
    path = get_analysis_path()
    with open(path, "w") as f:
        json.dump(analysis, f, indent=2)


def run_analyze(input_dir, config):
    """Analyze videos and save results. Appends to existing analysis, skips already analyzed files."""
    extensions = config.get("video_extensions", DEFAULT_CONFIG["video_extensions"])
    num_frames = config.get("num_frames", DEFAULT_CONFIG["num_frames"])
    model_path = config.get("model_path", "")
    model_resolution = config.get("model_resolution", 320)

    # Convert relative model path to absolute (relative to project root)
    if model_path and not os.path.isabs(model_path):
        script_dir = Path(__file__).resolve().parent
        project_root = script_dir.parent
        model_path = str(project_root / model_path)

    files = get_video_files(input_dir, extensions)

    if not files:
        print("No video files found!")
        return None

    # Load existing analysis to append to it
    existing_analysis = load_analysis()
    already_analyzed = set()
    if existing_analysis:
        for video in existing_analysis.get("videos", []):
            already_analyzed.add(video["filename"])

    # Filter to only new files
    new_files = [f for f in files if f not in already_analyzed]

    if not new_files:
        print(f"All {len(files)} videos already analyzed. Nothing new to process.")
        return existing_analysis

    print(f"Found {len(new_files)} new videos to analyze ({len(already_analyzed)} already done)")
    print(f"Config: num_frames={num_frames}")
    if model_path:
        print(f"Model: {model_path} ({model_resolution}px)")
    else:
        print(f"Model: default 320n ({model_resolution}px)")
    print("-" * 60)

    print("\nLoading NudeNet detector (this may take a moment)...")
    if model_path:
        detector = NudeDetector(model_path=model_path, inference_resolution=model_resolution)
    else:
        detector = NudeDetector(inference_resolution=model_resolution)
    print("Ready!\n")

    # Start with existing analysis or create new
    if existing_analysis:
        analysis = existing_analysis
        analysis["metadata"]["analyzed_at"] = datetime.now().isoformat()
        analysis["metadata"]["total_files"] = len(files)
    else:
        analysis = {
            "metadata": {
                "input_dir": input_dir,
                "analyzed_at": datetime.now().isoformat(),
                "config": config,
                "total_files": len(files),
            },
            "videos": []
        }

    for i, filename in enumerate(new_files, 1):
        print(f"[{i}/{len(new_files)}] {filename}")
        video_path = os.path.join(input_dir, filename)

        try:
            result = classify_video(
                video_path,
                detector,
                num_frames=num_frames,
                include_all_labels=True,
            )

            classifications = result["classifications"]
            video_metadata = result["metadata"]

            if classifications:
                labels_str = ", ".join([f"{k}: {v:.1f}%" for k, v in sorted(classifications.items())])
                print(f"  -> {labels_str}")
            else:
                print(f"  -> (nothing detected)")

            analysis["videos"].append({
                "filename": filename,
                "classifications": classifications,
                "video_metadata": video_metadata,
                "error": None,
            })

        except Exception as e:
            print(f"  -> ERROR: {e}")
            analysis["videos"].append({
                "filename": filename,
                "classifications": {},
                "video_metadata": {},
                "error": str(e),
            })

    # Save analysis
    save_analysis(analysis)
    print(f"\nAnalysis saved to: {get_analysis_path()}")

    return analysis


def run_apply_rules(input_dir, output_dir, rules, dry_run=False):
    """Apply rules to analyzed videos and move files."""
    analysis = load_analysis()

    if not analysis:
        print("No analysis found! Run Analyze first.")
        return None

    videos = analysis.get("videos", [])
    print(f"Applying {len(rules)} rules to {len(videos)} videos")
    print(f"Looking for files in: {input_dir}")
    if dry_run:
        print("DRY RUN - no files will be moved")
    print("-" * 60)

    stats = {"processed": 0, "errors": 0, "skipped": 0, "by_category": {}}

    for video in videos:
        filename = video["filename"]
        classifications = video["classifications"]
        file_path = os.path.join(input_dir, filename)

        # Skip if file doesn't exist (already moved or deleted)
        if not os.path.exists(file_path):
            stats["skipped"] += 1
            continue

        if video.get("error"):
            stats["errors"] += 1
            continue

        # Find matching rule
        matched_rule = get_matching_rule(classifications, rules)
        category = matched_rule["dir_name"] if matched_rule else "unclassified"

        # Show result
        if classifications:
            labels_str = ", ".join([f"{k}: {v:.0f}%" for k, v in classifications.items()])
            print(f"{filename}")
            print(f"  Detected: {labels_str}")
        else:
            print(f"{filename}")
            print(f"  Detected: (nothing)")

        # Move file
        category_dir = os.path.join(output_dir, category)
        dest_path = os.path.join(category_dir, filename)

        if dry_run:
            print(f"  -> Would move to: {category}/")
        else:
            os.makedirs(category_dir, exist_ok=True)
            shutil.move(file_path, dest_path)
            print(f"  -> Moved to: {category}/")

        stats["by_category"][category] = stats["by_category"].get(category, 0) + 1
        stats["processed"] += 1
        print()

    # Print summary
    print("-" * 60)
    print(f"Processed: {stats['processed']}, Skipped: {stats['skipped']}, Errors: {stats['errors']}")
    if stats["skipped"] > 0:
        print(f"(Skipped files were not found in {input_dir})")

    return stats


def run_reset(channel_dir):
    """Move all video files from _classified back to _unsorted folder."""
    extensions = set(DEFAULT_CONFIG["video_extensions"])

    moved = 0
    errors = 0

    classified_dir = os.path.join(channel_dir, CLASSIFIED_FOLDER)
    unsorted_dir = os.path.join(channel_dir, NEW_FOLDER)

    if not os.path.exists(classified_dir):
        print(f"No classified directory found: {classified_dir}")
        return {"moved": 0, "errors": 0}

    # Ensure _unsorted exists
    os.makedirs(unsorted_dir, exist_ok=True)

    print(f"Resetting: moving files from {CLASSIFIED_FOLDER}/ back to {NEW_FOLDER}/")
    print("-" * 60)

    # Scan _classified directory for category subdirs
    for subdir in os.listdir(classified_dir):
        subdir_path = os.path.join(classified_dir, subdir)

        if not os.path.isdir(subdir_path):
            continue
        if subdir.startswith('.'):
            continue

        # Move videos back
        for filename in os.listdir(subdir_path):
            file_path = os.path.join(subdir_path, filename)

            if not os.path.isfile(file_path):
                continue
            ext = os.path.splitext(filename)[1].lower()
            if ext not in extensions:
                continue

            dest_path = os.path.join(unsorted_dir, filename)

            # Handle collision
            if os.path.exists(dest_path):
                base, ext = os.path.splitext(filename)
                counter = 1
                while os.path.exists(dest_path):
                    dest_path = os.path.join(unsorted_dir, f"{base}_{counter}{ext}")
                    counter += 1

            try:
                shutil.move(file_path, dest_path)
                print(f"  {subdir}/{filename} -> {NEW_FOLDER}/{os.path.basename(dest_path)}")
                moved += 1
            except Exception as e:
                print(f"  ERROR: {filename}: {e}")
                errors += 1

        # Remove empty subdir
        try:
            if not os.listdir(subdir_path):
                os.rmdir(subdir_path)
                print(f"  Removed empty: {subdir}/")
        except OSError:
            pass

    # Remove empty _classified directory
    try:
        if os.path.exists(classified_dir) and not os.listdir(classified_dir):
            os.rmdir(classified_dir)
            print(f"  Removed empty: {CLASSIFIED_FOLDER}/")
    except OSError:
        pass

    print("-" * 60)
    print(f"Moved: {moved} files to {NEW_FOLDER}/")
    if errors:
        print(f"Errors: {errors}")

    return {"moved": moved, "errors": errors}


def show_settings_menu(config):
    """Show and edit settings."""
    while True:
        clear_screen()
        print_header()
        print("SETTINGS")
        print("-" * 40)
        print(f"  [1] Frames per video:    {config['num_frames']}")
        print(f"  [2] Video extensions:    {', '.join(config['video_extensions'])}")
        print()
        print("  [b] Back to main menu")

        choice = input("\nSelect option: ").strip().lower()

        if choice == "b":
            break
        elif choice == "1":
            try:
                val = int(input("Enter number of frames: ").strip())
                if val > 0:
                    config["num_frames"] = val
            except ValueError:
                pass
        elif choice == "2":
            exts = input("Enter extensions (comma-separated): ").strip()
            if exts:
                config["video_extensions"] = [e.strip() for e in exts.split(",")]

    return config


def show_rules_menu(rules):
    """Show and edit rules."""
    while True:
        clear_screen()
        print_header()
        print("CLASSIFICATION RULES (order = priority)")
        print("-" * 40)

        for i, rule in enumerate(rules, 1):
            print(f"  [{i}] {rule['dir_name']}")
            print(f"      {rule.get('description', '')}")
            if "thresholds" in rule:
                t = ", ".join([f"{k}: {v}%" for k, v in rule["thresholds"].items()])
                print(f"      AND: {t}")
            if "thresholds_any" in rule:
                t = ", ".join([f"{k}: {v}%" for k, v in rule["thresholds_any"].items()])
                print(f"      OR:  {t}")
            if "exclude" in rule:
                t = ", ".join([f"{k}: {v}%" for k, v in rule["exclude"].items()])
                print(f"      NOT: {t}")
            print()

        print("  [l] Load from file")
        print("  [b] Back to main menu")

        choice = input("\nSelect option: ").strip().lower()

        if choice == "b":
            break
        elif choice == "l":
            path = input("Enter rules file path: ").strip()
            if path and os.path.exists(path):
                loaded = load_rules(path)
                rules.clear()
                rules.extend(loaded)
                print(f"Loaded {len(rules)} rules")
            else:
                print("File not found")
            input("Press Enter...")

    return rules


def main():
    """Main interactive loop."""
    script_dir = Path(__file__).resolve().parent
    configs_dir = script_dir.parent / "configs"

    # Load config from YAML file
    config_path = configs_dir / "classifier_config.yaml"
    config = load_config(str(config_path))

    # Load rules from configs directory (required)
    rules_path = configs_dir / "classifier_rules.yaml"
    try:
        rules = load_rules(str(rules_path))
    except FileNotFoundError:
        print(f"ERROR: Rules file not found: {rules_path}")
        print("Please create the rules file before running the classifier.")
        return

    channel_dir = None  # Channel folder (contains _unsorted and _classified)
    analysis = None

    while True:
        clear_screen()
        print_header()

        # Show current state
        print("Current Configuration:")
        print(f"  Channel folder: {channel_dir or '(not set)'}")
        print(f"  Rules: {len(rules)} configured")

        if channel_dir:
            video_exts = config["video_extensions"]
            unsorted_dir = os.path.join(channel_dir, NEW_FOLDER)
            classified_dir = os.path.join(channel_dir, CLASSIFIED_FOLDER)

            # Count videos in _unsorted
            try:
                if os.path.exists(unsorted_dir):
                    videos = get_video_files(unsorted_dir, video_exts)
                    print(f"  {NEW_FOLDER}/: {len(videos)} videos")
                else:
                    print(f"  {NEW_FOLDER}/: (not found)")
            except Exception:
                pass

            # Count videos in _classified
            try:
                if os.path.exists(classified_dir):
                    classified_count = 0
                    for subdir in os.listdir(classified_dir):
                        subdir_path = os.path.join(classified_dir, subdir)
                        if os.path.isdir(subdir_path):
                            classified_count += len(get_video_files(subdir_path, video_exts))
                    print(f"  {CLASSIFIED_FOLDER}/: {classified_count} videos")
            except Exception:
                pass

        # Check for existing analysis (stored in media dir)
        analysis = load_analysis()
        if analysis:
            analyzed_at = analysis.get("metadata", {}).get("analyzed_at", "unknown")
            analyzed_dir = analysis.get("metadata", {}).get("input_dir", "unknown")
            print(f"  Analysis: {len(analysis.get('videos', []))} videos ({analyzed_at[:10]})")
        else:
            print(f"  Analysis: not found (run Analyze first)")

        print()

        options = {
            "1": "Select channel folder",
            "2": f"Analyze videos (from {NEW_FOLDER}/)",
            "3": f"Apply rules (move to {CLASSIFIED_FOLDER}/)",
            "4": f"Reset (move back to {NEW_FOLDER}/)",
            "5": "Settings",
            "6": "Rules",
            "q": "Quit",
        }

        choice = print_menu("MAIN MENU", options)

        if choice == "q":
            print("\nGoodbye!")
            break

        elif choice == "1":
            result = browse_directory(channel_dir, config["video_extensions"])
            if result:
                # If user selected _unsorted or _classified folder, use parent as channel
                if os.path.basename(result) in (NEW_FOLDER, CLASSIFIED_FOLDER):
                    channel_dir = os.path.dirname(result)
                    print(f"(Using parent folder as channel: {channel_dir})")
                else:
                    channel_dir = result
                analysis = load_analysis()

        elif choice == "2":
            if not channel_dir:
                print("\nPlease select a channel folder first!")
                input("Press Enter...")
                continue

            unsorted_dir = os.path.join(channel_dir, NEW_FOLDER)
            if not os.path.exists(unsorted_dir):
                print(f"\n{NEW_FOLDER}/ folder not found in {channel_dir}")
                print("Make sure you selected the correct channel folder.")
                input("Press Enter...")
                continue

            confirm = input("Start analysis? (y/n): ").strip().lower()
            if confirm == "y":
                analysis = run_analyze(unsorted_dir, config)
                input("\nPress Enter to continue...")

        elif choice == "3":
            if not channel_dir:
                print("\nPlease select a channel folder first!")
                input("Press Enter...")
                continue

            if not analysis:
                print("\nNo analysis found! Run Analyze first.")
                input("Press Enter...")
                continue

            unsorted_dir = os.path.join(channel_dir, NEW_FOLDER)
            classified_dir = os.path.join(channel_dir, CLASSIFIED_FOLDER)

            # Reload rules from file each time
            try:
                rules = load_rules(str(rules_path))
                print(f"Loaded {len(rules)} rules from {rules_path.name}")
            except FileNotFoundError:
                print(f"ERROR: Rules file not found: {rules_path}")
                input("Press Enter...")
                continue

            print(f"\nFrom: {unsorted_dir}")
            print(f"To:   {classified_dir}")
            dry = input("Dry run? (y/n/cancel): ").strip().lower()

            if dry == "y":
                run_apply_rules(unsorted_dir, classified_dir, rules, dry_run=True)
                input("\nPress Enter to continue...")
            elif dry == "n":
                run_apply_rules(unsorted_dir, classified_dir, rules, dry_run=False)
                input("\nPress Enter to continue...")

        elif choice == "4":
            if not channel_dir:
                print("\nPlease select a channel folder first!")
                input("Press Enter...")
                continue

            classified_dir = os.path.join(channel_dir, CLASSIFIED_FOLDER)
            if not os.path.exists(classified_dir):
                print(f"\n{CLASSIFIED_FOLDER}/ folder not found. Nothing to reset.")
                input("Press Enter...")
                continue

            confirm = input(f"Move all files back to {NEW_FOLDER}/? (y/n): ").strip().lower()
            if confirm == "y":
                run_reset(channel_dir)
                input("\nPress Enter to continue...")

        elif choice == "5":
            config = show_settings_menu(config)

        elif choice == "6":
            rules = show_rules_menu(rules)


if __name__ == "__main__":
    main()
