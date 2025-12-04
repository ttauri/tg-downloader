from sqlalchemy.orm import Session
from sqlalchemy import and_, asc, desc, func

from . import schemas
from .models import Media, Channel


def get_channel_by_id(db: Session, channel_id: str):
    return db.query(Channel).filter(Channel.channel_id == channel_id).first()


def get_subscribed_channels(db: Session):
    return db.query(Channel).filter(Channel.subscribed == True).all()


def get_available_channels(db: Session):
    return db.query(Channel).filter(Channel.subscribed == False).all()


def set_channel_subscription(db: Session, channel_id: str, subscribed: bool):
    channel = db.query(Channel).filter(Channel.channel_id == channel_id).first()
    channel.subscribed = subscribed
    db.commit()
    return channel


def create_or_update_channel(db: Session, channel: schemas.ChannelCreate):
    chan = db.query(Channel).filter(Channel.channel_id == channel.channel_id).first()
    if chan:
        chan.channel_name = channel.channel_name
    else:
        chan = Channel(channel_id=channel.channel_id, channel_name=channel.channel_name)
        db.add(chan)
    db.commit()
    db.refresh(chan)
    return chan


def get_all_media(db: Session, channel_id: str):
    return db.query(Media).filter(Media.tg_channel_id == channel_id).all()


def get_all_not_downloaded_media(db: Session, channel_id: int, order="none"):
    query = db.query(Media).filter(
        and_(Media.tg_channel_id == channel_id, Media.is_downloaded == False)
    )
    if order == "small":
        query = query.order_by(asc(Media.size))
    elif order == "large":
        query = query.order_by(desc(Media.size))
    return query


def get_all_downloaded_media(db: Session, channel_id: str):
    return db.query(Media).filter(
        and_(Media.tg_channel_id == channel_id, Media.is_downloaded == True)
    )


def delete_channel_media(db: Session, channel_id: str):
    """Delete all media records for a channel."""
    deleted = db.query(Media).filter(Media.tg_channel_id == channel_id).delete()
    db.commit()
    return deleted


def get_channel_media_stats(db: Session, channel_id: str):
    """Get media statistics for a channel (videos, images, other by type) with download status."""
    results = db.query(
        Media.media_type,
        Media.is_downloaded,
        func.count(Media.id).label('count'),
        func.sum(Media.size).label('total_size')
    ).filter(
        Media.tg_channel_id == channel_id
    ).group_by(Media.media_type, Media.is_downloaded).all()

    stats = {
        'videos': {'count': 0, 'downloaded': 0, 'size': 0, 'downloaded_size': 0},
        'images': {'count': 0, 'downloaded': 0, 'size': 0, 'downloaded_size': 0},
        'other': {'count': 0, 'downloaded': 0, 'size': 0, 'downloaded_size': 0},
        'total_size': 0,
        'total_downloaded_size': 0
    }

    for media_type, is_downloaded, count, total_size in results:
        size = total_size or 0
        stats['total_size'] += size

        if media_type and media_type.startswith('video'):
            category = 'videos'
        elif media_type and media_type.startswith('image'):
            category = 'images'
        else:
            category = 'other'

        stats[category]['count'] += count
        stats[category]['size'] += size
        if is_downloaded:
            stats[category]['downloaded'] += count
            stats[category]['downloaded_size'] += size
            stats['total_downloaded_size'] += size

    return stats


def create_media(db: Session, media: schemas.MediaCreate):
    existing = db.query(Media).filter(
        and_(
            Media.tg_message_id == media.tg_message_id,
            Media.tg_channel_id == media.tg_channel_id
        )
    ).first()
    if existing:
        # Don't overwrite is_downloaded and filename if already downloaded
        for key, value in media.model_dump().items():
            if key in ('is_downloaded', 'filename') and existing.is_downloaded:
                continue
            setattr(existing, key, value)
    else:
        existing = Media(**media.model_dump())
        db.add(existing)
    db.commit()
    db.refresh(existing)
    return existing
