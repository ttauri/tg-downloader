import asyncio
import json
import time
from typing import Optional

from webapp import schemas
from webapp.config import settings
from webapp.services.helper_functions import sanitize_dirname
from webapp.services.storage_service import ensure_unsorted_folder
from webapp.services.task_manager import Task, TaskStatus, CancelledError
from webapp.crud import create_media, get_channel_by_id, get_all_not_downloaded_media, find_downloaded_by_file_id
from webapp.database import SessionLocal
from webapp.telegram_client import client, download_media_from_message, ensure_client_connected
from webapp.logging_conf import logger


def should_download_media(media, options: dict) -> tuple[bool, str]:
    """
    Check if media should be downloaded based on channel options.
    Returns (should_download, skip_reason).
    """
    if not options:
        return True, ""

    # Check media type
    media_type = media.media_type or ""
    if media_type.startswith('video') and not options.get('type_video', True):
        return False, "video type disabled"
    if media_type.startswith('image') and not options.get('type_image', True):
        return False, "image type disabled"
    if media_type.startswith('audio') and not options.get('type_audio', True):
        return False, "audio type disabled"
    if not media_type.startswith(('video', 'image', 'audio')) and not options.get('type_other', True):
        return False, "other type disabled"

    # Check resolution (for videos with height info)
    if media.height:
        h = media.height
        if h <= 360 and not options.get('res_360p', True):
            return False, "360p disabled"
        elif 360 < h <= 480 and not options.get('res_480p', True):
            return False, "480p disabled"
        elif 480 < h <= 720 and not options.get('res_720p', True):
            return False, "720p disabled"
        elif 720 < h <= 1080 and not options.get('res_1080p', True):
            return False, "1080p disabled"
        elif 1080 < h <= 1440 and not options.get('res_1440p', True):
            return False, "1440p disabled"
        elif h > 1440 and not options.get('res_4k', True):
            return False, "4K disabled"

    # Check duration (for videos with duration info)
    if media.duration:
        d = media.duration
        if d < 30 and not options.get('dur_30s', True):
            return False, "under 30s disabled"
        elif 30 <= d < 60 and not options.get('dur_1m', True):
            return False, "30s-1m disabled"
        elif 60 <= d < 300 and not options.get('dur_5m', True):
            return False, "1-5m disabled"
        elif 300 <= d < 900 and not options.get('dur_15m', True):
            return False, "5-15m disabled"
        elif 900 <= d < 1800 and not options.get('dur_30m', True):
            return False, "15-30m disabled"
        elif 1800 <= d < 3600 and not options.get('dur_1h', True):
            return False, "30m-1h disabled"
        elif d >= 3600 and not options.get('dur_long', True):
            return False, "over 1h disabled"

    return True, ""


def _db_commit_and_refresh(db, obj):
    """Synchronous DB commit and refresh - to be run in thread pool."""
    db.commit()
    db.refresh(obj)


def _db_commit(db):
    """Synchronous DB commit - to be run in thread pool."""
    db.commit()


def format_speed(bytes_per_second):
    """Format download speed to human readable string."""
    if bytes_per_second < 1024:
        return f"{bytes_per_second:.0f} B/s"
    elif bytes_per_second < 1024 * 1024:
        return f"{bytes_per_second / 1024:.1f} KB/s"
    else:
        return f"{bytes_per_second / (1024 * 1024):.2f} MB/s"


def format_size(size_bytes):
    """Format size in bytes to human readable string."""
    if size_bytes < 1024:
        return f"{size_bytes:.0f} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.2f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


async def download_media_from_channel(channel_id: int, task: Optional[Task] = None):
    db = SessionLocal()
    sorting_type = settings.sorting_type
    logger.info(f"Using {sorting_type} sorting for channel media")
    channel = get_channel_by_id(db=db, channel_id=channel_id)

    # Load download options for this channel
    download_options = {}
    if channel.download_options:
        try:
            download_options = json.loads(channel.download_options)
            logger.info(f"Loaded download options: {download_options}")
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse download_options: {channel.download_options}")
    else:
        logger.info("No download options set for channel, downloading all")

    # Download to _unsorted subfolder to avoid conflicts with classifier
    download_path = ensure_unsorted_folder(channel.channel_name)
    logger.info(f"Download path: {download_path}")

    media = get_all_not_downloaded_media(db, channel_id, order=sorting_type)

    try:
        await ensure_client_connected()
        total = media.count()
        if task:
            await task.update(current=0, total=total, status=TaskStatus.RUNNING, message="Starting download...")

        skipped = 0
        filtered = 0
        stop_after_current = False
        for i, m in enumerate(media, start=1):
            # Check if previous file set the stop flag (cancellation requested during download)
            if stop_after_current:
                downloaded = i - 1 - skipped - filtered
                logger.info(f"Stopping before file {i}/{total}")
                if task:
                    await task.set_cancelled(f"Stopped after {downloaded} files downloaded")
                return

            # Check download options filter
            should_dl, skip_reason = should_download_media(m, download_options)
            if not should_dl:
                filtered += 1
                logger.info(f"Filtered {i}/{total}: {skip_reason} (duration={m.duration}, height={m.height})")
                if task:
                    await task.update(current=i, total=total,
                                      message=f"Skipped: {skip_reason}")
                continue

            # Check if this file was already downloaded (same tg_file_id)
            if m.tg_file_id:
                existing = find_downloaded_by_file_id(db, channel_id, m.tg_file_id)
                if existing:
                    # Mark as duplicate, skip download
                    m.duplicate_of_id = existing.id
                    m.is_downloaded = False
                    await asyncio.to_thread(_db_commit, db)
                    skipped += 1
                    logger.info(f"Skipped duplicate {i}/{total}: same file as {existing.filename}")
                    if task:
                        await task.update(current=i, total=total,
                                          message=f"Skipped duplicate {i}/{total}")
                    continue

            message = await client.get_messages(int(channel_id), ids=m.tg_message_id)
            file_size = m.size or 0
            size_formatted = format_size(file_size)
            logger.info(f"Downloading media {i} of {total} ID:{m.id}, Size:{size_formatted}")

            # Progress tracking for current file
            download_start_time = time.time()
            last_update_time = [download_start_time]  # Use list to allow mutation in callback

            async def progress_callback(current_bytes, total_bytes):
                nonlocal stop_after_current

                # Always check for cancellation (don't throttle this check)
                if task and task.is_cancelled:
                    stop_after_current = True

                now = time.time()
                # Throttle UI updates to max 2 per second
                if now - last_update_time[0] < 0.5:
                    return
                last_update_time[0] = now

                elapsed = now - download_start_time
                speed = current_bytes / elapsed if elapsed > 0 else 0
                speed_str = format_speed(speed)

                current_formatted = format_size(current_bytes)
                total_formatted = format_size(total_bytes)
                file_pct = round(current_bytes / total_bytes * 100) if total_bytes > 0 else 0

                # Show appropriate message based on cancellation state
                if stop_after_current:
                    msg = f"Finishing {i}/{total}: {current_formatted}/{total_formatted} ({file_pct}%) - stopping after this file..."
                else:
                    msg = f"Downloading {i}/{total}: {current_formatted}/{total_formatted} ({file_pct}%) @ {speed_str}"

                if task:
                    # Don't raise CancelledError - we want to finish the current file
                    await task.update(current=i, total=total, message=msg, file_progress=file_pct, check_cancelled=False)

            if task:
                await task.update(current=i, total=total, message=f"Starting {i}/{total}: {size_formatted}")

            media_path = await download_media_from_message(
                message, download_path,
                progress_callback=progress_callback
            )
            filename = media_path.split("/")[-1]
            logger.info(f"{media_path} finished. Filename: {filename}")
            m.is_downloaded = True
            m.filename = filename
            await asyncio.to_thread(_db_commit_and_refresh, db, m)

            # Check if cancellation was requested during this download
            if stop_after_current:
                downloaded = i - skipped - filtered
                logger.info(f"Stopping after completing file {i}/{total}")
                if task:
                    await task.set_cancelled(f"Stopped after {downloaded} files downloaded")
                return

        if task:
            downloaded = total - skipped - filtered
            msg = f"Downloaded {downloaded} files"
            if skipped > 0:
                msg += f", {skipped} duplicates"
            if filtered > 0:
                msg += f", {filtered} filtered"
            await task.complete(msg)
    except CancelledError:
        logger.info("Download cancelled by user")
        if task:
            await task.set_cancelled("Download stopped by user")
    except asyncio.CancelledError:
        # This can happen when switching channels or closing the browser
        logger.info("Download interrupted (asyncio cancelled)")
        if task:
            await task.set_cancelled("Download interrupted")
    except Exception as e:
        logger.exception(f"Download failed: {e}")
        if task:
            await task.fail(str(e))
        raise


async def fetch_messages_form_channel(channel_id: str, task: Optional[Task] = None):
    db = SessionLocal()
    try:
        await ensure_client_connected()
        tg_channel = await client.get_entity(int(channel_id))

        if task:
            await task.update(status=TaskStatus.RUNNING, message="Fetching messages...")

        count = 0
        async for message in client.iter_messages(tg_channel):
            if task and task.is_cancelled:
                await task.set_cancelled(f"Stopped after {count} items")
                return

            if not message.media or not message.document:
                continue
            try:
                # Extract file metadata
                file_obj = message.file
                duration = None
                width = None
                height = None
                original_filename = None

                if file_obj:
                    # Convert duration to int (Telegram returns float)
                    duration = int(file_obj.duration) if file_obj.duration else None
                    width = file_obj.width
                    height = file_obj.height
                    original_filename = file_obj.name

                new_media = schemas.MediaCreate(
                    tg_channel_id=channel_id,
                    tg_message_id=message.id,
                    media_type=message.document.mime_type,
                    size=message.document.size,
                    is_downloaded=False,
                    filename="",
                    # New fields
                    tg_file_id=message.document.id,
                    original_filename=original_filename,
                    duration=duration,
                    width=width,
                    height=height,
                    message_date=message.date,
                    caption=message.text or None,
                )
                create_media(db=db, media=new_media)
                count += 1
                logger.info(f'Media record created ID:{new_media.tg_message_id} TYPE:{new_media.media_type} FILE_ID:{new_media.tg_file_id}')

                if task and count % 10 == 0:
                    await task.update(current=count, message=f"Fetched {count} media items...")
            except BaseException as e:
                logger.exception(f"Unable to save media: {e}")

        if task:
            await task.complete(f"Fetched {count} media items")
    except CancelledError:
        logger.info("Fetch cancelled by user")
        if task:
            await task.set_cancelled("Fetch stopped by user")
    except asyncio.CancelledError:
        logger.info("Fetch interrupted (asyncio cancelled)")
        if task:
            await task.set_cancelled("Fetch interrupted")
    except Exception as e:
        logger.exception(f"Fetch failed: {e}")
        if task:
            await task.fail(str(e))
        raise
