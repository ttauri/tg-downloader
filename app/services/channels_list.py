from ..telegram_client import fetch_channels_list


async def get_channels_list():
    return await fetch_channels_list()
