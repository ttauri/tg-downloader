#!/usr/bin/env python3
"""
Interactive CLI for the video safety analyzer.

Workflow:
1. Select directory with videos
2. Analyze - detect content per second, save to JSON
3. Generate Timestamps - apply criteria, get unsafe ranges
4. Rerun with different criteria without re-analyzing
"""

import json
import os
from pathlib import Path

from analyzer import (
    ALLOWED_LABELS,
    DEFAULT_CONFIG,
    analyze_video,
    get_analysis_path,
    get_data_dir,
    get_video_files,
    load_analysis,
    load_config,
    save_analysis,
    save_config,
)
from timestamps import (
    generate_timestamps_report,
    format_ranges_for_ffmpeg,
)
from nudenet import NudeDetector


def clear_screen():
    """Clear terminal screen."""
    os.system("cls" if os.name == "nt" else "clear")


def print_header():
    """Print app header."""
    print("=" * 60)
    print("  VIDEO SAFETY ANALYZER - Per-Second Content Detection")
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


def browse_directory(start_path=None, video_extensions=None):
    """Simple directory browser."""
    if video_extensions is None:
        video_extensions = DEFAULT_CONFIG["video_extensions"]

    if start_path is None:
        start_path = os.getcwd()

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


def run_analyze(input_dir: str, config: dict):
    """Analyze videos in directory."""
    extensions = config.get("video_extensions", DEFAULT_CONFIG["video_extensions"])
    threshold = config.get("threshold", DEFAULT_CONFIG["threshold"])
    model_path = config.get("model_path", "")
    model_resolution = config.get("model_resolution", 320)

    # Convert relative model path to absolute
    if model_path and not os.path.isabs(model_path):
        script_dir = Path(__file__).resolve().parent
        project_root = script_dir.parent
        model_path = str(project_root / model_path)

    files = get_video_files(input_dir, extensions)

    if not files:
        print("No video files found!")
        return

    # Check which files are already analyzed
    already_analyzed = []
    to_analyze = []
    for f in files:
        if load_analysis(f):
            already_analyzed.append(f)
        else:
            to_analyze.append(f)

    print(f"Found {len(files)} videos")
    print(f"  Already analyzed: {len(already_analyzed)}")
    print(f"  To analyze: {len(to_analyze)}")
    print(f"Config: threshold={threshold}")
    print(f"Data directory: {get_data_dir()}")
    print("-" * 60)

    if not to_analyze:
        print("All videos already analyzed. Nothing to do.")
        return

    # Ask to re-analyze already analyzed files
    if already_analyzed:
        reanalyze = input(f"\nRe-analyze {len(already_analyzed)} existing? (y/n): ").strip().lower()
        if reanalyze == "y":
            to_analyze = files

    print(f"\nLoading NudeNet detector...")
    if model_path:
        detector = NudeDetector(model_path=model_path, inference_resolution=model_resolution)
    else:
        detector = NudeDetector(inference_resolution=model_resolution)
    print("Ready!\n")

    for i, filename in enumerate(to_analyze, 1):
        video_path = os.path.join(input_dir, filename)
        print(f"[{i}/{len(to_analyze)}] {filename}")

        def progress(current, total):
            pct = int(current / total * 100)
            print(f"\r  Analyzing: {current}/{total} seconds ({pct}%)", end="", flush=True)

        try:
            analysis = analyze_video(
                video_path,
                detector,
                threshold=threshold,
                progress_callback=progress,
            )
            print()  # New line after progress

            # Show summary
            detections = analysis.get("detections", {})
            detected_seconds = len(detections)
            total_seconds = analysis.get("total_seconds", 0)

            if detected_seconds > 0:
                # Count label occurrences
                label_counts = {}
                for second_data in detections.values():
                    for label in second_data:
                        label_counts[label] = label_counts.get(label, 0) + 1

                labels_str = ", ".join([f"{k}: {v}s" for k, v in sorted(label_counts.items())])
                print(f"  Detected in {detected_seconds}/{total_seconds}s: {labels_str}")
            else:
                print(f"  No detections in {total_seconds}s")

            # Save analysis
            save_analysis(filename, analysis)
            print(f"  Saved: {get_analysis_path(filename)}")

        except Exception as e:
            print(f"\n  ERROR: {e}")

        print()

    print("-" * 60)
    print("Analysis complete!")


def run_generate_timestamps(input_dir: str, config: dict):
    """Generate timestamps for analyzed videos."""
    extensions = config.get("video_extensions", DEFAULT_CONFIG["video_extensions"])
    unsafe_labels = config.get("unsafe_labels", DEFAULT_CONFIG["unsafe_labels"])
    unsafe_threshold = config.get("unsafe_threshold", DEFAULT_CONFIG["unsafe_threshold"])
    merge_gap = config.get("merge_gap", DEFAULT_CONFIG["merge_gap"])

    files = get_video_files(input_dir, extensions)

    if not files:
        print("No video files found!")
        return

    print(f"Generating timestamps for {len(files)} videos")
    print(f"Unsafe labels: {', '.join(unsafe_labels)}")
    print(f"Threshold: {unsafe_threshold}, Merge gap: {merge_gap}s")
    print("-" * 60)

    results = []

    for filename in files:
        analysis = load_analysis(filename)

        if not analysis:
            print(f"{filename}: NOT ANALYZED (run Analyze first)")
            continue

        report = generate_timestamps_report(
            analysis,
            unsafe_labels,
            unsafe_threshold,
            merge_gap,
        )

        stats = report["statistics"]
        unsafe_ranges = report["unsafe_ranges_formatted"]

        print(f"\n{filename}")
        print(f"  Duration: {stats['total_seconds']}s")
        print(f"  Unsafe: {stats['unsafe_seconds']}s ({stats['unsafe_percentage']}%)")

        if unsafe_ranges:
            print(f"  Ranges to cut:")
            for r in unsafe_ranges:
                print(f"    {r}")
        else:
            print(f"  No unsafe content detected")

        results.append(report)

    # Save all results to a summary file
    if results:
        summary_path = get_data_dir() / "_timestamps_report.json"
        with open(summary_path, "w") as f:
            json.dump(results, f, indent=2)
        print(f"\n" + "-" * 60)
        print(f"Report saved: {summary_path}")

    return results


def run_show_detections(input_dir: str, config: dict):
    """Show detailed detections for a specific video."""
    extensions = config.get("video_extensions", DEFAULT_CONFIG["video_extensions"])
    files = get_video_files(input_dir, extensions)

    if not files:
        print("No video files found!")
        return

    # List analyzed videos
    analyzed = []
    for f in files:
        if load_analysis(f):
            analyzed.append(f)

    if not analyzed:
        print("No analyzed videos found. Run Analyze first.")
        return

    print("Analyzed videos:")
    for i, f in enumerate(analyzed, 1):
        print(f"  [{i}] {f}")

    choice = input("\nSelect video number: ").strip()
    if not choice.isdigit():
        return

    idx = int(choice) - 1
    if idx < 0 or idx >= len(analyzed):
        return

    filename = analyzed[idx]
    analysis = load_analysis(filename)

    clear_screen()
    print_header()
    print(f"Detections for: {filename}")
    print(f"Duration: {analysis.get('duration', 0)}s")
    print("-" * 60)

    detections = analysis.get("detections", {})

    if not detections:
        print("No detections found.")
        return

    # Sort by second
    for second in sorted(detections.keys(), key=int):
        data = detections[second]
        labels_str = ", ".join([f"{k}: {v:.2f}" for k, v in data.items()])
        print(f"  {int(second):4d}s: {labels_str}")


def show_settings_menu(config: dict) -> dict:
    """Show and edit settings."""
    while True:
        clear_screen()
        print_header()
        print("SETTINGS")
        print("-" * 40)
        print(f"\n  Analysis Settings:")
        print(f"  [1] Detection threshold:   {config.get('threshold', 0.4)}")
        print(f"  [2] Video extensions:      {', '.join(config.get('video_extensions', []))}")
        print(f"\n  Timestamp Generation:")
        print(f"  [3] Unsafe labels:         {', '.join(config.get('unsafe_labels', []))}")
        print(f"  [4] Unsafe threshold:      {config.get('unsafe_threshold', 0.5)}")
        print(f"  [5] Merge gap (seconds):   {config.get('merge_gap', 2)}")
        print(f"\n  Available labels:")
        for label in ALLOWED_LABELS:
            print(f"      - {label}")
        print()
        print("  [s] Save config to file")
        print("  [b] Back to main menu")

        choice = input("\nSelect option: ").strip().lower()

        if choice == "b":
            break
        elif choice == "1":
            try:
                val = float(input("Enter threshold (0.0-1.0): ").strip())
                if 0 <= val <= 1:
                    config["threshold"] = val
            except ValueError:
                pass
        elif choice == "2":
            exts = input("Enter extensions (comma-separated): ").strip()
            if exts:
                config["video_extensions"] = [e.strip() for e in exts.split(",")]
        elif choice == "3":
            print(f"\nAvailable: {', '.join(ALLOWED_LABELS)}")
            labels = input("Enter unsafe labels (comma-separated): ").strip()
            if labels:
                config["unsafe_labels"] = [l.strip() for l in labels.split(",")]
        elif choice == "4":
            try:
                val = float(input("Enter unsafe threshold (0.0-1.0): ").strip())
                if 0 <= val <= 1:
                    config["unsafe_threshold"] = val
            except ValueError:
                pass
        elif choice == "5":
            try:
                val = int(input("Enter merge gap (seconds): ").strip())
                if val >= 0:
                    config["merge_gap"] = val
            except ValueError:
                pass
        elif choice == "s":
            script_dir = Path(__file__).resolve().parent
            config_path = script_dir.parent / "configs" / "analyzer_config.yaml"
            save_config(config, str(config_path))
            print(f"Saved to: {config_path}")
            input("Press Enter...")

    return config


def main():
    """Main interactive loop."""
    script_dir = Path(__file__).resolve().parent
    configs_dir = script_dir.parent / "configs"

    # Load config
    config_path = configs_dir / "analyzer_config.yaml"
    config = load_config(str(config_path))

    input_dir = None

    while True:
        clear_screen()
        print_header()

        # Show current state
        print("Current Configuration:")
        print(f"  Directory: {input_dir or '(not set)'}")
        print(f"  Data dir:  {get_data_dir()}")

        if input_dir:
            extensions = config.get("video_extensions", DEFAULT_CONFIG["video_extensions"])
            files = get_video_files(input_dir, extensions)
            analyzed = sum(1 for f in files if load_analysis(f))
            print(f"  Videos: {len(files)} ({analyzed} analyzed)")

        print(f"\n  Unsafe criteria: {', '.join(config.get('unsafe_labels', []))}")
        print(f"  Threshold: {config.get('unsafe_threshold', 0.5)}, Merge gap: {config.get('merge_gap', 2)}s")

        options = {
            "1": "Select directory",
            "2": "Analyze videos (detect content per second)",
            "3": "Generate timestamps (apply criteria)",
            "4": "Show detections (view raw data)",
            "5": "Settings",
            "q": "Quit",
        }

        choice = print_menu("MAIN MENU", options)

        if choice == "q":
            print("\nGoodbye!")
            break

        elif choice == "1":
            result = browse_directory(input_dir, config.get("video_extensions"))
            if result:
                input_dir = result

        elif choice == "2":
            if not input_dir:
                print("\nPlease select a directory first!")
                input("Press Enter...")
                continue

            confirm = input("Start analysis? (y/n): ").strip().lower()
            if confirm == "y":
                run_analyze(input_dir, config)
                input("\nPress Enter to continue...")

        elif choice == "3":
            if not input_dir:
                print("\nPlease select a directory first!")
                input("Press Enter...")
                continue

            run_generate_timestamps(input_dir, config)
            input("\nPress Enter to continue...")

        elif choice == "4":
            if not input_dir:
                print("\nPlease select a directory first!")
                input("Press Enter...")
                continue

            run_show_detections(input_dir, config)
            input("\nPress Enter to continue...")

        elif choice == "5":
            config = show_settings_menu(config)


if __name__ == "__main__":
    main()
