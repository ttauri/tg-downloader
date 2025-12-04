from typing import Optional

from app import schemas
from app.config import settings
from app.services.helper_functions import sanitize_dirname
from app.services.task_manager import Task, TaskStatus
from app.crud import create_media, get_channel_by_id, get_all_not_downloaded_media
from app.database import SessionLocal
from app.telegram_client import client, download_media_from_message
from app.logging_conf import logger


async def download_media_from_channel(channel_id: int, task: Optional[Task] = None):
    db = SessionLocal()
    sorting_type = settings.sorting_type
    logger.info(f"Using {sorting_type} sorting fror channel media")
    channel = get_channel_by_id(db=db, channel_id=channel_id)
    channel_folder = sanitize_dirname(channel.channel_name)
    media = get_all_not_downloaded_media(db, channel_id, order=sorting_type)

    try:
        async with client:
            total = media.count()
            if task:
                await task.update(current=0, total=total, status=TaskStatus.RUNNING, message="Starting download...")

            for i, m in enumerate(media, start=1):
                message = await client.get_messages(int(channel_id), ids=m.tg_message_id)
                size_mb = round(m.size / (1024 * 1024), 3)
                msg = f"Downloading {i}/{total}: {size_mb}MB"
                logger.info(f"Downloading media {i} of {total} ID:{m.id}, Size:{size_mb}MB")

                if task:
                    await task.update(current=i, total=total, message=msg)

                media_path = await download_media_from_message(
                    message, f"{settings.media_download_path}/{channel_folder}/"
                )
                filename = media_path.split("/")[-1]
                logger.info(f"{media_path} finished. Filename: {filename}")
                m.is_downloaded = True
                m.filename = filename
                db.commit()
                db.refresh(m)

            if task:
                await task.complete(f"Downloaded {total} files")
    except Exception as e:
        logger.error(f"Download failed: {e}")
        if task:
            await task.fail(str(e))
        raise


async def fetch_messages_form_channel(channel_id: str, task: Optional[Task] = None):
    db = SessionLocal()
    try:
        async with client:
            # Get the channel entity
            tg_channel = await client.get_entity(int(channel_id))

            if task:
                await task.update(status=TaskStatus.RUNNING, message="Fetching messages...")

            count = 0
            # Fetch messages
            async for message in client.iter_messages(tg_channel):
                if not message.media or not message.document:
                    continue
                try:
                    new_media = schemas.MediaCreate(
                        tg_channel_id=channel_id,
                        tg_message_id=message.id,
                        media_type=message.document.mime_type,
                        size=message.document.size,
                        is_downloaded=False,
                        filename="",
                    )
                    create_media(db=db, media=new_media)
                    count += 1
                    logger.info(f'Media record created ID:{new_media.tg_message_id} TYPE:{new_media.media_type}')

                    if task and count % 10 == 0:  # Update every 10 messages
                        await task.update(current=count, message=f"Fetched {count} media items...")
                except BaseException as e:
                    logger.critical(f"Unable to save media, {e}")

            if task:
                await task.complete(f"Fetched {count} media items")
    except Exception as e:
        logger.error(f"Fetch failed: {e}")
        if task:
            await task.fail(str(e))
        raise
