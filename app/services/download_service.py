import os
from fastapi import BackgroundTasks
from app.crud import get_media
from app.config import settings


def download_content_by_chunks(channel_id: str, max_size: float, db: Session):
    media_items = get_media(db, channel_id)
    downloaded_size = 0
    for media in media_items:
        if downloaded_size + media.size > max_size:
            break
        # Download the media
        media_path = os.path.join(settings.media_download_path, media.download_link)
        # Mark as downloaded
        media.is_downloaded = True
        db.add(media)
        db.commit()
        downloaded_size += media.size


def start_download(
    channel_id: str,
    max_size: float,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    background_tasks.add_task(download_content_by_chunks, channel_id, max_size, db)
