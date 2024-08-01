import os
from .ffmpeg_wrapper import FFmpegWrapper
from .exceptions import FFmpegError
import shutil
import tempfile
import math

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

def percentile(data, p):
    """Calculate the p-th percentile of a list of numbers."""
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * p
    f = int(k)
    c = k - f
    if f + 1 < len(sorted_data):
        return sorted_data[f] * (1 - c) + sorted_data[f + 1] * c
    return sorted_data[f]

def determine_output_bit_rate(video_info, target_option):
    if target_option == 'dynamic':
        bitrates = [vid['bit_rate'] for vid in video_info]
        durations = [vid['duration'] for vid in video_info]
        
        max_bitrate = max(bitrates)
        min_bitrate = min(bitrates)
        
        total_weighted_bitrate = sum(br * dur for br, dur in zip(bitrates, durations))
        total_duration = sum(durations)
        weighted_average_bitrate = total_weighted_bitrate / total_duration

        print('\n'.join(str(x) for x in sorted(bitrates)))
        
        print(f"Max bitrate: {max_bitrate}")
        print(f"Min bitrate: {min_bitrate}")
        print(f"Weighted average bitrate: {weighted_average_bitrate}")
        
        # Option 1: Percentile-based approach (e.g., 75th percentile)
        percentile_75 = percentile(bitrates, 0.75)
        
        # Option 2: Scaling the weighted average
        scale_factor = 2  # Adjust this factor as needed
        scaled_average = weighted_average_bitrate * scale_factor
        
        # Option 3: Using a target range
        target_min = 4_000_000
        target_max = 6_000_000
        
        if scaled_average < target_min:
            final_bitrate = target_min
        elif scaled_average > target_max:
            final_bitrate = target_max
        else:
            final_bitrate = scaled_average
        
        print(f"75th percentile bitrate: {percentile_75}")
        print(f"Scaled average bitrate: {scaled_average}")
        print(f"Final bitrate (within target range): {final_bitrate}")
        
        return percentile_75

# def determine_output_bit_rate(video_info, target_option):
#     if target_option == 'dynamic':
#         # mbr = max([br['bit_rate'] for br in video_info])
#         # print(f"Max bit rate: {mbr}")
#         # return mbr
#
#         total_weighted_bitrate = sum(vid['bit_rate'] * vid['duration'] for vid in video_info)
#         max_bitrate = max([vid['bit_rate'] for vid in video_info])
#         print(f"Max bitrate {max_bitrate}")
#         min_bitrate = min([vid['bit_rate'] for vid in video_info])
#         print(f"Min bitrate {min_bitrate}")
#
#         total_duration = sum([vid['duration'] for vid in video_info])
#         weighted_average_bitrate = total_weighted_bitrate / total_duration
#         print(f"Weighted average bitrate: {weighted_average_bitrate}")
#         return weighted_average_bitrate


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


def sort_videos_by_bitrate(input_directory):
    ffmpeg = FFmpegWrapper()
    
    # Create directories for bitrate categories
    bitrates = ['high', 'medium', 'low']
    for bitrate in bitrates:
        os.makedirs(os.path.join(input_directory, bitrate), exist_ok=True)

    # Get all video files in the input directory
    video_extensions = ('.mp4', '.avi', '.mov', '.mkv', '.flv', '.wmv')
    video_files = [f for f in os.listdir(input_directory) if f.lower().endswith(video_extensions)]

    # First pass: calculate min and max bitrates
    min_bitrate = float('inf')
    max_bitrate = 0
    bitrate_sum = 0
    valid_video_count = 0

    for video_file in video_files:
        input_path = os.path.join(input_directory, video_file)
        try:
            probe = ffmpeg.probe(input_path)
            video_stream = next((stream for stream in probe['streams'] if stream['codec_type'] == 'video'), None)
            
            if video_stream and 'bit_rate' in video_stream:
                bitrate = int(video_stream['bit_rate'])
                min_bitrate = min(min_bitrate, bitrate)
                max_bitrate = max(max_bitrate, bitrate)
                bitrate_sum += bitrate
                valid_video_count += 1
        except Exception as e:
            print(f"Error processing {video_file}: {str(e)}")

    if valid_video_count == 0:
        print("No valid videos found.")
        return

    # Calculate thresholds
    avg_bitrate = bitrate_sum / valid_video_count
    low_threshold = min_bitrate + (avg_bitrate - min_bitrate) / 2
    high_threshold = avg_bitrate + (max_bitrate - avg_bitrate) / 2

    print(f"Max bitrate: {max_bitrate}")
    print(f"Min bitrate: {min_bitrate}")
    print(f"Bitrate thresholds: Low < {low_threshold:.0f}, Medium < {high_threshold:.0f}, High >= {high_threshold:.0f}")

    # Second pass: sort videos
    for video_file in video_files:
        input_path = os.path.join(input_directory, video_file)
        try:
            probe = ffmpeg.probe(input_path)
            video_stream = next((stream for stream in probe['streams'] if stream['codec_type'] == 'video'), None)
            
            if video_stream:
                bitrate = int(video_stream.get('bit_rate', 0))
                
                # Determine bitrate category
                if bitrate >= high_threshold:
                    bitrate_category = 'high'
                elif bitrate >= low_threshold:
                    bitrate_category = 'medium'
                else:
                    bitrate_category = 'low'
                
                # Move the file to the appropriate folder
                destination = os.path.join(input_directory, bitrate_category, video_file)
                shutil.move(input_path, destination)
                print(f"Moved {video_file} to {bitrate_category} folder")
            else:
                print(f"Warning: No video stream found in {video_file}")
        except Exception as e:
            print(f"Error processing {video_file}: {str(e)}")

    # Print summary
    for bitrate in bitrates:
        count = len(os.listdir(os.path.join(input_directory, bitrate)))
        print(f"{bitrate.capitalize()} bitrate videos: {count}")

def split_files_into_folders(input_directory, files_per_folder=100):
    # Get all video files in the input directory
    video_extensions = ('.mp4', '.avi', '.mov', '.mkv', '.flv', '.wmv')
    video_files = [f for f in os.listdir(input_directory) if f.lower().endswith(video_extensions)]
    
    total_files = len(video_files)
    
    if total_files <= files_per_folder:
        print(f"Total files ({total_files}) is not more than {files_per_folder}. No splitting required.")
        return
    
    num_folders = math.ceil(total_files / files_per_folder)
    
    for i in range(1, num_folders + 1):
        folder_name = str(i)
        os.makedirs(os.path.join(input_directory, folder_name), exist_ok=True)
    
    for index, video_file in enumerate(video_files):
        source_path = os.path.join(input_directory, video_file)
        folder_number = (index // files_per_folder) + 1
        destination_folder = os.path.join(input_directory, str(folder_number))
        destination_path = os.path.join(destination_folder, video_file)
        
        shutil.move(source_path, destination_path)
        print(f"Moved {video_file} to folder {folder_number}")
    
    print(f"Split {total_files} files into {num_folders} folders.")
