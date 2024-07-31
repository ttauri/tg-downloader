import subprocess
import json
from .exceptions import FFmpegError
from tqdm import tqdm
import shlex
import re


class FFmpegWrapper:
    def _is_invalid_mp4_error(self, stderr):
        return "moov atom not found" in stderr or "Invalid data found when processing input" in stderr

    def probe(self, input_file):
        cmd = ['ffprobe', '-v', 'error', '-show_format', '-show_streams', '-print_format', 'json', input_file]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return json.loads(result.stdout)
        except subprocess.CalledProcessError as e:
            if self._is_invalid_mp4_error(e.stderr):
                return None  # Indicate an invalid file without raising an exception
            error_message = f"FFprobe failed for {input_file}:\n"
            error_message += f"Command: {' '.join(shlex.quote(arg) for arg in cmd)}\n"
            error_message += f"Return code: {e.returncode}\n"
            error_message += f"Standard output: {e.stdout}\n"
            error_message += f"Standard error: {e.stderr}\n"
            raise FFmpegError(error_message)
        except json.JSONDecodeError as e:
            raise FFmpegError(f"FFprobe output is not valid JSON for {input_file}: {str(e)}")



    def check_video(self, input_file):
        cmd = ['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-count_packets', 
               '-show_entries', 'stream=nb_read_packets', '-of', 'csv=p=0', input_file]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return int(result.stdout.strip()) > 0
        except subprocess.CalledProcessError as e:
            if self._is_invalid_mp4_error(e.stderr):
                return False
            error_message = f"Video check failed for {input_file}:\n"
            error_message += f"Command: {' '.join(shlex.quote(arg) for arg in cmd)}\n"
            error_message += f"Return code: {e.returncode}\n"
            error_message += f"Standard output: {e.stdout}\n"
            error_message += f"Standard error: {e.stderr}\n"
            raise FFmpegError(error_message)
        except ValueError:
            return False

    def resize_pad(self, input_file, output_file, width, height, frame_rate, video_bitrate, audio_bitrate, sample_rate):
        probe = self.probe(input_file)
        if probe is None:
            raise FFmpegError(f"Unable to probe file: {input_file}. The file may be corrupted or invalid.")

        # Check if the input file has an audio stream
        has_audio = any(stream['codec_type'] == 'audio' for stream in probe['streams'])

        cmd = [
            'ffmpeg',
            '-i', input_file,
        ]

        if not has_audio:
            # Add silent audio input
            cmd.extend([
                '-f', 'lavfi',
                '-i', 'anullsrc=channel_layout=stereo:sample_rate=44100'
            ])

        cmd.extend([
            '-filter_complex', f'[0:v]scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1[v]',
            '-map', '[v]',
            '-map', '0:a' if has_audio else '1:a',
            '-c:v', 'libx264',
            '-r', str(frame_rate),
            '-b:v', video_bitrate,
            '-c:a', 'aac',
            '-b:a', audio_bitrate,
            '-ar', str(sample_rate),
            '-shortest',
            '-y',
            output_file
        ])

        process = subprocess.Popen(cmd, stderr=subprocess.PIPE, universal_newlines=True)
        
        error_output = ""
        for line in process.stderr:
            error_output += line
            print(line, end='')  # Print FFmpeg output in real-time

        process.wait()
        if process.returncode != 0:
            raise FFmpegError(f"FFmpeg resize_pad failed for {input_file}. Error output:\n{error_output}")



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

        process = subprocess.Popen(cmd, stderr=subprocess.PIPE, universal_newlines=True)
        
        error_output = ""
        for line in process.stderr:
            error_output += line
            print(line, end='')  # Print FFmpeg output in real-time

        process.wait()
        if process.returncode != 0:
            raise FFmpegError(f"FFmpeg concatenation failed: {error_output}")


