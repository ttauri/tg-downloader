import os
import subprocess
import shutil
from tqdm import tqdm


def get_optimal_dimensions(width, height, target_ratio=16 / 9):
    if width / height > target_ratio:
        # Video is wider than 16:9
        new_width = width
        new_height = int(width / target_ratio)
    else:
        # Video is taller than 16:9
        new_height = height
        new_width = int(height * target_ratio)
    return new_width, new_height


def get_video_info(filepath):
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,bit_rate,r_frame_rate",
            "-of",
            "default=noprint_wrappers=1",
            filepath,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        return None
    info = {}
    for line in result.stdout.decode().split("\n"):
        if "=" in line:
            key, value = line.split("=")
            info[key.strip()] = value.strip()
    return info


def check_media_validity(filepath):
    video_result = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", filepath, "-c", "copy", "-f", "null", "-"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if video_result.returncode != 0:
        print(f"Error in file {filepath}:")
        print(video_result.stderr.decode())
        return False
    return True


def process_videos(input_folder, output_file, target_fps=30):
    files = [
        os.path.join(input_folder, f)
        for f in os.listdir(input_folder)
        if f.endswith(".mp4")
    ]
    if not files:
        print("No MP4 files found in the folder.")
        return

    valid_files = []
    max_bitrate = 0
    target_width = 0
    target_height = 0

    for file in files:
        if check_media_validity(file):
            print(f"Probing file {file}")
            valid_files.append(file)
            info = get_video_info(file)
            if info and "bit_rate" in info and int(info["bit_rate"]) > max_bitrate:
                max_bitrate = int(info["bit_rate"])
            video_info = get_video_info(file)
            width = int(video_info["width"])
            if width > target_width:
                target_width = width
            height = int(video_info["height"])
            if height > target_height:
                target_height = height
        else:
            print(f"Skipping damaged file: {file}")

    if not valid_files:
        print("No valid MP4 files to process.")
        return

    target_ratio = 16 / 9

    if (target_width / target_height) != target_ratio:
        target_height = int(target_width / target_ratio)

    concat_list_file = "concat_list.txt"
    with open(concat_list_file, "w") as f:
        for file in valid_files:
            f.write(f"file '{file}'\n")

    temp_folder = "temp_videos"
    os.makedirs(temp_folder, exist_ok=True)
    temp_files = []

    for idx, file in enumerate(tqdm(valid_files, desc="Processing videos")):
        temp_file = os.path.join(temp_folder, f"temp_{idx}.mp4")
        temp_files.append(temp_file)

        video_info = get_video_info(file)
        if not video_info:
            print(f"Skipping file due to error in getting video info: {file}")
            continue

        input_width = int(video_info["width"])
        input_height = int(video_info["height"])
        target_width, target_height = get_optimal_dimensions(input_width, input_height)

        filter_complex = f"scale={target_width}:{target_height}:force_original_aspect_ratio=decrease,pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p"

        try:
            # First, try to process with audio
            subprocess.run(
                [
                    "ffmpeg",
                    "-i",
                    file,
                    "-vf",
                    filter_complex,
                    "-r",
                    str(target_fps),
                    "-c:v",
                    "libx264",
                    "-preset",
                    "fast",
                    "-crf",
                    "18",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "192k",
                    "-y",
                    temp_file,
                ],
                check=True,
                stderr=subprocess.PIPE,
            )
        except subprocess.CalledProcessError as e:
            print(f"Error processing file with audio {file}. Attempting without audio:")
            print(e.stderr.decode())
            try:
                # If that fails, try processing without audio
                subprocess.run(
                    [
                        "ffmpeg",
                        "-i",
                        file,
                        "-vf",
                        filter_complex,
                        "-r",
                        str(target_fps),
                        "-c:v",
                        "libx264",
                        "-preset",
                        "fast",
                        "-crf",
                        "18",
                        "-an",
                        "-y",
                        temp_file,
                    ],
                    check=True,
                    stderr=subprocess.PIPE,
                )
            except subprocess.CalledProcessError as e:
                print(f"Error processing file without audio {file}. Skipping:")
                print(e.stderr.decode())
                continue

    with open(concat_list_file, "w") as f:
        for temp_file in temp_files:
            f.write(f"file '{temp_file}'\n")

    print("Concatenating files...")
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                concat_list_file,
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-af",
                "aresample=async=1000",
                "-vsync",
                "vfr",
                "-max_muxing_queue_size",
                "1024",
                "-shortest",
                output_file,
            ],
            check=True,
            stderr=subprocess.PIPE,
        )
        print("Concatenation complete.")
    except subprocess.CalledProcessError as e:
        print("Error during concatenation:")
        print(e.stderr.decode())

    shutil.rmtree(temp_folder)
    os.remove(concat_list_file)
    print(f"Output file created: {output_file}")


if __name__ == "__main__":
    # input_folder = "media/1158029646"
    input_folder = "media/test"
    output_file = "output.mp4"
    process_videos(input_folder, output_file)
