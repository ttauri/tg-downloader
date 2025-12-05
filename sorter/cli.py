#!/usr/bin/env python3
"""
Interactive CLI for the video sorter using Rich + Questionary.

Workflow:
1. Select directory with videos
2. Preview - analyze files and see categorization stats
3. Sort - choose sorting method and move files
4. Reset - move all files back to root directory
"""

import os
from pathlib import Path
from typing import Optional

import questionary
from questionary import Style
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.table import Table
from rich.text import Text
from rich import box

from sorter import (
    CATEGORIZATION_METHODS,
    DEFAULT_CONFIG,
    load_config,
    preview_videos,
    reset_sorting,
    save_config,
    sort_by_bitrate,
    sort_by_duration,
    sort_by_orientation,
    sort_by_pipeline,
    sort_by_quality,
    split_into_folders,
)

# Initialize Rich console
console = Console()

# Custom style for questionary
custom_style = Style([
    ('qmark', 'fg:cyan bold'),
    ('question', 'bold'),
    ('answer', 'fg:cyan'),
    ('pointer', 'fg:cyan bold'),
    ('highlighted', 'fg:cyan bold'),
    ('selected', 'fg:green'),
    ('separator', 'fg:gray'),
    ('instruction', 'fg:gray'),
])


def clear_screen():
    """Clear terminal screen."""
    console.clear()


def print_header():
    """Print app header."""
    header = Text()
    header.append("VIDEO SORTER", style="bold cyan")
    header.append(" - Organize Videos by Properties", style="dim")
    console.print(Panel(header, box=box.DOUBLE, border_style="cyan"))
    console.print()


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


def format_bitrate(bitrate: int) -> str:
    """Format bitrate to human-readable string."""
    if bitrate < 1000:
        return f"{bitrate} bps"
    elif bitrate < 1000000:
        return f"{bitrate / 1000:.1f} Kbps"
    else:
        return f"{bitrate / 1000000:.1f} Mbps"


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


def browse_directory(start_path=None, video_extensions=None) -> Optional[str]:
    """Interactive directory browser using questionary."""
    if video_extensions is None:
        video_extensions = DEFAULT_CONFIG["video_extensions"]

    if start_path is None:
        media_dir = find_media_directory()
        start_path = media_dir if media_dir else os.getcwd()

    current = Path(start_path).resolve()

    while True:
        clear_screen()
        print_header()

        console.print(f"[bold]Current:[/bold] [cyan]{current}[/cyan]\n")

        try:
            dirs = sorted(
                [d for d in current.iterdir() if d.is_dir() and not d.name.startswith(".")]
            )
        except PermissionError:
            console.print("[red]Permission denied![/red]")
            current = current.parent
            continue

        # Count videos in current directory
        videos = [
            f for f in current.iterdir()
            if f.is_file() and f.suffix.lower() in video_extensions
        ]
        console.print(f"[green]{len(videos)}[/green] video files in this directory\n")

        # Build choices
        choices = []
        choices.append(questionary.Separator("── Navigation ──"))
        choices.append({"name": "📁 .. (Parent directory)", "value": ".."})

        if dirs:
            choices.append(questionary.Separator("── Subdirectories ──"))
            for d in dirs[:20]:
                try:
                    video_count = len([
                        f for f in d.iterdir()
                        if f.is_file() and f.suffix.lower() in video_extensions
                    ])
                    count_str = f" ({video_count} videos)" if video_count > 0 else ""
                except:
                    count_str = ""
                choices.append({"name": f"📂 {d.name}/{count_str}", "value": str(d)})

            if len(dirs) > 20:
                choices.append({"name": f"... and {len(dirs) - 20} more", "value": None, "disabled": True})

        choices.append(questionary.Separator("── Actions ──"))
        choices.append({"name": "✓ SELECT this directory", "value": "SELECT"})
        choices.append({"name": "✎ Enter path manually", "value": "MANUAL"})
        choices.append({"name": "✗ Cancel", "value": "CANCEL"})

        result = questionary.select(
            "Choose directory:",
            choices=choices,
            style=custom_style,
            use_shortcuts=True,
        ).ask()

        if result is None or result == "CANCEL":
            return None
        elif result == "SELECT":
            return str(current)
        elif result == "MANUAL":
            path = questionary.path(
                "Enter path:",
                only_directories=True,
                style=custom_style,
            ).ask()
            if path and os.path.isdir(path):
                return path
            else:
                console.print("[red]Invalid path![/red]")
                questionary.press_any_key_to_continue().ask()
        elif result == "..":
            current = current.parent
        elif result and os.path.isdir(result):
            current = Path(result)


def run_preview(directory: str, config: dict):
    """Preview videos and show categorization stats with Rich output."""
    console.print(f"\n[bold]Analyzing videos in:[/bold] [cyan]{directory}[/cyan]")

    files_data = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Analyzing...", total=None)

        def on_progress(current, total, filename):
            progress.update(task, total=total, completed=current, description=f"Analyzing {filename[:30]}...")

        result = preview_videos(directory, config, on_progress)

    files = result["files"]
    stats = result["stats"]
    errors = result["errors"]
    thresholds = result.get("thresholds", {})

    if not files:
        console.print("[yellow]No video files found![/yellow]")
        return result

    # Create file list table
    table = Table(title=f"Found {len(files)} video files", box=box.ROUNDED)
    table.add_column("Filename", style="cyan", max_width=35)
    table.add_column("Duration", justify="right")
    table.add_column("Resolution", justify="right")
    table.add_column("Bitrate", justify="right")
    table.add_column("O", justify="center")  # Orientation
    table.add_column("Q", justify="center")  # Quality

    display_files = files[:15] + files[-5:] if len(files) > 20 else files

    for i, vid in enumerate(display_files):
        if i == 15 and len(files) > 20:
            table.add_row("...", f"({len(files) - 20} more)", "...", "...", "...", "...")

        name = vid["filename"]
        if len(name) > 33:
            name = name[:30] + "..."

        dur_str = format_duration(vid["duration"])
        res_str = f"{vid['width']}x{vid['height']}"
        br_str = format_bitrate(vid["bitrate"]) if vid["bitrate"] else "N/A"
        ori = "H" if vid["orientation"] == "horizontal" else "V"
        ori_style = "green" if ori == "H" else "magenta"

        qual = vid["quality_cat"][0].upper()
        qual_style = {"H": "green", "M": "yellow", "L": "red", "U": "dim"}.get(qual, "dim")

        table.add_row(
            name,
            dur_str,
            res_str,
            br_str,
            f"[{ori_style}]{ori}[/{ori_style}]",
            f"[{qual_style}]{qual}[/{qual_style}]",
        )

    console.print(table)

    # Stats panel
    console.print()

    # Orientation stats
    ori_table = Table(title="By Orientation", box=box.SIMPLE)
    ori_table.add_column("Category", style="bold")
    ori_table.add_column("Count", justify="right")
    ori_table.add_column("Percentage", justify="right")
    ori_table.add_column("", min_width=20)

    for key, count in stats["orientation"].items():
        pct = count / len(files) * 100 if files else 0
        bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
        ori_table.add_row(key, str(count), f"{pct:.1f}%", f"[cyan]{bar}[/cyan]")

    console.print(ori_table)

    # Duration stats with threshold info
    dur_thresh = thresholds.get("duration", {})
    dur_method = dur_thresh.get("method", "fixed")
    dur_values = dur_thresh.get("values", [])

    dur_title = f"By Duration (method: {dur_method})"
    if dur_values and dur_method != "fixed":
        thresh_str = ", ".join([format_duration(v) for v in dur_values])
        dur_title += f" - thresholds: {thresh_str}"

    dur_table = Table(title=dur_title, box=box.SIMPLE)
    dur_table.add_column("Category", style="bold")
    dur_table.add_column("Count", justify="right")
    dur_table.add_column("Percentage", justify="right")
    dur_table.add_column("", min_width=20)

    for key, count in stats["duration"].items():
        pct = count / len(files) * 100 if files else 0
        bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
        dur_table.add_row(key, str(count), f"{pct:.1f}%", f"[green]{bar}[/green]")

    console.print(dur_table)

    # Quality stats with threshold info
    qual_thresh = thresholds.get("quality", {})
    qual_method = qual_thresh.get("method", "fixed")
    qual_values = qual_thresh.get("values", [])

    qual_title = f"By Quality (method: {qual_method})"
    if qual_values and qual_method != "fixed":
        thresh_str = ", ".join([f"{v:.2f}" for v in qual_values])
        qual_title += f" - thresholds: {thresh_str}"

    qual_table = Table(title=qual_title, box=box.SIMPLE)
    qual_table.add_column("Category", style="bold")
    qual_table.add_column("Count", justify="right")
    qual_table.add_column("Percentage", justify="right")
    qual_table.add_column("", min_width=20)

    for key, count in stats["quality"].items():
        if count > 0:
            pct = count / len(files) * 100 if files else 0
            bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
            qual_table.add_row(key, str(count), f"{pct:.1f}%", f"[yellow]{bar}[/yellow]")

    console.print(qual_table)

    if errors:
        console.print(f"\n[red]Errors: {len(errors)} files could not be analyzed[/red]")

    return result


def run_sort(directory: str, sort_type: str, config: dict, dry_run: bool = False):
    """Run the selected sorting method with Rich progress."""
    prefix = "[DRY RUN] " if dry_run else ""
    console.print(f"\n[bold]{prefix}Sorting by:[/bold] [cyan]{sort_type}[/cyan]")
    console.print(f"[bold]Directory:[/bold] [cyan]{directory}[/cyan]\n")

    results = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Sorting...", total=None)

        def on_progress(current, total, filename, category):
            progress.update(task, total=total, completed=current,
                          description=f"{filename[:25]}... → {category}")
            results.append((filename, category))

        if sort_type == "orientation":
            result = sort_by_orientation(directory, config, dry_run, on_progress)
        elif sort_type == "duration":
            result = sort_by_duration(directory, config, dry_run, on_progress)
        elif sort_type == "quality":
            result = sort_by_quality(directory, config, dry_run, on_progress)
        elif sort_type == "pipeline":
            result = sort_by_pipeline(directory, config, dry_run, on_progress)
        else:
            console.print(f"[red]Unknown sort type: {sort_type}[/red]")
            return None

    # Summary
    action = "Would move" if dry_run else "Moved"
    console.print(f"\n[green]✓ {action}: {result['moved']} files[/green]")

    if result.get("errors"):
        console.print(f"[red]Errors: {result['errors']}[/red]")

    if result.get("stats"):
        stats_table = Table(title="By Category", box=box.SIMPLE)
        stats_table.add_column("Category", style="cyan")
        stats_table.add_column("Count", justify="right")
        for cat, count in sorted(result["stats"].items()):
            stats_table.add_row(cat, str(count))
        console.print(stats_table)

    return result


def run_split(directory: str, files_per_folder: int, config: dict, dry_run: bool = False):
    """Split files into numbered folders with Rich progress."""
    prefix = "[DRY RUN] " if dry_run else ""
    console.print(f"\n[bold]{prefix}Splitting into folders of {files_per_folder}[/bold]")
    console.print(f"[bold]Directory:[/bold] [cyan]{directory}[/cyan]\n")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Splitting...", total=None)

        def on_progress(current, total, filename, folder):
            progress.update(task, total=total, completed=current,
                          description=f"{filename[:25]}... → {folder}")

        result = split_into_folders(directory, files_per_folder, config, dry_run, on_progress)

    if result.get("message"):
        console.print(f"[yellow]{result['message']}[/yellow]")
    else:
        action = "Would move" if dry_run else "Moved"
        console.print(f"\n[green]✓ {action}: {result['moved']} files into {result['folders']} folders[/green]")

    return result


def run_reset(directory: str, config: dict, dry_run: bool = False):
    """Reset sorting with Rich progress."""
    prefix = "[DRY RUN] " if dry_run else ""
    console.print(f"\n[bold]{prefix}Resetting - moving files back to root[/bold]")
    console.print(f"[bold]Directory:[/bold] [cyan]{directory}[/cyan]\n")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Resetting...", total=None)

        def on_progress(current, total, filename, from_dir):
            progress.update(task, total=total, completed=current,
                          description=f"{from_dir}/{filename[:20]}...")

        result = reset_sorting(directory, config, dry_run, on_progress)

    action = "Would move" if dry_run else "Moved"
    console.print(f"\n[green]✓ {action}: {result['moved']} files[/green]")

    if result.get("errors"):
        console.print(f"[red]Errors: {result['errors']}[/red]")

    return result


def show_settings_menu(config: dict) -> dict:
    """Show and edit settings using questionary."""
    while True:
        clear_screen()
        print_header()

        # Current settings display
        settings_table = Table(title="Current Settings", box=box.ROUNDED)
        settings_table.add_column("Setting", style="bold")
        settings_table.add_column("Value", style="cyan")

        settings_table.add_row("Duration method", config.get("duration_method", "fixed"))
        settings_table.add_row("Quality method", config.get("quality_method", "fixed"))
        settings_table.add_row("Categories", str(config.get("num_categories", 3)))
        settings_table.add_row("", "")
        settings_table.add_row("Duration short max", f"{config.get('duration_short_max', 60)}s")
        settings_table.add_row("Duration medium max", f"{config.get('duration_medium_max', 300)}s")
        settings_table.add_row("Quality high min", f"{config.get('quality_high_min', 1.0):.0%}")
        settings_table.add_row("Quality medium min", f"{config.get('quality_medium_min', 0.5):.0%}")
        settings_table.add_row("Bitrate factor", str(config.get("bitrate_factor", 0.13)))

        console.print(settings_table)
        console.print()

        choice = questionary.select(
            "What would you like to change?",
            choices=[
                questionary.Separator("── Categorization Methods ──"),
                {"name": "Duration method", "value": "duration_method"},
                {"name": "Quality method", "value": "quality_method"},
                {"name": "Number of categories", "value": "num_categories"},
                questionary.Separator("── Fixed Thresholds ──"),
                {"name": "Duration - short max", "value": "duration_short_max"},
                {"name": "Duration - medium max", "value": "duration_medium_max"},
                {"name": "Quality - high min", "value": "quality_high_min"},
                {"name": "Quality - medium min", "value": "quality_medium_min"},
                questionary.Separator("── Other ──"),
                {"name": "Bitrate factor", "value": "bitrate_factor"},
                {"name": "Video extensions", "value": "video_extensions"},
                questionary.Separator(""),
                {"name": "← Back to main menu", "value": "back"},
            ],
            style=custom_style,
        ).ask()

        if choice is None or choice == "back":
            break
        elif choice in ["duration_method", "quality_method"]:
            current = config.get(choice, "fixed")
            method_choices = []
            for m in CATEGORIZATION_METHODS:
                desc = {
                    "fixed": "Use fixed thresholds from config",
                    "percentile": "Split at 33rd/66th percentile",
                    "stddev": "Use mean ± standard deviation",
                    "kmeans": "K-means clustering (natural groups)",
                    "jenks": "Jenks natural breaks",
                }.get(m, "")
                name = f"{m} - {desc}" if desc else m
                if m == current:
                    name = f"● {name}"
                method_choices.append({"name": name, "value": m})

            new_val = questionary.select(
                f"Select {choice.replace('_', ' ')}:",
                choices=method_choices,
                style=custom_style,
            ).ask()
            if new_val:
                config[choice] = new_val

        elif choice == "num_categories":
            new_val = questionary.select(
                "Number of categories:",
                choices=[
                    {"name": "2 (short/long, low/high)", "value": 2},
                    {"name": "3 (short/medium/long, low/medium/high)", "value": 3},
                ],
                style=custom_style,
            ).ask()
            if new_val:
                config["num_categories"] = new_val

        elif choice in ["duration_short_max", "duration_medium_max"]:
            current = config.get(choice, 60 if "short" in choice else 300)
            new_val = questionary.text(
                f"Enter {choice.replace('_', ' ')} (seconds):",
                default=str(current),
                style=custom_style,
            ).ask()
            try:
                val = int(new_val)
                if val > 0:
                    config[choice] = val
            except (ValueError, TypeError):
                pass

        elif choice in ["quality_high_min", "quality_medium_min"]:
            current = config.get(choice, 1.0 if "high" in choice else 0.5)
            new_val = questionary.text(
                f"Enter {choice.replace('_', ' ')} (ratio, e.g., 1.0 = 100%):",
                default=str(current),
                style=custom_style,
            ).ask()
            try:
                val = float(new_val)
                if 0 < val <= 2:
                    config[choice] = val
            except (ValueError, TypeError):
                pass

        elif choice == "bitrate_factor":
            current = config.get("bitrate_factor", 0.13)
            new_val = questionary.text(
                "Enter bitrate factor:",
                default=str(current),
                style=custom_style,
            ).ask()
            try:
                val = float(new_val)
                if 0 < val < 1:
                    config["bitrate_factor"] = val
            except (ValueError, TypeError):
                pass

        elif choice == "video_extensions":
            current = ", ".join(config.get("video_extensions", []))
            new_val = questionary.text(
                "Enter extensions (comma-separated):",
                default=current,
                style=custom_style,
            ).ask()
            if new_val:
                config["video_extensions"] = [e.strip() for e in new_val.split(",")]

    return config


def show_method_description(method: str):
    """Show detailed description for a sorting method."""
    descriptions = {
        "orientation": {
            "title": "Sort by Orientation",
            "desc": "Separates videos based on aspect ratio (width vs height).",
            "example": """
[bold]Example:[/bold]
  video1.mp4 (1920x1080) → [green]horizontal/[/green]video1.mp4
  video2.mp4 (1080x1920) → [magenta]vertical/[/magenta]video2.mp4
  video3.mp4 (720x1280)  → [magenta]vertical/[/magenta]video3.mp4

[dim]Use case: Separate phone recordings (vertical) from camera/screen recordings (horizontal)[/dim]
""",
        },
        "duration": {
            "title": "Sort by Duration",
            "desc": "Groups videos by length into short/medium/long categories.",
            "example": """
[bold]Example (with fixed thresholds: short<60s, medium<300s):[/bold]
  clip1.mp4 (30s)   → [cyan]short_under_60s/[/cyan]clip1.mp4
  clip2.mp4 (2m)    → [yellow]medium_60s-300s/[/yellow]clip2.mp4
  movie.mp4 (10m)   → [green]long_over_300s/[/green]movie.mp4

[bold]Dynamic methods calculate thresholds from your actual videos:[/bold]
  • percentile: Equal distribution (33% in each category)
  • kmeans: Finds natural clusters in your durations
  • jenks: Minimizes variation within each group

[dim]Folder names include threshold values for clarity (e.g., medium_37s-53s)[/dim]
""",
        },
        "quality": {
            "title": "Sort by Quality",
            "desc": "Groups videos by bitrate relative to their resolution.",
            "example": """
[bold]How it works:[/bold]
  optimal_bitrate = width × height × fps × 0.13
  quality_ratio = actual_bitrate / optimal_bitrate × 100%

[bold]Example (1080p@30fps, optimal ~8Mbps, thresholds: 50%, 100%):[/bold]
  video1.mp4 (12 Mbps) → 150%  → [green]high_over_100pct/[/green]video1.mp4
  video2.mp4 (5 Mbps)  → 60%   → [yellow]medium_50-100pct/[/yellow]video2.mp4
  video3.mp4 (2 Mbps)  → 25%   → [red]low_under_50pct/[/red]video3.mp4

[dim]Folder names show quality thresholds (e.g., medium_48-80pct with percentile method)[/dim]
""",
        },
        "pipeline": {
            "title": "Sort by Pipeline",
            "desc": "Creates nested folder structure: orientation → duration → bitrate.",
            "example": """
[bold]Example folder structure (threshold: 300 Kbps):[/bold]
  horizontal/
    short_under_60s/
      normal_over_300kbps/
      low_under_300kbps/
    medium_60s-300s/
    long_over_300s/
  vertical/
    ...

[bold]Example file placement:[/bold]
  clip.mp4 (1920x1080, 45s, 500 Kbps)
    → [cyan]horizontal/short_under_60s/normal_over_300kbps/[/cyan]clip.mp4
  reel.mp4 (1080x1920, 3m, 200 Kbps)
    → [magenta]vertical/medium_60s-300s/low_under_300kbps/[/magenta]reel.mp4

[dim]Use case: Organize by all criteria, separating bad quality for exclusion from concat[/dim]
""",
        },
        "split": {
            "title": "Split into Folders",
            "desc": "Divides videos into numbered folders with N files each.",
            "example": """
[bold]Example (100 files per folder):[/bold]
  1/
    video001.mp4
    video002.mp4
    ... (100 files)
  2/
    video101.mp4
    video102.mp4
    ... (100 files)
  3/
    ...

[dim]Use case: Break up large collections for easier batch processing[/dim]
""",
        },
    }

    info = descriptions.get(method, {})
    if info:
        console.print(Panel(
            f"[bold]{info['title']}[/bold]\n\n{info['desc']}\n{info['example']}",
            border_style="cyan",
            box=box.ROUNDED,
        ))


def build_sort_tree(files: list, sort_type: str, config: dict = None) -> dict:
    """Build a tree structure of how files will be sorted."""
    tree = {}

    if config is None:
        config = DEFAULT_CONFIG.copy()

    bitrate_threshold = config.get("bitrate_threshold", 300) * 1000  # to bps
    thresh_kbps = config.get("bitrate_threshold", 300)

    for vid in files:
        if sort_type == "orientation":
            path_parts = [vid["orientation"]]
        elif sort_type == "duration":
            path_parts = [vid["duration_cat"]]
        elif sort_type == "quality":
            path_parts = [vid["quality_cat"]]
        elif sort_type == "bitrate":
            bitrate = vid.get("bitrate", 0)
            if bitrate > 0 and bitrate < bitrate_threshold:
                path_parts = [f"low_under_{thresh_kbps}kbps"]
            else:
                path_parts = [f"normal_over_{thresh_kbps}kbps"]
        elif sort_type == "pipeline":
            # Pipeline uses orientation -> duration -> bitrate
            bitrate = vid.get("bitrate", 0)
            if bitrate > 0 and bitrate < bitrate_threshold:
                bitrate_cat = f"low_under_{thresh_kbps}kbps"
            else:
                bitrate_cat = f"normal_over_{thresh_kbps}kbps"
            path_parts = [vid["orientation"], vid["duration_cat"], bitrate_cat]
        else:
            path_parts = []

        # Build nested dict
        current = tree
        for part in path_parts[:-1]:
            if part not in current:
                current[part] = {}
            current = current[part]

        # Add file to final folder
        final_folder = path_parts[-1] if path_parts else "root"
        if final_folder not in current:
            current[final_folder] = []
        current[final_folder].append(vid)

    return tree


def calculate_folder_totals(tree: dict) -> dict:
    """Calculate total duration for each folder in tree."""
    totals = {}

    def calc_recursive(node, path=""):
        total_duration = 0
        if isinstance(node, dict):
            for key, value in node.items():
                child_path = f"{path}/{key}" if path else key
                child_duration = calc_recursive(value, child_path)
                total_duration += child_duration
            if path:
                totals[path] = total_duration
        elif isinstance(node, list):
            total_duration = sum(vid.get("duration", 0) for vid in node)
            totals[path] = total_duration
        return total_duration

    calc_recursive(tree)
    return totals


def print_sort_tree(tree: dict, indent: int = 0, path: str = "", folder_totals: dict = None):
    """Print the sort tree with file details."""
    if folder_totals is None:
        folder_totals = calculate_folder_totals(tree)

    for key, value in sorted(tree.items()):
        prefix = "  " * indent
        current_path = f"{path}/{key}" if path else key

        if isinstance(value, dict):
            # It's a folder with subfolders
            total_dur = folder_totals.get(current_path, 0)
            console.print(f"{prefix}[bold cyan]📁 {key}/[/bold cyan] [dim](total: {format_duration(total_dur)})[/dim]")
            print_sort_tree(value, indent + 1, current_path, folder_totals)
        elif isinstance(value, list):
            # It's a folder with files
            total_dur = folder_totals.get(current_path, 0)
            console.print(f"{prefix}[bold cyan]📁 {key}/[/bold cyan] [dim]({len(value)} files, {format_duration(total_dur)})[/dim]")

            # Show files (limit to first 10 + summary)
            display_files = value[:10]
            for vid in display_files:
                name = vid["filename"]
                if len(name) > 30:
                    name = name[:27] + "..."

                dur = format_duration(vid["duration"])
                res = f"{vid['width']}x{vid['height']}"
                br = format_bitrate(vid["bitrate"]) if vid["bitrate"] else "N/A"

                console.print(f"{prefix}  [dim]├─[/dim] {name}")
                console.print(f"{prefix}  [dim]│  {res} | {dur} | {br}[/dim]")

            if len(value) > 10:
                console.print(f"{prefix}  [dim]└─ ... and {len(value) - 10} more files[/dim]")


def show_sort_preview(directory: str, sort_type: str, config: dict) -> bool:
    """Show tree preview of sorting and ask for confirmation."""
    clear_screen()
    print_header()

    console.print(f"[bold]Sorting by:[/bold] [cyan]{sort_type}[/cyan]")
    console.print(f"[bold]Directory:[/bold] [cyan]{directory}[/cyan]\n")

    # Analyze videos
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Analyzing videos...", total=None)

        def on_progress(current, total, filename):
            progress.update(task, description=f"Analyzing {filename[:30]}...")

        result = preview_videos(directory, config, on_progress)

    files = result["files"]

    if not files:
        console.print("[yellow]No video files found![/yellow]")
        return False

    # Show threshold info
    thresholds = result.get("thresholds", {})
    if sort_type in ["duration", "pipeline"]:
        dur_info = thresholds.get("duration", {})
        method = dur_info.get("method", "fixed")
        labels = dur_info.get("labels", [])
        console.print(f"[bold]Duration:[/bold] method={method}")
        if labels:
            console.print(f"  Categories: {', '.join(labels)}")

    if sort_type == "quality":
        qual_info = thresholds.get("quality", {})
        method = qual_info.get("method", "fixed")
        labels = qual_info.get("labels", [])
        console.print(f"[bold]Quality:[/bold] method={method}")
        if labels:
            console.print(f"  Categories: {', '.join(labels)}")

    if sort_type in ["bitrate", "pipeline"]:
        thresh = config.get("bitrate_threshold", 300)
        console.print(f"[bold]Bitrate threshold:[/bold] {thresh} Kbps")
        console.print(f"  [dim]< {thresh} Kbps = low (bad quality)[/dim]")
        console.print(f"  [dim]≥ {thresh} Kbps = normal (good for concat)[/dim]")

    console.print()

    # Build and display tree
    tree = build_sort_tree(files, sort_type, config)

    console.print(Panel("[bold]Proposed folder structure:[/bold]", box=box.SIMPLE))
    print_sort_tree(tree)

    # Summary
    console.print()
    total_folders = sum(1 for _ in _count_folders(tree))
    console.print(f"[bold]Summary:[/bold] {len(files)} files → {total_folders} folders")

    return True


def _count_folders(tree: dict):
    """Generator to count all leaf folders in tree."""
    for key, value in tree.items():
        if isinstance(value, dict):
            yield from _count_folders(value)
        elif isinstance(value, list):
            yield key


def execute_sort(directory: str, sort_type: str, config: dict):
    """Actually move the files after user confirmation."""
    console.print()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Moving files...", total=None)

        def on_progress(current, total, filename, category):
            progress.update(task, total=total, completed=current,
                          description=f"Moving {filename[:25]}...")

        if sort_type == "orientation":
            result = sort_by_orientation(directory, config, dry_run=False, on_progress=on_progress)
        elif sort_type == "duration":
            result = sort_by_duration(directory, config, dry_run=False, on_progress=on_progress)
        elif sort_type == "quality":
            result = sort_by_quality(directory, config, dry_run=False, on_progress=on_progress)
        elif sort_type == "bitrate":
            result = sort_by_bitrate(directory, config, dry_run=False, on_progress=on_progress)
        elif sort_type == "pipeline":
            result = sort_by_pipeline(directory, config, dry_run=False, on_progress=on_progress)

    console.print(f"\n[green]✓ Moved {result['moved']} files successfully![/green]")
    return result


def show_sort_menu(directory: str, config: dict):
    """Show sorting workflow: select method → preview tree → accept/decline."""
    while True:
        clear_screen()
        print_header()
        console.print(f"[bold]Sort videos in:[/bold] [cyan]{directory}[/cyan]\n")

        # Show current method settings
        dur_method = config.get('duration_method', 'fixed')
        qual_method = config.get('quality_method', 'fixed')
        bitrate_thresh = config.get('bitrate_threshold', 300)
        console.print(f"[dim]Duration: {dur_method} | Quality: {qual_method} | Bitrate threshold: {bitrate_thresh} Kbps[/dim]\n")

        choice = questionary.select(
            "Select action:",
            choices=[
                questionary.Separator("── Settings ──"),
                {"name": "⚙  Change duration method", "value": "change_duration"},
                {"name": "⚙  Change quality method", "value": "change_quality"},
                {"name": f"⚙  Change bitrate threshold ({bitrate_thresh} Kbps)", "value": "change_bitrate"},
                questionary.Separator("── Sort Videos ──"),
                {"name": "📐 Sort by Orientation (horizontal/vertical)", "value": "orientation"},
                {"name": "⏱  Sort by Duration (short/medium/long)", "value": "duration"},
                {"name": "📊 Sort by Bitrate (low/normal) - for concat prep", "value": "bitrate"},
                {"name": "🎬 Sort by Quality (low/medium/high)", "value": "quality"},
                {"name": "🔀 Sort by Pipeline (orientation→duration→quality)", "value": "pipeline"},
                {"name": "📁 Split into folders (N files per folder)", "value": "split"},
                questionary.Separator(""),
                {"name": "❓ Show method descriptions", "value": "help"},
                {"name": "← Back", "value": "back"},
            ],
            style=custom_style,
        ).ask()

        if choice is None or choice == "back":
            break

        elif choice == "change_duration":
            # Show detailed description
            console.print()
            console.print(Panel(
                "[bold]Duration Categorization Methods[/bold]\n\n"
                "[cyan]fixed[/cyan] - Static thresholds (default: 60s, 300s)\n"
                "  Always uses the same cutoffs regardless of your videos.\n"
                "  [dim]Example: 10 videos all under 30s → all go to 'short'[/dim]\n\n"
                "[cyan]percentile[/cyan] - Equal distribution (33% in each category)\n"
                "  Splits videos so each category has roughly equal count.\n"
                "  [dim]Example: 90 videos → 30 short, 30 medium, 30 long[/dim]\n"
                "  [dim]Thresholds adapt: if most videos are 20-40s, splits might be 25s/35s[/dim]\n\n"
                "[cyan]stddev[/cyan] - Statistical (mean ± 0.5×std deviation)\n"
                "  Centers categories around average duration.\n"
                "  [dim]Example: mean=45s, stddev=20s → short<35s, medium=35-55s, long>55s[/dim]\n"
                "  [dim]Good when durations follow normal distribution[/dim]\n\n"
                "[cyan]kmeans[/cyan] - K-means clustering\n"
                "  Finds natural groups by minimizing distance to cluster centers.\n"
                "  [dim]Example: videos at 10-20s, 60-90s, 200-300s → finds these 3 clusters[/dim]\n"
                "  [dim]Best when videos naturally form distinct groups[/dim]\n\n"
                "[cyan]jenks[/cyan] - Jenks natural breaks\n"
                "  Minimizes variance within groups, maximizes between groups.\n"
                "  [dim]Similar to kmeans but optimizes for homogeneous categories[/dim]\n"
                "  [dim]Often produces most 'natural' feeling splits[/dim]",
                title="Duration Methods",
                border_style="cyan",
                box=box.ROUNDED,
            ))

            current = config.get("duration_method", "fixed")
            method_choices = [{"name": f"{'● ' if m == current else '  '}{m}", "value": m}
                             for m in CATEGORIZATION_METHODS]

            new_method = questionary.select(
                "Select duration method:",
                choices=method_choices,
                style=custom_style,
            ).ask()
            if new_method:
                config["duration_method"] = new_method

        elif choice == "change_bitrate":
            console.print()
            console.print(Panel(
                "[bold]Bitrate Threshold[/bold]\n\n"
                "Simple cutoff to separate low quality from normal videos.\n"
                "Videos below this threshold go to 'low', others to 'normal'.\n\n"
                "[bold]Recommended values:[/bold]\n"
                "  [cyan]200 Kbps[/cyan] - Very strict, only truly terrible quality\n"
                "  [cyan]300 Kbps[/cyan] - Good default, catches ~10% worst videos\n"
                "  [cyan]400 Kbps[/cyan] - More strict, catches ~30-40% videos\n"
                "  [cyan]500 Kbps[/cyan] - Strict, about half will be 'low'\n\n"
                "[dim]Use case: Filter out bad videos before concatenation[/dim]",
                title="Bitrate Threshold",
                border_style="cyan",
                box=box.ROUNDED,
            ))

            current = config.get("bitrate_threshold", 300)
            new_val = questionary.text(
                f"Enter bitrate threshold in Kbps (current: {current}):",
                default=str(current),
                style=custom_style,
            ).ask()
            try:
                val = int(new_val)
                if val > 0:
                    config["bitrate_threshold"] = val
            except (ValueError, TypeError):
                pass

        elif choice == "change_quality":
            # Show detailed description
            console.print()
            console.print(Panel(
                "[bold]Quality Categorization Methods[/bold]\n\n"
                "Quality = actual_bitrate / optimal_bitrate × 100%\n"
                "[dim]Optimal bitrate = width × height × fps × 0.13[/dim]\n\n"
                "[cyan]fixed[/cyan] - Static thresholds (default: 50%, 100%)\n"
                "  <50% = low, 50-100% = medium, >100% = high quality.\n"
                "  [dim]Example: 1080p video at 4Mbps (optimal ~8Mbps) → 50% → medium[/dim]\n\n"
                "[cyan]percentile[/cyan] - Equal distribution (33% in each category)\n"
                "  Splits so each quality tier has similar count.\n"
                "  [dim]Example: 90 videos → 30 low, 30 medium, 30 high[/dim]\n"
                "  [dim]Useful when you want balanced categories[/dim]\n\n"
                "[cyan]stddev[/cyan] - Statistical (mean ± 0.5×std deviation)\n"
                "  Centers around average quality ratio.\n"
                "  [dim]Good for finding outliers (unusually good/bad quality)[/dim]\n\n"
                "[cyan]kmeans[/cyan] - K-means clustering\n"
                "  Groups videos with similar quality ratios together.\n"
                "  [dim]Example: finds clusters at 30%, 70%, 150% quality[/dim]\n"
                "  [dim]Best when quality naturally varies in distinct levels[/dim]\n\n"
                "[cyan]jenks[/cyan] - Jenks natural breaks\n"
                "  Optimizes for homogeneous quality groups.\n"
                "  [dim]Minimizes quality variation within each category[/dim]",
                title="Quality Methods",
                border_style="cyan",
                box=box.ROUNDED,
            ))

            current = config.get("quality_method", "fixed")
            method_choices = [{"name": f"{'● ' if m == current else '  '}{m}", "value": m}
                             for m in CATEGORIZATION_METHODS]

            new_method = questionary.select(
                "Select quality method:",
                choices=method_choices,
                style=custom_style,
            ).ask()
            if new_method:
                config["quality_method"] = new_method

        elif choice == "help":
            clear_screen()
            print_header()
            console.print("[bold]Sorting Methods Overview[/bold]\n")
            for method in ["orientation", "duration", "quality", "pipeline", "split"]:
                show_method_description(method)
                console.print()
            questionary.press_any_key_to_continue().ask()

        elif choice == "split":
            show_method_description("split")
            n_str = questionary.text(
                "Files per folder:",
                default="100",
                style=custom_style,
            ).ask()
            try:
                n = int(n_str)
            except (ValueError, TypeError):
                n = 100

            # For split, just run it with confirmation
            if questionary.confirm("Proceed with split?", style=custom_style).ask():
                run_split(directory, n, config, dry_run=False)

        elif choice in ["orientation", "duration", "quality", "bitrate", "pipeline"]:
            # New workflow: preview → accept/decline loop
            while True:
                has_files = show_sort_preview(directory, choice, config)

                if not has_files:
                    break

                console.print()
                action_choices = [
                    {"name": "✓ Accept and move files", "value": "accept"},
                    {"name": "⚙ Change duration method", "value": "change_duration"},
                ]
                if choice in ["bitrate", "pipeline"]:
                    action_choices.append({"name": "⚙ Change bitrate threshold", "value": "change_bitrate"})
                if choice == "quality":
                    action_choices.append({"name": "⚙ Change quality method", "value": "change_quality"})
                action_choices.append({"name": "✗ Cancel", "value": "cancel"})

                action = questionary.select(
                    "What would you like to do?",
                    choices=action_choices,
                    style=custom_style,
                ).ask()

                if action == "accept":
                    execute_sort(directory, choice, config)
                    break
                elif action == "change_duration":
                    console.print()
                    console.print("[bold]Duration Methods:[/bold]")
                    console.print("  [cyan]fixed[/cyan]      - Static thresholds (60s, 300s)")
                    console.print("  [cyan]percentile[/cyan] - Equal count in each category")
                    console.print("  [cyan]stddev[/cyan]     - Mean ± standard deviation")
                    console.print("  [cyan]kmeans[/cyan]     - Find natural clusters")
                    console.print("  [cyan]jenks[/cyan]      - Minimize within-group variance")
                    console.print()
                    current = config.get("duration_method", "fixed")
                    method_choices = [{"name": f"{'● ' if m == current else '  '}{m}", "value": m}
                                     for m in CATEGORIZATION_METHODS]
                    new_method = questionary.select("Duration method:", choices=method_choices, style=custom_style).ask()
                    if new_method:
                        config["duration_method"] = new_method
                    # Loop continues, will show new preview
                elif action == "change_quality":
                    console.print()
                    console.print("[bold]Quality Methods:[/bold]")
                    console.print("  [cyan]fixed[/cyan]      - Static thresholds (50%, 100%)")
                    console.print("  [cyan]percentile[/cyan] - Equal count in each category")
                    console.print("  [cyan]stddev[/cyan]     - Mean ± standard deviation")
                    console.print("  [cyan]kmeans[/cyan]     - Find natural clusters")
                    console.print("  [cyan]jenks[/cyan]      - Minimize within-group variance")
                    console.print()
                    current = config.get("quality_method", "fixed")
                    method_choices = [{"name": f"{'● ' if m == current else '  '}{m}", "value": m}
                                     for m in CATEGORIZATION_METHODS]
                    new_method = questionary.select("Quality method:", choices=method_choices, style=custom_style).ask()
                    if new_method:
                        config["quality_method"] = new_method
                    # Loop continues, will show new preview
                elif action == "change_bitrate":
                    console.print()
                    console.print("[bold]Bitrate Threshold:[/bold] 200=strict, 300=default, 400=loose, 500=very loose")
                    current = config.get("bitrate_threshold", 300)
                    new_val = questionary.text(
                        f"Enter threshold in Kbps (current: {current}):",
                        default=str(current),
                        style=custom_style,
                    ).ask()
                    try:
                        val = int(new_val)
                        if val > 0:
                            config["bitrate_threshold"] = val
                    except (ValueError, TypeError):
                        pass
                    # Loop continues, will show new preview
                else:  # cancel
                    break


def main():
    """Main interactive loop."""
    script_dir = Path(__file__).resolve().parent
    configs_dir = script_dir.parent / "configs"

    # Load config from YAML file
    config_path = configs_dir / "sorter_config.yaml"
    config = load_config(str(config_path))

    source_dir = None

    while True:
        clear_screen()
        print_header()

        # Show current state
        info_table = Table(box=box.ROUNDED, show_header=False, border_style="dim")
        info_table.add_column("Key", style="bold")
        info_table.add_column("Value", style="cyan")

        info_table.add_row("Source folder", source_dir or "[dim](not set)[/dim]")

        dur_method = config.get('duration_method', 'fixed')
        qual_method = config.get('quality_method', 'fixed')

        if dur_method == "fixed":
            dur_info = f"fixed (short < {config.get('duration_short_max', 60)}s, medium < {config.get('duration_medium_max', 300)}s)"
        else:
            dur_info = f"{dur_method} (dynamic)"
        info_table.add_row("Duration", dur_info)

        if qual_method == "fixed":
            qual_info = f"fixed (high ≥ {config.get('quality_high_min', 1.0):.0%}, medium ≥ {config.get('quality_medium_min', 0.5):.0%})"
        else:
            qual_info = f"{qual_method} (dynamic)"
        info_table.add_row("Quality", qual_info)

        if source_dir:
            video_exts = config.get("video_extensions", DEFAULT_CONFIG["video_extensions"])
            try:
                files = [f for f in os.listdir(source_dir)
                         if os.path.isfile(os.path.join(source_dir, f))
                         and os.path.splitext(f)[1].lower() in video_exts]
                info_table.add_row("Videos found", f"[green]{len(files)}[/green]")
            except Exception:
                info_table.add_row("Videos found", "[red]error[/red]")

        console.print(info_table)
        console.print()

        choice = questionary.select(
            "What would you like to do?",
            choices=[
                {"name": "📂 Select source folder", "value": "browse"},
                {"name": "👁  Preview videos", "value": "preview"},
                {"name": "📊 Sort videos", "value": "sort"},
                {"name": "↩  Reset (move all back to root)", "value": "reset"},
                {"name": "⚙  Settings", "value": "settings"},
                questionary.Separator(""),
                {"name": "✗ Quit", "value": "quit"},
            ],
            style=custom_style,
        ).ask()

        if choice is None or choice == "quit":
            # Save config before exit
            os.makedirs(configs_dir, exist_ok=True)
            save_config(config, str(config_path))
            console.print("\n[cyan]Goodbye![/cyan] 👋")
            break

        elif choice == "browse":
            result = browse_directory(source_dir, config.get("video_extensions"))
            if result:
                source_dir = result

        elif choice == "preview":
            if not source_dir:
                console.print("\n[yellow]Please select a source folder first![/yellow]")
                continue

            run_preview(source_dir, config)
            questionary.press_any_key_to_continue().ask()

        elif choice == "sort":
            if not source_dir:
                console.print("\n[yellow]Please select a source folder first![/yellow]")
                continue

            show_sort_menu(source_dir, config)

        elif choice == "reset":
            if not source_dir:
                console.print("\n[yellow]Please select a source folder first![/yellow]")
                continue

            if questionary.confirm("Do a dry run first?", default=True, style=custom_style).ask():
                run_reset(source_dir, config, dry_run=True)
                if questionary.confirm("Proceed with actual reset?", style=custom_style).ask():
                    run_reset(source_dir, config, dry_run=False)
            else:
                if questionary.confirm("Are you sure you want to reset?", style=custom_style).ask():
                    run_reset(source_dir, config, dry_run=False)

        elif choice == "settings":
            config = show_settings_menu(config)
            # Save config
            os.makedirs(configs_dir, exist_ok=True)
            save_config(config, str(config_path))


if __name__ == "__main__":
    main()
