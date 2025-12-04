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
        and_(
            Media.tg_channel_id == channel_id,
            Media.is_downloaded == False,
            Media.duplicate_of_id == None  # Exclude duplicates
        )
    )
    if order == "small":
        query = query.order_by(asc(Media.size))
    elif order == "large":
        query = query.order_by(desc(Media.size))
    return query


def count_filtered_pending_media(db: Session, channel_id: str, options: dict) -> dict:
    """
    Count pending media that would be downloaded based on filter options.
    Returns dict with total pending, filtered count, and would-download count.
    """
    from webapp.services.periodic_task import should_download_media

    pending = db.query(Media).filter(
        and_(
            Media.tg_channel_id == channel_id,
            Media.is_downloaded == False,
            Media.duplicate_of_id == None
        )
    ).all()

    total_pending = len(pending)
    would_download = 0
    filtered_out = 0

    for m in pending:
        should_dl, _ = should_download_media(m, options)
        if should_dl:
            would_download += 1
        else:
            filtered_out += 1

    return {
        "total_pending": total_pending,
        "would_download": would_download,
        "filtered_out": filtered_out
    }


def find_downloaded_by_file_id(db: Session, channel_id: str, tg_file_id: int):
    """Find a downloaded media record with the same tg_file_id."""
    if not tg_file_id:
        return None
    return db.query(Media).filter(
        and_(
            Media.tg_channel_id == channel_id,
            Media.tg_file_id == tg_file_id,
            Media.is_downloaded == True
        )
    ).first()


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


def get_channel_content_stats(db: Session, channel_id: str, downloaded_only: bool = True):
    """
    Get detailed content statistics for a channel.
    Returns duration distribution, resolution distribution, activity timeline, and top content.

    Args:
        downloaded_only: If True, only include downloaded files. If False, include all files.
    """
    from datetime import datetime, timedelta
    from collections import defaultdict

    # Base filter for videos with duration
    video_filters = [
        Media.tg_channel_id == channel_id,
        Media.media_type.like('video%'),
        Media.duration != None,
        Media.duration > 0
    ]
    if downloaded_only:
        video_filters.append(Media.is_downloaded == True)

    videos_with_duration = db.query(Media).filter(and_(*video_filters)).all()

    # Base filter for media with resolution
    resolution_filters = [
        Media.tg_channel_id == channel_id,
        Media.width != None,
        Media.height != None
    ]
    if downloaded_only:
        resolution_filters.append(Media.is_downloaded == True)

    media_with_resolution = db.query(Media).filter(and_(*resolution_filters)).all()

    # Get all media for activity timeline (always show full channel activity)
    all_media_for_timeline = db.query(Media).filter(
        Media.tg_channel_id == channel_id
    ).all()

    # Get duplicates count
    duplicates = db.query(Media).filter(
        and_(
            Media.tg_channel_id == channel_id,
            Media.duplicate_of_id != None
        )
    ).all()

    # ===== Duration Distribution =====
    duration_buckets = {
        '< 30s': 0,
        '30s - 1m': 0,
        '1m - 5m': 0,
        '5m - 15m': 0,
        '15m - 30m': 0,
        '30m - 1h': 0,
        '> 1h': 0
    }

    total_duration = 0
    for video in videos_with_duration:
        d = video.duration
        total_duration += d

        if d < 30:
            duration_buckets['< 30s'] += 1
        elif d < 60:
            duration_buckets['30s - 1m'] += 1
        elif d < 300:
            duration_buckets['1m - 5m'] += 1
        elif d < 900:
            duration_buckets['5m - 15m'] += 1
        elif d < 1800:
            duration_buckets['15m - 30m'] += 1
        elif d < 3600:
            duration_buckets['30m - 1h'] += 1
        else:
            duration_buckets['> 1h'] += 1

    # ===== Resolution Distribution =====
    resolution_buckets = {
        '360p': 0,
        '480p': 0,
        '720p': 0,
        '1080p': 0,
        '1440p': 0,
        '4K+': 0
    }

    for m in media_with_resolution:
        height = m.height
        if height <= 360:
            resolution_buckets['360p'] += 1
        elif height <= 480:
            resolution_buckets['480p'] += 1
        elif height <= 720:
            resolution_buckets['720p'] += 1
        elif height <= 1080:
            resolution_buckets['1080p'] += 1
        elif height <= 1440:
            resolution_buckets['1440p'] += 1
        else:
            resolution_buckets['4K+'] += 1

    # ===== Activity Timeline (all time) =====
    activity_timeline = defaultdict(int)

    for m in all_media_for_timeline:
        if m.message_date:
            month_key = m.message_date.strftime('%Y-%m')
            activity_timeline[month_key] += 1

    # Sort all months chronologically
    sorted_months = sorted(activity_timeline.keys())
    activity_data = {month: activity_timeline[month] for month in sorted_months}

    # ===== Top Content =====
    # Longest videos
    longest_filters = [
        Media.tg_channel_id == channel_id,
        Media.media_type.like('video%'),
        Media.duration != None
    ]
    if downloaded_only:
        longest_filters.append(Media.is_downloaded == True)

    longest_videos = db.query(Media).filter(
        and_(*longest_filters)
    ).order_by(desc(Media.duration)).limit(5).all()

    # Largest files
    largest_filters = [
        Media.tg_channel_id == channel_id,
        Media.size != None
    ]
    if downloaded_only:
        largest_filters.append(Media.is_downloaded == True)

    largest_files = db.query(Media).filter(
        and_(*largest_filters)
    ).order_by(desc(Media.size)).limit(5).all()

    # ===== Summary Stats =====
    avg_duration = total_duration / len(videos_with_duration) if videos_with_duration else 0

    # Calculate duplicate space saved
    duplicate_size = sum(d.size or 0 for d in duplicates)

    return {
        'duration_distribution': duration_buckets,
        'resolution_distribution': resolution_buckets,
        'activity_timeline': activity_data,
        'total_duration_seconds': total_duration,
        'avg_duration_seconds': avg_duration,
        'video_count_with_duration': len(videos_with_duration),
        'duplicates_count': len(duplicates),
        'duplicates_size': duplicate_size,
        'longest_videos': [
            {
                'id': v.id,
                'filename': v.original_filename or v.filename,
                'duration': v.duration,
                'size': v.size
            } for v in longest_videos
        ],
        'largest_files': [
            {
                'id': f.id,
                'filename': f.original_filename or f.filename,
                'size': f.size,
                'media_type': f.media_type
            } for f in largest_files
        ]
    }


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
