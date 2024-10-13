from sqlalchemy.orm import Session
from sqlalchemy import and_, asc, desc, func
from . import schemas
from sqlalchemy.sql.expression import case
from app.models import Media, Channel
from app.logging_conf import logger


def get_channels(db: Session):
    return db.query(Channel).all()


def get_channel_by_id(db: Session, channel_id: str):
    return db.query(Channel).filter(Channel.channel_id == channel_id).first()


def get_subscribed_channels(db: Session):
    channels = db.query(Channel).filter(Channel.subscribed == True)
    logger.info(f"Qurying subscribed channels, got: {channels.count()} channels")
    return channels


def get_available_channels(db: Session):
    channels = db.query(Channel).filter(Channel.subscribed == False)
    logger.info(f"Qurying available channels, got: {channels.count()} channels")
    return channels


def subscribe_to_channel(db: Session, channel_id: str):
    channel = db.query(Channel).filter(Channel.channel_id == channel_id).first()
    channel.subscribed = True
    db.commit()
    return channel


def unsubscribe_to_channel(db: Session, channel_id: str):
    channel = db.query(Channel).filter(Channel.channel_id == channel_id).first()
    channel.subscribed = False
    db.commit()
    return channel


def create_or_update_channel(db: Session, channel: schemas.ChannelCreate):
    chan = db.query(Channel).filter(Channel.channel_id == channel.channel_id).first()
    if chan:
        chan.channel_id = channel.channel_id
        chan.channel_name = channel.channel_name
        db.commit()
        db.refresh(chan)
        return chan
    else:
        db_channel = Channel(
            channel_id=channel.channel_id, channel_name=channel.channel_name
        )
        db.add(db_channel)
        db.commit()
        db.refresh(db_channel)
        return db_channel


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

    # return query.all()
    return query


# def get_all_not_downloaded_media(db: Session, channel_id: str, order="none"):
#     query = db.query(Media).filter(
#         and_(Media.tg_channel_id == channel_id, Media.is_downloaded == False)
#     )
#
#     if order == "medium":
#         # Get the median file size
#         subquery = (
#             db.query(func.avg(Media.size).label("median_size"))
#             .filter(Media.tg_channel_id == channel_id)
#             .subquery()
#         )
#
#         # Order by absolute difference from the median size
#         query = query.add_columns(
#             (func.abs(Media.size - subquery.c.median_size)).label("size_diff")
#         ).order_by("size_diff")
#     elif order == "small":
#         query = query.order_by(Media.size)
#     elif order == "large":
#         query = query.order_by(Media.size.desc())
#
#     return query.all()


def get_all_downloaded_media(db: Session, channel_id: str):
    return db.query(Media).filter(
        and_(Media.tg_channel_id == channel_id, Media.is_downloaded == True)
    )


def is_media_exists(db: Session, tg_message_id: str):
    return db.query(Media).filter(Media.tg_message_id == tg_message_id).all()


def create_media(db: Session, media: schemas.MediaCreate):
    existing_media = (
        db.query(Media).filter(Media.tg_message_id == media.tg_message_id).first()
    )

    if existing_media:
        # Update existing record
        for key, value in media.dict().items():
            setattr(existing_media, key, value)
    else:
        # Create new record
        existing_media = Media(**media.dict())
        db.add(existing_media)

    db.commit()
    db.refresh(existing_media)
    return existing_media
