import asyncio
import json

import starlette.status as status
from fastapi import BackgroundTasks, Depends, FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from .crud import (
    create_or_update_channel,
    get_available_channels,
    get_channel_by_id,
    get_subscribed_channels,
    set_channel_subscription,
    get_all_media,
    get_all_downloaded_media,
    get_all_not_downloaded_media,
)
from .database import get_db, init_db
from .routes import media
from .schemas import ChannelCreate
from .telegram_client import fetch_channels_list
from .services.task_manager import task_manager, TaskStatus
from .services.periodic_task import (
    fetch_messages_form_channel,
    download_media_from_channel,
)

app = FastAPI()

templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.on_event("startup")
def on_startup():
    init_db()


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


@app.get("/channel_details/", response_class=HTMLResponse)
async def get_channel_details(
    request: Request, channel_id: str = Query(...), db: Session = Depends(get_db)
):
    chan = get_channel_by_id(db, channel_id)
    all_media = get_all_media(db, channel_id)
    d_media = get_all_downloaded_media(db, channel_id)
    nd_media = get_all_not_downloaded_media(db, channel_id)
    return templates.TemplateResponse(
        "channel_details.html",
        {
            "request": request,
            "channel": chan,
            "all_media": len(all_media),
            "downloaded_media": d_media.count(),
            "not_downloaded_media": nd_media.count(),
        },
    )


@app.get("/update_channels_list/", response_class=HTMLResponse)
async def update_channel_form(request: Request, db: Session = Depends(get_db)):
    available_channels = await fetch_channels_list()

    for channel in available_channels:
        chan = ChannelCreate(channel_id=str(channel.id), channel_name=channel.name)
        create_or_update_channel(db, chan)
    return templates.TemplateResponse(
        "index.html", {"request": request, "available_channels": available_channels}
    )


async def run_fetch_task(channel_id: str, task):
    """Background task wrapper for fetching messages."""
    await fetch_messages_form_channel(channel_id=channel_id, task=task)


async def run_download_task(channel_id: str, task):
    """Background task wrapper for downloading media."""
    await download_media_from_channel(channel_id=channel_id, task=task)


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


@app.get("/task_progress/{task_id}")
async def task_progress(task_id: str):
    """SSE endpoint for streaming task progress."""
    task = task_manager.get_task(task_id)
    if not task:
        return {"error": "Task not found"}

    async def event_stream():
        try:
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
