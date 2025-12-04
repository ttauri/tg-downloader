import time
from typing import Optional

from webapp import schemas
from webapp.config import settings
from webapp.services.helper_functions import sanitize_dirname
from webapp.services.storage_service import ensure_unsorted_folder
from webapp.services.task_manager import Task, TaskStatus, CancelledError
from webapp.crud import create_media, get_channel_by_id, get_all_not_downloaded_media, find_downloaded_by_file_id
from webapp.database import SessionLocal
from webapp.telegram_client import client, download_media_from_message
from webapp.logging_conf import logger


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

    # Download to _unsorted subfolder to avoid conflicts with classifier
    download_path = ensure_unsorted_folder(channel.channel_name)
    logger.info(f"Download path: {download_path}")

    media = get_all_not_downloaded_media(db, channel_id, order=sorting_type)

    try:
        async with client:
            total = media.count()
            if task:
                await task.update(current=0, total=total, status=TaskStatus.RUNNING, message="Starting download...")

            skipped = 0
            for i, m in enumerate(media, start=1):
                if task and task.is_cancelled:
                    await task.set_cancelled(f"Stopped after {i-1}/{total} files")
                    return

                # Check if this file was already downloaded (same tg_file_id)
                if m.tg_file_id:
                    existing = find_downloaded_by_file_id(db, channel_id, m.tg_file_id)
                    if existing:
                        # Mark as duplicate, skip download
                        m.duplicate_of_id = existing.id
                        m.is_downloaded = False
                        db.commit()
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
                    # Check for cancellation during download
                    if task and task.is_cancelled:
                        raise CancelledError("Download cancelled by user")

                    now = time.time()
                    # Throttle updates to max 2 per second
                    if now - last_update_time[0] < 0.5:
                        return
                    last_update_time[0] = now

                    elapsed = now - download_start_time
                    speed = current_bytes / elapsed if elapsed > 0 else 0
                    speed_str = format_speed(speed)

                    current_formatted = format_size(current_bytes)
                    total_formatted = format_size(total_bytes)
                    pct = round(current_bytes / total_bytes * 100) if total_bytes > 0 else 0

                    msg = f"Downloading {i}/{total}: {current_formatted}/{total_formatted} ({pct}%) @ {speed_str}"

                    if task:
                        await task.update(current=i, total=total, message=msg)

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
                db.commit()
                db.refresh(m)

            if task:
                downloaded = total - skipped
                msg = f"Downloaded {downloaded} files"
                if skipped > 0:
                    msg += f", skipped {skipped} duplicates"
                await task.complete(msg)
    except CancelledError:
        logger.info("Download cancelled by user")
        if task:
            await task.set_cancelled("Download stopped by user")
    except Exception as e:
        logger.error(f"Download failed: {e}")
        if task:
            await task.fail(str(e))
        raise


async def fetch_messages_form_channel(channel_id: str, task: Optional[Task] = None):
    db = SessionLocal()
    try:
        async with client:
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
                    logger.critical(f"Unable to save media, {e}")

            if task:
                await task.complete(f"Fetched {count} media items")
    except CancelledError:
        logger.info("Fetch cancelled by user")
        if task:
            await task.set_cancelled("Fetch stopped by user")
    except Exception as e:
        logger.error(f"Fetch failed: {e}")
        if task:
            await task.fail(str(e))
        raise
