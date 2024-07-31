import os
from .ffmpeg_wrapper import FFmpegWrapper


def analyze_videos(input_files):
    ffmpeg = FFmpegWrapper()
    video_info = []
    for input_file in input_files:
        info = ffmpeg.probe(input_file)
        video_stream = next(
            (stream for stream in info["streams"] if stream["codec_type"] == "video"),
            None,
        )
        if video_stream:
            video_info.append(
                {
                    "file": input_file,
                    "width": int(video_stream["width"]),
                    "height": int(video_stream["height"]),
                }
            )
    return video_info


# def determine_output_resolution(video_info, target_option):
#     if target_option in ["1080p", "720p"]:
#         return target_option
#
#     # For dynamic option
#     max_width = max(info["width"] for info in video_info)
#     max_height = max(info["height"] for info in video_info)
#
#     # Define standard 16:9 resolutions
#     standard_resolutions = [
#         (1920, 1080),
#         (1280, 720),
#         (854, 480),
#         (640, 360),
#         (426, 240),
#     ]
#
#     # Find the smallest standard resolution that's larger than or equal to the max input resolution
#     for width, height in standard_resolutions:
#         if width >= max_width and height >= max_height:
#             return f"{width}x{height}"
#
#     # If all videos are smaller than the smallest standard resolution, use the smallest
#     return f"{standard_resolutions[-1][0]}x{standard_resolutions[-1][1]}"


def determine_output_resolution(video_info, target_option):
    if target_option in ["1080p", "720p"]:
        return target_option

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
    base_name = os.path.splitext(os.path.basename(input_file))[0]
    output_file = f"normalized_{base_name}.mp4"

    ffmpeg.resize_pad(
        input_file,
        output_file,
        width=output_params["width"],
        height=output_params["height"],
        frame_rate=output_params["frame_rate"],
        video_bitrate=output_params["video_bitrate"],
        audio_bitrate=output_params["audio_bitrate"],
        sample_rate=output_params["sample_rate"],
    )

    return output_file

