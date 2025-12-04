from sqlalchemy import Column, Integer, BigInteger, String, Boolean, Float, DateTime, Text, UniqueConstraint, ForeignKey
from sqlalchemy.orm import relationship

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
    size = Column(Float)  # Telegram-reported size
    is_downloaded = Column(Boolean, default=False)
    filename = Column(String, index=True)

    # Telegram file identification (for deduplication)
    tg_file_id = Column(BigInteger, index=True)  # message.document.id - unique per file

    # File metadata from Telegram
    original_filename = Column(String)  # Original filename from Telegram
    duration = Column(Integer)  # Duration in seconds (video/audio)
    width = Column(Integer)  # Width in pixels (video/image)
    height = Column(Integer)  # Height in pixels (video/image)

    # Message metadata
    message_date = Column(DateTime)  # When message was posted
    caption = Column(Text)  # Message text/description

    # Sync & deduplication fields
    file_hash = Column(String, index=True)  # SHA256 of first+last 1MB
    disk_size = Column(Integer)  # Actual file size on disk
    disk_verified = Column(Boolean, default=False)  # Last sync confirmed file exists
    duplicate_of_id = Column(Integer, ForeignKey('media.id'), nullable=True)
    quality_score = Column(Integer, default=0)  # For choosing best quality (higher = better)

    # Self-referential relationship for duplicates
    duplicate_of = relationship('Media', remote_side=[id], backref='duplicates')


class Channel(Base):
    __tablename__ = "channels"
    id = Column(Integer, primary_key=True, index=True)
    channel_id = Column(String, unique=True, index=True)
    channel_name = Column(String, unique=False, index=True)
    subscribed = Column(Boolean, default=False)
