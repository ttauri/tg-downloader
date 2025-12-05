#!/usr/bin/env python3
"""
Interactive CLI for the video concatenator.

Workflow:
1. Select directory with videos (channel folder or category folder)
2. Preview - see list of files, total duration, estimated output size
3. Concat - normalize and concatenate all videos
4. Settings - configure resolution, fps, quality
"""

import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from concat import (
    DEFAULT_CONFIG,
    check_media_validity,
    concatenate_videos,
    get_target_dimensions,
    get_video_info,
    load_config,
    normalize_video,
    process_videos,
    save_config,
    RESOLUTION_MAP,
)


def clear_screen():
    """Clear terminal screen."""
    os.system("cls" if os.name == "nt" else "clear")


def print_header():
    """Print app header."""
    print("=" * 60)
    print("  VIDEO CONCATENATOR - Merge Multiple Videos")
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


def format_duration(seconds: float) -> str:
    """Format duration in seconds to human-readable string."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        mins = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{mins}m {secs}s"
    else:
        hours = int(seconds // 3600)
        mins = int((seconds % 3600) // 60)
        return f"{hours}h {mins}m"


def format_size(size_bytes: int) -> str:
    """Format size in bytes to human-readable string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


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
            # Count videos in subdirectory
            try:
                video_count = len([
                    f for f in d.iterdir()
                    if f.is_file() and f.suffix.lower() in video_extensions
                ])
                count_str = f" ({video_count} videos)" if video_count > 0 else ""
            except:
                count_str = ""
            print(f"  [{i:2}] {d.name}/{count_str}")

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


def get_video_files(directory: str, extensions: List[str]) -> List[str]:
    """Get list of video files in directory."""
    return sorted([
        os.path.join(directory, f)
        for f in os.listdir(directory)
        if os.path.isfile(os.path.join(directory, f))
        and os.path.splitext(f)[1].lower() in extensions
    ])


def preview_videos(directory: str, config: dict) -> Optional[dict]:
    """
    Preview videos in directory - show stats without processing.

    Returns dict with file list and stats.
    """
    extensions = config.get("video_extensions", DEFAULT_CONFIG["video_extensions"])
    files = get_video_files(directory, extensions)

    if not files:
        print("No video files found!")
        return None

    print(f"\nFound {len(files)} video files")
    print("-" * 60)

    total_duration = 0
    total_size = 0
    valid_files = []
    resolutions = {}

    for i, filepath in enumerate(files, 1):
        filename = os.path.basename(filepath)
        file_size = os.path.getsize(filepath)
        total_size += file_size

        info = get_video_info(filepath)

        if info and info.get("duration"):
            duration = info["duration"]
            total_duration += duration
            dur_str = format_duration(duration)
            res_str = f"{info['width']}x{info['height']}"
            fps_str = f"{info['fps']}fps"

            # Track resolution distribution
            res_key = f"{info['height']}p"
            resolutions[res_key] = resolutions.get(res_key, 0) + 1

            status = "OK"
            valid_files.append(filepath)
        else:
            dur_str = "???"
            res_str = "???"
            fps_str = "???"
            status = "ERROR"

        # Show first 20 and last 5
        if i <= 20 or i > len(files) - 5:
            print(f"  {i:3}. {filename[:40]:<40} {dur_str:>8} {res_str:>10} {status}")
        elif i == 21:
            print(f"  ... ({len(files) - 25} more files) ...")

    print("-" * 60)
    print(f"Total files:    {len(files)}")
    print(f"Valid files:    {len(valid_files)}")
    print(f"Total duration: {format_duration(total_duration)}")
    print(f"Total size:     {format_size(total_size)}")

    if resolutions:
        res_summary = ", ".join([f"{k}: {v}" for k, v in sorted(resolutions.items())])
        print(f"Resolutions:    {res_summary}")

    return {
        "files": valid_files,
        "total_duration": total_duration,
        "total_size": total_size,
        "resolutions": resolutions,
    }


def run_concat(directory: str, output_file: str, config: dict):
    """Run the concatenation process."""
    extensions = config.get("video_extensions", DEFAULT_CONFIG["video_extensions"])
    files = get_video_files(directory, extensions)

    if not files:
        print("No video files found!")
        return None

    print(f"\nProcessing {len(files)} files...")
    print(f"Output: {output_file}")
    print(f"Target: {config.get('target_resolution', '1080p')} @ {config.get('target_fps', 30)}fps")
    print("-" * 60)

    def on_progress(current, total, filename, status):
        # Truncate filename for display
        name = filename[:35] + "..." if len(filename) > 38 else filename
        print(f"  [{current:3}/{total}] {name:<40} {status}")

    stats = process_videos(
        directory,
        output_file,
        config=config,
        on_progress=on_progress,
        validate=True,
    )

    print("-" * 60)
    print(f"Processed: {stats['processed']}")
    print(f"Skipped:   {stats['skipped']}")
    print(f"Errors:    {stats['errors']}")

    if stats["output_path"]:
        output_size = os.path.getsize(stats["output_path"])
        print(f"\nOutput file: {stats['output_path']}")
        print(f"Output size: {format_size(output_size)}")
    else:
        print("\nConcatenation failed!")

    return stats


def show_settings_menu(config: dict) -> dict:
    """Show and edit settings."""
    while True:
        clear_screen()
        print_header()
        print("SETTINGS")
        print("-" * 40)
        print(f"  [1] Target resolution:  {config.get('target_resolution', '1080p')}")
        print(f"  [2] Target FPS:         {config.get('target_fps', 30)}")
        print(f"  [3] Aspect ratio:       {config.get('aspect_ratio', '16:9')}")
        print(f"  [4] Quality (CRF):      {config.get('crf', 18)} (lower = better)")
        print(f"  [5] Encoding preset:    {config.get('preset', 'fast')}")
        print(f"  [6] Video extensions:   {', '.join(config.get('video_extensions', []))}")
        print()
        print("  [b] Back to main menu")

        choice = input("\nSelect option: ").strip().lower()

        if choice == "b":
            break
        elif choice == "1":
            print("\nAvailable resolutions:")
            print("  720p, 1080p, 1440p, 4k, source")
            val = input("Enter resolution: ").strip().lower()
            if val in ["720p", "1080p", "1440p", "4k", "source"]:
                config["target_resolution"] = val
        elif choice == "2":
            try:
                val = int(input("Enter FPS (e.g., 24, 30, 60): ").strip())
                if 1 <= val <= 120:
                    config["target_fps"] = val
            except ValueError:
                pass
        elif choice == "3":
            print("\nAspect ratios: 16:9, 4:3, 21:9, source")
            val = input("Enter aspect ratio: ").strip()
            if val in ["16:9", "4:3", "21:9", "source"]:
                config["aspect_ratio"] = val
        elif choice == "4":
            try:
                val = int(input("Enter CRF (0-51, recommended 18-23): ").strip())
                if 0 <= val <= 51:
                    config["crf"] = val
            except ValueError:
                pass
        elif choice == "5":
            print("\nPresets: ultrafast, fast, medium, slow, veryslow")
            val = input("Enter preset: ").strip().lower()
            if val in ["ultrafast", "fast", "medium", "slow", "veryslow"]:
                config["preset"] = val
        elif choice == "6":
            exts = input("Enter extensions (comma-separated, e.g., .mp4,.avi): ").strip()
            if exts:
                config["video_extensions"] = [e.strip() for e in exts.split(",")]

    return config


def generate_output_filename(directory: str) -> str:
    """Generate output filename based on directory name and timestamp."""
    dir_name = os.path.basename(directory.rstrip("/"))
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{dir_name}_concat_{timestamp}.mp4"


def main():
    """Main interactive loop."""
    script_dir = Path(__file__).resolve().parent
    configs_dir = script_dir.parent / "configs"

    # Load config from YAML file
    config_path = configs_dir / "concat_config.yaml"
    config = load_config(str(config_path))

    source_dir = None
    preview_data = None

    while True:
        clear_screen()
        print_header()

        # Show current state
        print("Current Configuration:")
        print(f"  Source folder:  {source_dir or '(not set)'}")
        print(f"  Resolution:     {config.get('target_resolution', '1080p')}")
        print(f"  FPS:            {config.get('target_fps', 30)}")

        if source_dir:
            video_exts = config.get("video_extensions", DEFAULT_CONFIG["video_extensions"])
            try:
                files = get_video_files(source_dir, video_exts)
                print(f"  Videos found:   {len(files)}")
            except Exception:
                print(f"  Videos found:   (error reading)")

        print()

        options = {
            "1": "Select source folder",
            "2": "Preview videos",
            "3": "Concatenate videos",
            "4": "Settings",
            "q": "Quit",
        }

        choice = print_menu("MAIN MENU", options)

        if choice == "q":
            print("\nGoodbye!")
            break

        elif choice == "1":
            result = browse_directory(source_dir, config.get("video_extensions"))
            if result:
                source_dir = result
                preview_data = None

        elif choice == "2":
            if not source_dir:
                print("\nPlease select a source folder first!")
                input("Press Enter...")
                continue

            preview_data = preview_videos(source_dir, config)
            input("\nPress Enter to continue...")

        elif choice == "3":
            if not source_dir:
                print("\nPlease select a source folder first!")
                input("Press Enter...")
                continue

            # Generate default output filename
            default_output = generate_output_filename(source_dir)
            output_dir = os.path.dirname(source_dir) or "."
            default_path = os.path.join(output_dir, default_output)

            print(f"\nDefault output: {default_path}")
            custom = input("Enter custom output path (or press Enter for default): ").strip()
            output_file = custom if custom else default_path

            # Confirm
            print(f"\nSource:  {source_dir}")
            print(f"Output:  {output_file}")
            confirm = input("Start concatenation? (y/n): ").strip().lower()

            if confirm == "y":
                stats = run_concat(source_dir, output_file, config)
                input("\nPress Enter to continue...")

        elif choice == "4":
            config = show_settings_menu(config)
            # Save config
            os.makedirs(configs_dir, exist_ok=True)
            save_config(config, str(config_path))


if __name__ == "__main__":
    main()
