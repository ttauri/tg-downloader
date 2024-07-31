from .utils import (
    analyze_videos,
    determine_output_resolution,
    determine_output_bit_rate,
    normalize_video,
    create_temp_directory,
    cleanup_temp_directory,
)
from tqdm import tqdm
from .config import OUTPUT_OPTIONS
from .exceptions import VideoProcessingError, FFmpegError
from .ffmpeg_wrapper import FFmpegWrapper
import traceback


class VideoConcatenator:
    def __init__(self, input_files, output_option, output_file):
        self.input_files = input_files
        self.output_option = output_option
        self.output_file = output_file
        self.ffmpeg = FFmpegWrapper()
        self.temp_dir = None

    def process(self):
        try:
            self.temp_dir = create_temp_directory()
            valid_input_files = self._check_input_files()
            if not valid_input_files:
                raise VideoProcessingError("No valid input files found")

            video_info = analyze_videos(valid_input_files)
            print("Analyzing videos")
            print(video_info)
            if not video_info:
                raise VideoProcessingError(
                    "No valid video streams found in input files"
                )

            output_resolution = determine_output_resolution(
                video_info, self.output_option
            )
            output_bitrate = determine_output_bit_rate(video_info, self.output_option)
            print(f"Output resolution: {output_resolution}")

            if self.output_option == "dynamic":
                width, height = map(int, output_resolution.split("x"))
                output_params = {
                    "width": width,
                    "height": height,
                    "frame_rate": OUTPUT_OPTIONS["dynamic"]["frame_rate"],
                    # "video_bitrate": f"{width * height // 1000}k",  # Adjust bitrate based on resolution
                    "video_bitrate": output_bitrate,
                    "audio_bitrate": OUTPUT_OPTIONS["dynamic"]["audio_bitrate"],
                    "sample_rate": OUTPUT_OPTIONS["dynamic"]["sample_rate"],
                }
            else:
                output_params = OUTPUT_OPTIONS[self.output_option]
            print(f"Output params: {output_params}")

            normalized_files = self._normalize_videos(video_info, output_params)
            if not normalized_files:
                raise VideoProcessingError("No videos were successfully normalized")

            print(f"Concatenating {len(normalized_files)} normalized videos...")
            self._concatenate_videos(normalized_files, output_params)
        except Exception as e:
            raise VideoProcessingError(f"Error processing videos: {str(e)}")
        finally:
            if self.temp_dir:
                cleanup_temp_directory()

    def _check_input_files(self):
        valid_files = []
        for input_file in tqdm(self.input_files, desc="Checking input files"):
            try:
                if self.ffmpeg.check_video(input_file):
                    valid_files.append(input_file)
                else:
                    print(f"Warning: Skipping corrupted or invalid file: {input_file}")
            except FFmpegError as e:
                print(f"Error checking file {input_file}: {str(e)}")
        return valid_files

    def _normalize_videos(self, video_info, output_params):
        normalized_files = []
        failed_files = []
        for input_file in tqdm(video_info, desc="Normalizing videos"):
            try:
                normalized_file = normalize_video(
                    input_file["file"], output_params, self.ffmpeg
                )
                if normalized_file:
                    normalized_files.append(normalized_file)
                else:
                    failed_files.append(input_file["file"])
            except Exception as e:
                print(f"Unexpected error normalizing {input_file['file']}:")
                print(str(e))
                failed_files.append(input_file["file"])

        if failed_files:
            print(f"Warning: Failed to normalize {len(failed_files)} file(s):")
            for file in failed_files:
                print(f"  - {file}")

        if not normalized_files:
            raise VideoProcessingError(
                "All video normalizations failed. Please check the error messages above for details."
            )

        return normalized_files

    def _concatenate_videos(self, normalized_files, output_params):
        try:
            print("Concatenating videos...")
            self.ffmpeg.concatenate(normalized_files, self.output_file, output_params)
        except FFmpegError as e:
            print(f"Error during video concatenation:")
            print(str(e))
            raise VideoProcessingError(
                "Video concatenation failed. Please check the error messages above for details."
            )
