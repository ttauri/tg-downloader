from .utils import analyze_videos, determine_output_resolution, normalize_video
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
            video_info = analyze_videos(self.input_files)
            output_resolution = determine_output_resolution(video_info, self.output_option)
            
            if self.output_option == 'dynamic':
                width, height = map(int, output_resolution.split('x'))
                output_params = {
                    'width': width,
                    'height': height,
                    'frame_rate': OUTPUT_OPTIONS['dynamic']['frame_rate'],
                    'video_bitrate': f"{width * height // 1000}k",  # Adjust bitrate based on resolution
                    'audio_bitrate': OUTPUT_OPTIONS['dynamic']['audio_bitrate'],
                    'sample_rate': OUTPUT_OPTIONS['dynamic']['sample_rate']
                }
            else:
                output_params = OUTPUT_OPTIONS[self.output_option]

            normalized_files = self._normalize_videos(video_info, output_params)
            self._concatenate_videos(normalized_files, output_params)
        except Exception as e:
            raise VideoProcessingError(f"Error processing videos: {str(e)}")

    def _normalize_videos(self, video_info, output_params):
        normalized_files = []
        for input_file in self.input_files:
            normalized_file = normalize_video(input_file, output_params, self.ffmpeg)
            normalized_files.append(normalized_file)
        return normalized_files

    def _concatenate_videos(self, normalized_files, output_params):
        self.ffmpeg.concatenate(normalized_files, self.output_file, output_params)