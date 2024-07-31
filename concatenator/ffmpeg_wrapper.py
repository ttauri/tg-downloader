import subprocess
import json
from .exceptions import FFmpegError

class FFmpegWrapper:
    def probe(self, input_file):
        cmd = ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', '-show_streams', input_file]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise FFmpegError(f"FFprobe failed: {result.stderr}")
        return json.loads(result.stdout)

    def resize_pad(self, input_file, output_file, width, height, frame_rate, video_bitrate, audio_bitrate, sample_rate):
        cmd = [
            'ffmpeg', '-i', input_file,
            '-vf', f'scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1',
            '-r', str(frame_rate),
            '-b:v', video_bitrate,
            '-b:a', audio_bitrate,
            '-ar', str(sample_rate),
            '-c:v', 'libx264',
            '-c:a', 'aac',
            '-y',
            output_file
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise FFmpegError(f"FFmpeg resize_pad failed: {result.stderr}")

    def concatenate(self, input_files, output_file, output_params):
        input_args = []
        for file in input_files:
            input_args.extend(['-i', file])
        
        filter_complex = f"concat=n={len(input_files)}:v=1:a=1[outv][outa]"
        
        cmd = [
            'ffmpeg',
            *input_args,
            '-filter_complex', filter_complex,
            '-map', '[outv]',
            '-map', '[outa]',
            '-c:v', 'libx264',
            '-c:a', 'aac',
            '-b:v', output_params['video_bitrate'],
            '-b:a', output_params['audio_bitrate'],
            '-r', str(output_params['frame_rate']),
            '-ar', str(output_params['sample_rate']),
            '-y',
            output_file
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise FFmpegError(f"FFmpeg concatenation failed: {result.stderr}")