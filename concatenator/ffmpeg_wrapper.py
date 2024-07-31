import subprocess
import json
from .exceptions import FFmpegError
from tqdm import tqdm
import re


class FFmpegWrapper:
    def probe(self, input_file):
        cmd = [
            "ffprobe",
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            input_file,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise FFmpegError(f"FFprobe failed: {result.stderr}")
        return json.loads(result.stdout)

    def check_video(self, input_file):
        cmd = ["ffmpeg", "-v", "error", "-i", input_file, "-f", "null", "-"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        return result.returncode == 0 and not result.stderr

    def resize_pad(
        self,
        input_file,
        output_file,
        width,
        height,
        frame_rate,
        video_bitrate,
        audio_bitrate,
        sample_rate,
    ):
        # Get total number of frames
        probe = self.probe(input_file)
        total_frames = int(probe["streams"][0]["nb_frames"])

        cmd = [
            "ffmpeg",
            "-i",
            input_file,
            "-vf",
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1",
            "-r",
            str(frame_rate),
            "-b:v",
            video_bitrate,
            "-b:a",
            audio_bitrate,
            "-ar",
            str(sample_rate),
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-y",
            output_file,
        ]

        process = subprocess.Popen(cmd, stderr=subprocess.PIPE, universal_newlines=True)

        pbar = tqdm(total=total_frames, unit="frames", desc=f"Processing {input_file}")
        for line in process.stderr:
            if "frame=" in line:
                current_frame = int(line.split("frame=")[1].split()[0])
                pbar.update(current_frame - pbar.n)
        pbar.close()

        # if process.returncode != 0:

        # raise FFmpegError(f"FFmpeg resize_pad failed for {input_file}")

    # def concatenate(self, input_files, output_file, output_params):
    #     input_args = []
    #     for file in input_files:
    #         input_args.extend(['-i', file])
    #
    #     filter_complex = f"concat=n={len(input_files)}:v=1:a=1[outv][outa]"
    #
    #     cmd = [
    #         'ffmpeg',
    #         *input_args,
    #         '-filter_complex', filter_complex,
    #         '-map', '[outv]',
    #         '-map', '[outa]',
    #         '-c:v', 'libx264',
    #         '-c:a', 'aac',
    #         '-b:v', output_params['video_bitrate'],
    #         '-b:a', output_params['audio_bitrate'],
    #         '-r', str(output_params['frame_rate']),
    #         '-ar', str(output_params['sample_rate']),
    #         '-y',
    #         output_file
    #     ]
    #     result = subprocess.run(cmd, capture_output=True, text=True)
    #     if result.returncode != 0:
    #         raise FFmpegError(f"FFmpeg concatenation failed: {result.stderr}")
    def concatenate(self, input_files, output_file, output_params):
        input_args = []
        for file in input_files:
            input_args.extend(["-i", file])

        filter_complex = f"concat=n={len(input_files)}:v=1:a=1[outv][outa]"

        cmd = [
            "ffmpeg",
            *input_args,
            "-filter_complex",
            filter_complex,
            "-map",
            "[outv]",
            "-map",
            "[outa]",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-b:v",
            output_params["video_bitrate"],
            "-b:a",
            output_params["audio_bitrate"],
            "-r",
            str(output_params["frame_rate"]),
            "-ar",
            str(output_params["sample_rate"]),
            "-y",
            output_file,
        ]

        # Get total duration of all input files
        total_duration = sum(
            float(self.probe(f)["format"]["duration"]) for f in input_files
        )

        process = subprocess.Popen(cmd, stderr=subprocess.PIPE, universal_newlines=True)

        pbar = tqdm(total=total_duration, unit="s", desc="Concatenating videos")
        error_message = ""
        for line in process.stderr:
            time_match = re.search(r"time=(\d{2}):(\d{2}):(\d{2}\.\d{2})", line)
            if time_match:
                hours, minutes, seconds = time_match.groups()
                current_time = (
                    float(hours) * 3600 + float(minutes) * 60 + float(seconds)
                )
                pbar.update(current_time - pbar.n)
            elif "Error" in line or "error" in line:
                error_message += line
        pbar.close()

        process.wait()
        if process.returncode != 0:
            raise FFmpegError(f"FFmpeg concatenation failed: {error_message}")
