from .utils import (
    analyze_videos,
    determine_output_resolution,
    normalize_video,
    create_temp_directory,
    cleanup_temp_directory,
)
from tqdm import tqdm
from .config import OUTPUT_OPTIONS
from .exceptions import VideoProcessingError
from .ffmpeg_wrapper import FFmpegWrapper


class VideoConcatenator:
    def __init__(self, input_files, output_option, output_file):
        self.input_files = input_files
        self.output_option = output_option
        self.output_file = output_file
        self.ffmpeg = FFmpegWrapper()

    def process(self):
        try:
            create_temp_directory()
            create_temp_directory()
            valid_input_files = self._check_input_files()
            if not valid_input_files:
                raise VideoProcessingError("No valid input files found")
            video_info = analyze_videos(valid_input_files)
            output_resolution = determine_output_resolution(
                video_info, self.output_option
            )

            if self.output_option == "dynamic":
                width, height = map(int, output_resolution.split("x"))
                output_params = {
                    "width": width,
                    "height": height,
                    "frame_rate": OUTPUT_OPTIONS["dynamic"]["frame_rate"],
                    "video_bitrate": f"{width * height // 1000}k",  # Adjust bitrate based on resolution
                    "audio_bitrate": OUTPUT_OPTIONS["dynamic"]["audio_bitrate"],
                    "sample_rate": OUTPUT_OPTIONS["dynamic"]["sample_rate"],
                }
            else:
                output_params = OUTPUT_OPTIONS[self.output_option]

            normalized_files = self._normalize_videos(video_info, output_params)
            self._concatenate_videos(normalized_files, output_params)
        except Exception as e:
            raise VideoProcessingError(f"Error processing videos: {str(e)}")
        finally:
            cleanup_temp_directory()

    def _check_input_files(self):
        valid_files = []
        for input_file in tqdm(self.input_files, desc="Checking input files"):
            if self.ffmpeg.check_video(input_file):
                valid_files.append(input_file)
            else:
                print(f"Warning: Skipping corrupted or invalid file: {input_file}")
        return valid_files

    def _normalize_videos(self, video_info, output_params):
        normalized_files = []
        for input_file in tqdm(self.input_files, desc="Normalizing videos"):
            normalized_file = normalize_video(input_file, output_params, self.ffmpeg)
            normalized_files.append(normalized_file)
        return normalized_files

    def _concatenate_videos(self, normalized_files, output_params):
        self.ffmpeg.concatenate(normalized_files, self.output_file, output_params)
