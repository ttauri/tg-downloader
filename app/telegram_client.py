from telethon import TelegramClient
from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument

from .config import settings

client = TelegramClient("session_name", settings.api_id, settings.api_hash)

# Available media types :
# if isinstance(message.media, (MessageMediaPhoto, MessageMediaDocument)):


async def fetch_channels_list():
    await client.start(phone=settings.phone)
    channels = await client.get_dialogs()
    return channels


async def download_media_from_message(message, path, progress_callback=None):
    # For now only videos
    if isinstance(message.media, MessageMediaDocument):
        file_path = await message.download_media(file=path, progress_callback=progress_callback)
        return file_path
    return None


async def fetch_channel_media(channel_id):
    async with client:
        channel = await client.get_entity(int(channel_id))
        async for message in client.iter_messages(channel):
            # async for message in client.iter_messages(channel, filter=lambda m: m.media):
            yield message
