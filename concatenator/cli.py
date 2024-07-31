import argparse
import sys
import os
import glob

# Add the parent directory of 'concatenator' to the Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, parent_dir)

from concatenator.core import VideoConcatenator

def main():
    parser = argparse.ArgumentParser(description="Concatenate video files")
    parser.add_argument("input_directory", help="Directory containing input video files")
    parser.add_argument("--output", required=True, help="Output file name")
    parser.add_argument("--option", choices=['1080p', '720p', 'dynamic'], default='dynamic', help="Output option")
    parser.add_argument("--extensions", default="mp4,avi,mov,mkv", help="Comma-separated list of video file extensions to process (default: mp4,avi,mov,mkv)")
    
    args = parser.parse_args()
    
    # Get list of video files in the input directory
    extensions = args.extensions.split(',')
    input_files = []
    for ext in extensions:
        input_files.extend(glob.glob(os.path.join(args.input_directory, f"*.{ext}")))
    
    if not input_files:
        print(f"No video files found in {args.input_directory} with extensions: {args.extensions}")
        return

    input_files.sort()  # Sort files alphabetically

    print(f"Found {len(input_files)} video files to process.")
    

    concatenator = VideoConcatenator(input_files, args.option, args.output)
    concatenator.process()
    print(f"Concatenated video saved as {args.output}")

if __name__ == "__main__":
    main()
