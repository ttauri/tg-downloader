import os

from app import schemas
from app.config import settings
from app.crud import (
    create_media,
    get_subscribed_channels,
    get_all_not_downloaded_media,
)
from app.database import SessionLocal
from app.telegram_client import client, download_media_from_message, fetch_channel_media
from app.logging_conf import logger


async def check_for_new_messages():
    print("QUerying MESSAGES")
    async with client:
        db = SessionLocal()
        channels = get_subscribed_channels(db)
        for channel in channels:
            async for message in fetch_channel_media(channel.channel_id):
                media_path = await download_media_from_message(
                    message, settings.media_download_path
                )
                if media_path:
                    media_size = os.path.getsize(media_path) / (1024 * 1024)
                    media_type = "img" if "image" in media_path else "video"
                    new_media = schemas.MediaCreate(
                        tg_message_id=message.id,
                        tg_channel_id=channel.id,
                        media_type=media_type,
                        download_link=media_path,
                        size=media_size,
                        is_downloaded=True,
                        channel_id=channel.channel_id,
                    )
                    print(new_media)
                    create_media(db=db, media=new_media)


async def download_media_from_channel(channel_id: int):
    db = SessionLocal()
    sorting_type = config.sorting_type
    logger.info(f"Using {sorting_type} sorting")
    media = get_all_not_downloaded_media(db, channel_id, order="large")
    async with client:
        for m in media:
            message = await client.get_messages(int(channel_id), ids=m.tg_message_id)
            logger.info(f"Downloading media {m.id}, size:{m.size / (1024 * 1024)}MB")
            media_path = await download_media_from_message(
                message, f"{settings.media_download_path}/{str(m.tg_channel_id)[4:]}/"
            )
            filename = media_path.split("/")[-1]
            logger.info(f"{media_path} finished. Filename: {filename}")
            m.is_downloaded = True
            m.filename = filename
            db.commit()
            db.refresh(m)


async def fetch_messages_form_channel(channel_id: str):
    db = SessionLocal()
    async with client:
        # Get the channel entity
        tg_channel = await client.get_entity(int(channel_id))

        # Fetch messages
        async for message in client.iter_messages(tg_channel):
            if not message.media or not message.document:
                continue
            try:
                new_media = schemas.MediaCreate(
                    tg_message_id=message.id,
                    tg_channel_id=channel_id,
                    media_type=message.document.mime_type,
                    size=message.document.size,
                    is_downloaded=False,
                )
                print(new_media)
                # logger.info('Media record created')
                create_media(db=db, media=new_media)
            except BaseException as e:
                logger.critical(f"Unable to save media, {e}")
