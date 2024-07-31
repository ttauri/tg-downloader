import os
from .ffmpeg_wrapper import FFmpegWrapper
from .exceptions import FFmpegError
import shutil
import tempfile

# Add these at the top of the file
temp_dir = None


def analyze_videos(input_files):
    ffmpeg = FFmpegWrapper()
    video_info = []
    for input_file in input_files:
        info = ffmpeg.probe(input_file)
        if info is None:
            print(f"Warning: Skipping invalid or corrupted file: {input_file}")
            print("       This file may be incomplete or have a missing moov atom.")
            continue
        video_stream = next((stream for stream in info['streams'] if stream['codec_type'] == 'video'), None)
        if video_stream:
            video_info.append({
                'file': input_file,
                'width': int(video_stream['width']),
                'height': int(video_stream['height']),
                'bit_rate': int(video_stream['bit_rate']),
                'duration': float(video_stream['duration'])
            })
    return video_info


def average_resolution_16_9(resolutions):
    # Calculate average width and height
    total_width = sum(res[0] for res in resolutions)
    total_height = sum(res[1] for res in resolutions)
    count = len(resolutions)
    avg_width = total_width // count
    avg_height = total_height // count
    # Transform to 16:9
    if avg_width / avg_height > 16 / 9:
        # Width is larger relative to height, so we'll keep width and increase height
        new_height = (avg_width * 9) // 16
        new_width = avg_width
    else:
        # Height is larger relative to width, so we'll keep height and increase width
        new_width = (avg_height * 16) // 9
        new_height = avg_height
    # Ensure even numbers
    new_width = (new_width + 1) & ~1
    new_height = (new_height + 1) & ~1
    return new_width, new_height


def transform_to_16_9(width, height):
    # Calculate the target width for 16:9 aspect ratio
    target_width = (height * 16) // 9
    # Round to the nearest multiple of 2 for even dimensions
    target_width = (target_width + 1) & ~1
    return target_width, height


def determine_output_bit_rate(video_info, target_option):
    if target_option == 'dynamic':
        # mbr = max([br['bit_rate'] for br in video_info])
        # print(f"Max bit rate: {mbr}")
        # return mbr

        total_weighted_bitrate = sum(vid['bit_rate'] * vid['duration'] for vid in video_info)
        max_bitrate = sum([vid['bit_rate'] for vid in video_info])
        print(f"Max bitrate {max_bitrate}")
        total_duration = sum([vid['duration'] for vid in video_info])
        weighted_average_bitrate = total_weighted_bitrate / total_duration
        print(f"Weighted average bitrate: {weighted_average_bitrate}")
        return weighted_average_bitrate


def determine_output_resolution(video_info, target_option):
    max_width = max(info["width"] for info in video_info)
    print(f"Max video width is {max_width}")
    max_height = max(info["height"] for info in video_info)
    print(f"Max video height is {max_height}")

    if target_option in ["1080p", "720p"]:
        return target_option

    # elif target_option == "dynamic":
    #     res = transform_to_16_9(max_width, max_height)
    #     return f"{res[0]}x{res[1]}"

    elif target_option == "dynamic":
        return f"{max_width}x{max_height}"

    elif target_option == "average":
        resolutions = [[info['width'], info['height']] for info in video_info]
        avg = average_resolution_16_9(resolutions)
        print(avg)
        return f"{avg[0]}x{avg[1]}"

    elif target_option == "dynamic_old":
        # For dynamic option
        max_width = max(info["width"] for info in video_info)
        print(f"Max video width is {max_width}")
        max_height = max(info["height"] for info in video_info)
        print(f"Max video height is {max_height}")

        # Define standard 16:9 resolutions
        standard_resolutions = [(1920, 1080), (1280, 720), (854, 480), (640, 360)]

        # Find the smallest standard resolution that's larger than or equal to both max dimensions
        for width, height in standard_resolutions:
            if (
                width >= max_width
                and width >= max_height
                and height >= max_width
                and height >= max_height
            ):
                return f"{width}x{height}"

        # If all videos are larger than the largest standard resolution, use the largest
        return f"{standard_resolutions[0][0]}x{standard_resolutions[0][1]}"



def normalize_video(input_file, output_params, ffmpeg):
    global temp_dir
    if not temp_dir:
        raise ValueError("Temporary directory not created. Call create_temp_directory() first.")
    
    base_name = os.path.splitext(os.path.basename(input_file))[0]
    output_file = os.path.join(temp_dir, f"normalized_{base_name}.mp4")
    
    try:
        print(f"Normalizing video: {input_file}")
        print(f"Output file: {output_file}")
        ffmpeg.resize_pad(
            input_file,
            output_file,
            width=output_params['width'],
            height=output_params['height'],
            frame_rate=output_params['frame_rate'],
            video_bitrate=output_params['video_bitrate'],
            audio_bitrate=output_params['audio_bitrate'],
            sample_rate=output_params['sample_rate']
        )
        return output_file
    except FFmpegError as e:
        print(f"Error normalizing video {input_file}:")
        print(str(e))
        return None

def create_temp_directory():
    global temp_dir
    temp_dir = tempfile.mkdtemp(prefix="video_concatenator_")
    return temp_dir


def cleanup_temp_directory():
    global temp_dir
    if temp_dir and os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)
    temp_dir = None


def sort_videos_by_orientation(input_directory):
    ffmpeg = FFmpegWrapper()
    
    # Create directories for horizontal and vertical videos
    horizontal_dir = os.path.join(input_directory, 'horizontal')
    vertical_dir = os.path.join(input_directory, 'vertical')
    os.makedirs(horizontal_dir, exist_ok=True)
    os.makedirs(vertical_dir, exist_ok=True)

    # Get all video files in the input directory
    video_extensions = ('.mp4', '.avi', '.mov', '.mkv', '.flv', '.wmv')
    video_files = [f for f in os.listdir(input_directory) if f.lower().endswith(video_extensions)]

    for video_file in video_files:
        input_path = os.path.join(input_directory, video_file)
        try:
            # Probe the video to get its dimensions
            probe = ffmpeg.probe(input_path)
            video_stream = next((stream for stream in probe['streams'] if stream['codec_type'] == 'video'), None)
            
            if video_stream:
                width = int(video_stream['width'])
                height = int(video_stream['height'])
                
                # Determine orientation and move the file
                if width >= height:
                    destination = os.path.join(horizontal_dir, video_file)
                else:
                    destination = os.path.join(vertical_dir, video_file)
                
                shutil.move(input_path, destination)
                print(f"Moved {video_file} to {'horizontal' if width >= height else 'vertical'} folder")
            else:
                print(f"Warning: No video stream found in {video_file}")
        except Exception as e:
            print(f"Error processing {video_file}: {str(e)}")

    # Print summary
    horizontal_count = len(os.listdir(horizontal_dir))
    vertical_count = len(os.listdir(vertical_dir))
    print(f"\nSorting complete:")
    print(f"Horizontal videos: {horizontal_count}")
    print(f"Vertical videos: {vertical_count}")
