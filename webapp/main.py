import asyncio
import json
from pathlib import Path

import starlette.status as status
from fastapi import BackgroundTasks, Depends, FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from .crud import (
    create_or_update_channel,
    delete_channel_media,
    get_available_channels,
    get_channel_by_id,
    get_channel_media_stats,
    get_subscribed_channels,
    set_channel_subscription,
    get_all_media,
    get_all_downloaded_media,
    get_all_not_downloaded_media,
)
from .models import Media
from .database import get_db, init_db
from .routes import media
from .schemas import ChannelCreate
from .telegram_client import fetch_channels_list
from .services.task_manager import task_manager, TaskStatus
from .services.periodic_task import (
    fetch_messages_form_channel,
    download_media_from_channel,
)
from .services.sync_service import sync_channel_storage, startup_sync_check
from .services.storage_service import (
    get_channel_folder_path,
    get_folder_stats,
    format_size as format_size_storage,
)
from .config import settings, ENV_FILE_PATH

# Get the directory where this file is located
BASE_DIR = Path(__file__).resolve().parent

app = FastAPI()

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


@app.on_event("startup")
def on_startup():
    init_db()
    startup_sync_check()


app.include_router(media.router, prefix="/media", tags=["media"])


@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request, db: Session = Depends(get_db)):
    sub_channels = get_subscribed_channels(db)
    available_channels = get_available_channels(db)
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "sub_channels": sub_channels,
            "available_channels": available_channels,
        },
    )


def format_size(size_bytes):
    """Format size in bytes to human readable string."""
    if size_bytes < 1024:
        return f"{size_bytes:.0f} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.2f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


@app.get("/channel_details/", response_class=HTMLResponse)
async def get_channel_details(
    request: Request, channel_id: str = Query(...), db: Session = Depends(get_db)
):
    chan = get_channel_by_id(db, channel_id)
    all_media = get_all_media(db, channel_id)
    d_media = get_all_downloaded_media(db, channel_id)
    nd_media = get_all_not_downloaded_media(db, channel_id)
    stats = get_channel_media_stats(db, channel_id)

    return templates.TemplateResponse(
        "channel_details.html",
        {
            "request": request,
            "channel": chan,
            "all_media": len(all_media),
            "downloaded_media": d_media.count(),
            "not_downloaded_media": nd_media.count(),
            "stats": stats,
            "video_count": stats['videos']['count'],
            "video_downloaded": stats['videos']['downloaded'],
            "video_size": format_size(stats['videos']['size']),
            "video_downloaded_size": format_size(stats['videos']['downloaded_size']),
            "image_count": stats['images']['count'],
            "image_downloaded": stats['images']['downloaded'],
            "image_size": format_size(stats['images']['size']),
            "image_downloaded_size": format_size(stats['images']['downloaded_size']),
            "other_count": stats['other']['count'],
            "other_downloaded": stats['other']['downloaded'],
            "other_size": format_size(stats['other']['size']),
            "other_downloaded_size": format_size(stats['other']['downloaded_size']),
            "total_size": format_size(stats['total_size']),
            "total_downloaded_size": format_size(stats['total_downloaded_size']),
        },
    )


@app.get("/update_channels_list/")
async def update_channel_form(request: Request, db: Session = Depends(get_db)):
    available_channels = await fetch_channels_list()

    for channel in available_channels:
        chan = ChannelCreate(channel_id=str(channel.id), channel_name=channel.name)
        create_or_update_channel(db, chan)

    return RedirectResponse("/", status_code=status.HTTP_302_FOUND)


async def run_fetch_task(channel_id: str, task):
    """Background task wrapper for fetching messages."""
    await fetch_messages_form_channel(channel_id=channel_id, task=task)


async def run_download_task(channel_id: str, task):
    """Background task wrapper for downloading media."""
    await download_media_from_channel(channel_id=channel_id, task=task)


async def run_sync_task(channel_id: str, channel_name: str, task):
    """Background task wrapper for syncing storage."""
    await sync_channel_storage(channel_id=channel_id, channel_name=channel_name, task=task)


@app.post("/fetch_messages/")
async def check_messages(
    request: Request,
    background_tasks: BackgroundTasks,
    channel_id: str = Query(...),
    db: Session = Depends(get_db)
):
    # Check if there's already an active task for this channel
    existing = task_manager.get_active_task(channel_id, "fetch")
    if existing:
        return {"task_id": existing.task_id, "status": "already_running"}

    task = task_manager.create_task(channel_id, "fetch")
    background_tasks.add_task(run_fetch_task, channel_id, task)
    return {"task_id": task.task_id, "status": "started"}


@app.post("/download_media_from_channel/")
async def download_media(
    request: Request,
    background_tasks: BackgroundTasks,
    channel_id: str = Query(...),
    db: Session = Depends(get_db)
):
    # Check if there's already an active task for this channel
    existing = task_manager.get_active_task(channel_id, "download")
    if existing:
        return {"task_id": existing.task_id, "status": "already_running"}

    task = task_manager.create_task(channel_id, "download")
    background_tasks.add_task(run_download_task, channel_id, task)
    return {"task_id": task.task_id, "status": "started"}


@app.post("/sync_channel/")
async def sync_channel(
    request: Request,
    background_tasks: BackgroundTasks,
    channel_id: str = Query(...),
    db: Session = Depends(get_db)
):
    """Sync database with actual files on disk."""
    # Check if there's already an active sync task for this channel
    existing = task_manager.get_active_task(channel_id, "sync")
    if existing:
        return {"task_id": existing.task_id, "status": "already_running"}

    channel = get_channel_by_id(db, channel_id)
    if not channel:
        return {"error": "Channel not found"}

    task = task_manager.create_task(channel_id, "sync")
    background_tasks.add_task(run_sync_task, channel_id, channel.channel_name, task)
    return {"task_id": task.task_id, "status": "started"}


@app.get("/task_progress/{task_id}")
async def task_progress(task_id: str):
    """SSE endpoint for streaming task progress."""
    task = task_manager.get_task(task_id)
    if not task:
        return {"error": "Task not found"}

    async def event_stream():
        try:
            # Send current state immediately when connection is established
            progress = task.progress
            data = {
                "task_id": progress.task_id,
                "status": progress.status.value,
                "current": progress.current,
                "total": progress.total,
                "message": progress.message or "Starting...",
                "error": progress.error,
            }
            yield f"data: {json.dumps(data)}\n\n"

            # Then listen for updates
            async for progress in task.events():
                data = {
                    "task_id": progress.task_id,
                    "status": progress.status.value,
                    "current": progress.current,
                    "total": progress.total,
                    "message": progress.message,
                    "error": progress.error,
                }
                yield f"data: {json.dumps(data)}\n\n"
        except asyncio.CancelledError:
            pass

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


@app.post("/stop_task/{task_id}")
async def stop_task(task_id: str):
    """Stop a running task."""
    task = task_manager.get_task(task_id)
    if not task:
        return {"error": "Task not found"}
    task.cancel()
    return {"status": "stopping", "task_id": task_id}


@app.post("/subscribe_to_channel/", response_class=HTMLResponse)
async def add_channel(
    request: Request, channel_id: str = Form(...), db: Session = Depends(get_db)
):
    set_channel_subscription(db, channel_id, True)
    return RedirectResponse("/", status_code=status.HTTP_302_FOUND)


@app.post("/unsubscribe_to_channel/", response_class=HTMLResponse)
async def unsubscribe_from_channel(
    request: Request, channel_id: str = Form(...), db: Session = Depends(get_db)
):
    set_channel_subscription(db, channel_id, False)
    return RedirectResponse("/", status_code=status.HTTP_302_FOUND)


@app.post("/reset_channel/{channel_id}")
async def reset_channel(channel_id: str, db: Session = Depends(get_db)):
    """Delete all media records for a channel."""
    deleted = delete_channel_media(db, channel_id)
    return {"status": "success", "deleted": deleted, "channel_id": channel_id}


@app.get("/storage_info/{channel_id}")
async def storage_info(channel_id: str, db: Session = Depends(get_db)):
    """Get storage information for a channel's media folder."""
    channel = get_channel_by_id(db, channel_id)
    if not channel:
        return {"error": "Channel not found"}

    folder_path = get_channel_folder_path(channel.channel_name)
    stats = get_folder_stats(folder_path)

    # Get DB count for comparison
    all_media = get_all_media(db, channel_id)
    downloaded_media = get_all_downloaded_media(db, channel_id)
    db_downloaded_count = downloaded_media.count()

    # Format extensions with sizes
    extensions_formatted = {}
    for ext, data in stats['extensions'].items():
        extensions_formatted[ext] = {
            'count': data['count'],
            'size': data['size'],
            'size_formatted': format_size_storage(data['size']),
        }

    # Format file list with sizes
    files_formatted = []
    for f in stats['files']:
        files_formatted.append({
            'name': f['name'],
            'size': f['size'],
            'size_formatted': format_size_storage(f['size']),
            'extension': f['extension'],
        })

    return {
        "exists": stats['exists'],
        "path": stats['path'],
        "file_count": stats['file_count'],
        "total_size": stats['total_size'],
        "total_size_formatted": format_size_storage(stats['total_size']),
        "extensions": extensions_formatted,
        "files": files_formatted,
        "db_downloaded_count": db_downloaded_count,
        "db_total_count": len(all_media),
        "mismatch": stats['file_count'] != db_downloaded_count if stats['exists'] else False,
    }


def format_duration(seconds):
    """Format duration in seconds to MM:SS or HH:MM:SS."""
    if not seconds:
        return None
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


@app.get("/media_list/{channel_id}")
async def media_list(
    channel_id: str,
    db: Session = Depends(get_db),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    media_type: str = Query(None),
    downloaded: bool = Query(None),
    sort_by: str = Query("date"),
    sort_order: str = Query("desc"),
):
    """Get paginated media list with metadata for a channel."""
    from sqlalchemy import and_, asc, desc

    query = db.query(Media).filter(Media.tg_channel_id == channel_id)

    if media_type:
        query = query.filter(Media.media_type.like(f"{media_type}%"))
    if downloaded is not None:
        query = query.filter(Media.is_downloaded == downloaded)

    # Apply sorting
    sort_func = desc if sort_order == "desc" else asc
    if sort_by == "size":
        query = query.order_by(sort_func(Media.size))
    elif sort_by == "duration":
        query = query.order_by(sort_func(Media.duration))
    elif sort_by == "name":
        query = query.order_by(sort_func(Media.original_filename))
    else:  # default: date
        query = query.order_by(sort_func(Media.message_date))

    total = query.count()
    items = query.offset(offset).limit(limit).all()

    media_items = []
    for m in items:
        media_items.append({
            "id": m.id,
            "tg_message_id": m.tg_message_id,
            "media_type": m.media_type,
            "size": m.size,
            "size_formatted": format_size(m.size) if m.size else None,
            "is_downloaded": m.is_downloaded,
            "filename": m.filename,
            "original_filename": m.original_filename,
            "duration": m.duration,
            "duration_formatted": format_duration(m.duration),
            "width": m.width,
            "height": m.height,
            "resolution": f"{m.width}x{m.height}" if m.width and m.height else None,
            "message_date": m.message_date.isoformat() if m.message_date else None,
            "caption": m.caption[:100] + "..." if m.caption and len(m.caption) > 100 else m.caption,
            "is_duplicate": m.duplicate_of_id is not None,
        })

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "items": media_items,
    }


def read_env_file():
    """Read current settings from env file."""
    env_settings = {}
    if ENV_FILE_PATH.exists():
        for line in ENV_FILE_PATH.read_text().strip().split('\n'):
            if '=' in line:
                key, value = line.split('=', 1)
                env_settings[key.strip()] = value.strip()
    return env_settings


def write_env_file(env_settings: dict):
    """Write settings to env file."""
    lines = [f"{key}={value}" for key, value in env_settings.items()]
    ENV_FILE_PATH.write_text('\n'.join(lines) + '\n')


@app.get("/settings/", response_class=HTMLResponse)
async def settings_page(request: Request, message: str = None, error: bool = False):
    """Display settings page."""
    env_settings = read_env_file()
    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "settings": env_settings,
            "message": message,
            "error": error,
        },
    )


@app.post("/settings/", response_class=HTMLResponse)
async def save_settings(
    request: Request,
    api_id: str = Form(...),
    api_hash: str = Form(...),
    phone: str = Form(...),
    db_url: str = Form(...),
    media_download_path: str = Form(...),
    sorting_type: str = Form(...),
):
    """Save settings to env file."""
    try:
        env_settings = {
            "api_id": api_id,
            "api_hash": api_hash,
            "phone": phone,
            "db_url": db_url,
            "media_download_path": media_download_path,
            "sorting_type": sorting_type,
        }
        write_env_file(env_settings)

        return templates.TemplateResponse(
            "settings.html",
            {
                "request": request,
                "settings": env_settings,
                "message": "Settings saved successfully. Restart the application for API changes to take effect.",
                "error": False,
            },
        )
    except Exception as e:
        env_settings = read_env_file()
        return templates.TemplateResponse(
            "settings.html",
            {
                "request": request,
                "settings": env_settings,
                "message": f"Failed to save settings: {str(e)}",
                "error": True,
            },
        )
