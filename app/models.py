from sqlalchemy import Column, Integer, String, Boolean, Float, UniqueConstraint

from .database import Base


class Media(Base):
    __tablename__ = "media"
    __table_args__ = (
        UniqueConstraint('tg_message_id', 'tg_channel_id', name='uq_message_channel'),
    )
    id = Column(Integer, primary_key=True, index=True)
    tg_message_id = Column(Integer, index=True)
    tg_channel_id = Column(Integer, index=True)
    media_type = Column(String, index=True)
    size = Column(Float)
    is_downloaded = Column(Boolean, default=False)
    filename = Column(String, index=True)


class Channel(Base):
    __tablename__ = "channels"
    id = Column(Integer, primary_key=True, index=True)
    channel_id = Column(String, unique=True, index=True)
    channel_name = Column(String, unique=False, index=True)
    subscribed = Column(Boolean, default=False)
