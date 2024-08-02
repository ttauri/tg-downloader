import argparse
import sys
import os
import glob
from tqdm import tqdm

# Add the parent directory of 'concatenator' to the Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, parent_dir)

from concatenator.utils import cleanup_temp_directory, sort_videos_by_orientation, sort_videos_by_bitrate, split_files_into_folders, get_video_info, format_duration, format_size, format_bitrate
from concatenator.core import VideoConcatenator

def main():
    parser = argparse.ArgumentParser(description="Concatenate video files")
    parser.add_argument(
        "input_directory", help="Directory containing input video files"
    )
    parser.add_argument("--output", required=False, help="Output file name")
    parser.add_argument(
        "--option",
        choices=["1080p", "720p", "dynamic"],
        default="dynamic",
        help="Output option",
    )
    parser.add_argument(
        "--extensions",
        default="mp4,avi,mov,mkv",
        help="Comma-separated list of video file extensions to process (default: mp4,avi,mov,mkv)",
    )
    parser.add_argument("--info", action="store_true", help="Show information about video files in the directory")

    parser.add_argument("--sort", choices=['bitrate', 'split', 'orientation'], help="Sort videos by bitrate or split into folders")
    parser.add_argument("--max-files", help="Amount of files in forder when splitting", type=int)

    args = parser.parse_args()

    if args.info:
        print("Analyzing video files...")
        video_info, summary = get_video_info(args.input_directory)
        
        print("\nVideo File Information:")
        for info in video_info:
            print(f"File: {info['file']}")
            print(f"  Duration: {format_duration(info['duration'])}")
            print(f"  Size: {format_size(info['size'])}")
            print(f"  Bitrate: {format_bitrate(info['bitrate'])}")
            print(f"  Resolution: {info['resolution']}")
            print()
        
        print("Summary:")
        print(f"Total videos: {summary['total_videos']}")
        print(f"Total duration: {format_duration(summary['total_duration'])}")
        print(f"Total size: {format_size(summary['total_size'])}")
        print(f"Average bitrate: {format_bitrate(summary['avg_bitrate'])}")
        print(f"Minimum bitrate: {format_bitrate(summary['min_bitrate'])}")
        print(f"Maximum bitrate: {format_bitrate(summary['max_bitrate'])}")
        print("Resolutions:")
        for resolution, count in summary['resolutions'].items():
            print(f"  {resolution}: {count}")
        return

    if args.sort == 'bitrate':
        print("Sorting videos by bitrate...")
        sort_videos_by_bitrate(args.input_directory)
        print("Sorting complete. Videos are now sorted into 'high', 'medium', and 'low' bitrate folders.")
    elif args.sort == 'split':
        if args.max_files:
            max_files = args.max_files
        else:
            max_files = 100
        print(f"Splitting files into folders with {max_files} files per folder...")
        split_files_into_folders(args.input_directory, max_files)
        print("Splitting complete.")
    elif args.sort == 'orientation':
        print("Sorting videos by orientation...")
        sort_videos_by_orientation(args.input_directory)
        print("Sorting complete. Videos are now in 'horizontal' and 'vertical' subdirectories.")
        return

    # Get list of video files in the input directory
    extensions = args.extensions.split(",")
    input_files = []
    for ext in extensions:
        input_files.extend(glob.glob(os.path.join(args.input_directory, f"*.{ext}")))

    if not input_files:
        print(
            f"No video files found in {args.input_directory} with extensions: {args.extensions}"
        )
        return

    input_files.sort()  # Sort files alphabetically

    print(f"Found {len(input_files)} video files to process.")

    try:
        with tqdm(total=3, desc="Overall progress") as pbar:
            concatenator = VideoConcatenator(input_files, args.option, args.output)
            pbar.update(1)
            concatenator.process()
            pbar.update(1)
            print(f"Concatenated video saved as {args.output}")
            pbar.update(1)
    except Exception as e:
        print(f"Error: {str(e)}")
    finally:
        cleanup_temp_directory()


if __name__ == "__main__":
    main()
