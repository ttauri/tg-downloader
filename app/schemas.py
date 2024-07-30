from pydantic import BaseModel
from typing import Optional


class MediaBase(BaseModel):
    tg_channel_id: int
    tg_message_id: int
    media_type: str
    size: float
    is_downloaded: bool
    filename: str


class MediaCreate(MediaBase):
    pass


class Media(MediaBase):
    id: int

    class Config:
        from_attributes = True


class ChannelBase(BaseModel):
    channel_id: str
    channel_name: str


class ChannelCreate(ChannelBase):
    pass


class Channel(ChannelBase):
    id: int

    class Config:
        from_attributes = True
