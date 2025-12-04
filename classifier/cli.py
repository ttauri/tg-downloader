#!/usr/bin/env python3
"""
Interactive CLI for the video classifier.
"""

import os
from pathlib import Path

from classifier import (
    ALLOWED_LABELS,
    DEFAULT_CONFIG,
    DEFAULT_RULES,
    classify_and_sort,
    load_config,
    load_rules,
    save_config,
    save_rules,
)


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


def browse_directory(start_path=None, video_extensions=None):
    """Simple directory browser."""
    if video_extensions is None:
        video_extensions = DEFAULT_CONFIG["video_extensions"]

    current = Path(start_path or os.getcwd()).resolve()

    while True:
        clear_screen()
        print_header()
        print(f"Current: {current}\n")

        # List directories
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

        # Count video files
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


def show_settings_menu(config):
    """Show and edit settings."""
    while True:
        clear_screen()
        print_header()
        print("SETTINGS")
        print("-" * 40)
        print(f"  [1] Detection threshold: {config['threshold']}")
        print(f"  [2] Frames per video:    {config['num_frames']}")
        print(f"  [3] Video extensions:    {', '.join(config['video_extensions'])}")
        print()
        print("  [s] Save to config.json")
        print("  [l] Load from config.json")
        print("  [b] Back to main menu")

        choice = input("\nSelect option: ").strip().lower()

        if choice == "b":
            break
        elif choice == "1":
            try:
                val = float(input("Enter threshold (0.0-1.0): ").strip())
                if 0 <= val <= 1:
                    config["threshold"] = val
                else:
                    print("Value must be between 0 and 1")
                    input("Press Enter...")
            except ValueError:
                print("Invalid number")
                input("Press Enter...")
        elif choice == "2":
            try:
                val = int(input("Enter number of frames: ").strip())
                if val > 0:
                    config["num_frames"] = val
                else:
                    print("Value must be positive")
                    input("Press Enter...")
            except ValueError:
                print("Invalid number")
                input("Press Enter...")
        elif choice == "3":
            exts = input("Enter extensions (comma-separated, e.g., .mp4,.avi): ").strip()
            if exts:
                config["video_extensions"] = [e.strip() for e in exts.split(",")]
        elif choice == "s":
            save_config(config, "config.json")
            print("Saved to config.json")
            input("Press Enter...")
        elif choice == "l":
            loaded = load_config("config.json")
            config.update(loaded)
            print("Loaded from config.json")
            input("Press Enter...")

    return config


def show_rules_menu(rules):
    """Show and edit rules."""
    while True:
        clear_screen()
        print_header()
        print("CLASSIFICATION RULES (order = priority)")
        print("-" * 40)

        for i, rule in enumerate(rules, 1):
            thresholds = ", ".join([f"{k}: {v}%" for k, v in rule["thresholds"].items()])
            print(f"  [{i}] {rule['dir_name']}")
            print(f"      {rule.get('description', 'No description')}")
            print(f"      Thresholds: {thresholds}")
            print()

        print("  [a] Add new rule")
        print("  [d] Delete a rule")
        print("  [m] Move rule (change priority)")
        print("  [s] Save to rules.json")
        print("  [l] Load from rules.json")
        print("  [r] Reset to defaults")
        print("  [b] Back to main menu")

        choice = input("\nSelect option: ").strip().lower()

        if choice == "b":
            break
        elif choice == "a":
            new_rule = create_rule_wizard()
            if new_rule:
                rules.append(new_rule)
                print("Rule added!")
                input("Press Enter...")
        elif choice == "d":
            try:
                idx = int(input("Enter rule number to delete: ").strip()) - 1
                if 0 <= idx < len(rules):
                    deleted = rules.pop(idx)
                    print(f"Deleted: {deleted['dir_name']}")
                else:
                    print("Invalid rule number")
                input("Press Enter...")
            except ValueError:
                print("Invalid input")
                input("Press Enter...")
        elif choice == "m":
            try:
                idx = int(input("Enter rule number to move: ").strip()) - 1
                new_pos = int(input("Enter new position: ").strip()) - 1
                if 0 <= idx < len(rules) and 0 <= new_pos < len(rules):
                    rule = rules.pop(idx)
                    rules.insert(new_pos, rule)
                    print("Rule moved!")
                else:
                    print("Invalid positions")
                input("Press Enter...")
            except ValueError:
                print("Invalid input")
                input("Press Enter...")
        elif choice == "s":
            save_rules(rules, "rules.json")
            print("Saved to rules.json")
            input("Press Enter...")
        elif choice == "l":
            loaded = load_rules("rules.json")
            rules.clear()
            rules.extend(loaded)
            print("Loaded from rules.json")
            input("Press Enter...")
        elif choice == "r":
            rules.clear()
            rules.extend([r.copy() for r in DEFAULT_RULES])
            print("Reset to defaults")
            input("Press Enter...")

    return rules


def create_rule_wizard():
    """Wizard to create a new rule."""
    print("\n--- Create New Rule ---")

    dir_name = input("Directory name (e.g., 'category_name'): ").strip()
    if not dir_name:
        return None

    description = input("Description: ").strip()

    print("\nAvailable labels for thresholds:")
    for i, label in enumerate(ALLOWED_LABELS, 1):
        print(f"  {i}. {label}")

    thresholds = {}
    while True:
        label_input = input("\nEnter label number (or 'done' to finish): ").strip()
        if label_input.lower() == "done":
            break
        try:
            idx = int(label_input) - 1
            if 0 <= idx < len(ALLOWED_LABELS):
                label = ALLOWED_LABELS[idx]
                pct = float(input(f"  Minimum % for {label}: ").strip())
                thresholds[label] = pct
            else:
                print("Invalid label number")
        except ValueError:
            print("Invalid input")

    if not thresholds:
        print("No thresholds defined, rule not created")
        return None

    return {
        "dir_name": dir_name,
        "description": description,
        "thresholds": thresholds,
    }


def run_classification_interactive(input_dir, output_dir, config, rules, dry_run=False):
    """Run classification with interactive progress display."""

    def on_video_start(index, total, filename):
        print(f"[{index}/{total}] {filename}")

    def on_video_done(filename, classifications, category):
        if classifications:
            labels_str = ", ".join([f"{k}: {v:.0f}%" for k, v in classifications.items()])
            print(f"  Detected: {labels_str}")
        else:
            print(f"  Detected: (nothing above threshold)")

        if category and not category.startswith("ERROR"):
            action = "Would move to" if dry_run else "Moved to"
            print(f"  -> {action}: {category}/")
        elif category:
            print(f"  {category}")
        print()

    print("\nLoading NudeNet detector (this may take a moment)...")

    stats = classify_and_sort(
        input_dir=input_dir,
        output_dir=output_dir,
        config=config,
        rules=rules,
        dry_run=dry_run,
        on_video_start=on_video_start,
        on_video_done=on_video_done,
    )

    return stats


def main():
    """Main interactive loop."""
    config = DEFAULT_CONFIG.copy()
    rules = [r.copy() for r in DEFAULT_RULES]

    # Try to load saved config/rules
    if os.path.exists("config.json"):
        try:
            config = load_config("config.json")
        except Exception:
            pass

    if os.path.exists("rules.json"):
        try:
            rules = load_rules("rules.json")
        except Exception:
            pass

    input_dir = None
    output_dir = None

    while True:
        clear_screen()
        print_header()

        # Show current state
        print("Current Configuration:")
        print(f"  Input directory:  {input_dir or '(not set)'}")
        print(f"  Output directory: {output_dir or '(auto)'}")
        print(f"  Threshold: {config['threshold']}, Frames: {config['num_frames']}")
        print(f"  Rules: {len(rules)} configured")

        if input_dir:
            video_exts = config["video_extensions"]
            try:
                videos = [
                    f for f in os.listdir(input_dir)
                    if os.path.splitext(f)[1].lower() in video_exts
                ]
                print(f"  Videos found: {len(videos)}")
            except Exception:
                print("  Videos found: (error reading directory)")

        print()

        options = {
            "1": "Select input directory",
            "2": "Select output directory",
            "3": "Settings",
            "4": "Rules",
            "5": "Run classification",
            "6": "Dry run (preview)",
            "q": "Quit",
        }

        choice = print_menu("MAIN MENU", options)

        if choice == "q":
            print("\nGoodbye!")
            break
        elif choice == "1":
            result = browse_directory(input_dir or os.getcwd(), config["video_extensions"])
            if result:
                input_dir = result
                if not output_dir:
                    output_dir = os.path.join(input_dir, "classified")
        elif choice == "2":
            result = browse_directory(
                output_dir or input_dir or os.getcwd(), config["video_extensions"]
            )
            if result:
                output_dir = result
        elif choice == "3":
            config = show_settings_menu(config)
        elif choice == "4":
            rules = show_rules_menu(rules)
        elif choice in ("5", "6"):
            if not input_dir:
                print("\nPlease select an input directory first!")
                input("Press Enter...")
                continue

            dry_run = choice == "6"

            if not output_dir:
                output_dir = os.path.join(input_dir, "classified")

            print()
            if dry_run:
                print("=== DRY RUN MODE - No files will be moved ===\n")

            confirm = input(
                f"Start {'dry run' if dry_run else 'classification'}? (y/n): "
            ).strip().lower()

            if confirm == "y":
                stats = run_classification_interactive(
                    input_dir, output_dir, config, rules, dry_run=dry_run
                )

                print("\n" + "=" * 60)
                print("SUMMARY")
                print("=" * 60)
                print(f"  Processed: {stats['processed']}")
                print(f"  Errors: {stats.get('errors', 0)}")
                if stats.get("by_category"):
                    print("\n  By category:")
                    for cat, count in sorted(stats["by_category"].items()):
                        print(f"    {cat}: {count}")

                input("\nPress Enter to continue...")


if __name__ == "__main__":
    main()
