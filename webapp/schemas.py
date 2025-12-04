from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class MediaBase(BaseModel):
    tg_channel_id: int
    tg_message_id: int
    media_type: str
    size: float
    is_downloaded: bool
    filename: str

    # Telegram file identification
    tg_file_id: Optional[int] = None

    # File metadata
    original_filename: Optional[str] = None
    duration: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None

    # Message metadata
    message_date: Optional[datetime] = None
    caption: Optional[str] = None


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
