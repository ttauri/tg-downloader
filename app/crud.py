from sqlalchemy.orm import Session
from sqlalchemy import and_, asc, desc

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


def create_media(db: Session, media: schemas.MediaCreate):
    existing = db.query(Media).filter(Media.tg_message_id == media.tg_message_id).first()
    if existing:
        for key, value in media.model_dump().items():
            setattr(existing, key, value)
    else:
        existing = Media(**media.model_dump())
        db.add(existing)
    db.commit()
    db.refresh(existing)
    return existing
