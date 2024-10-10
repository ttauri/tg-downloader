import starlette.status as status
from fastapi import Depends, FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from .crud import (
    create_or_update_channel,
    get_available_channels,
    get_channel_by_id,
    get_subscribed_channels,
    subscribe_to_channel,
    unsubscribe_to_channel,
    get_all_media,
    get_all_downloaded_media,
    get_all_not_downloaded_media,
)
from .database import SessionLocal, init_db
from .routes import channels, media
from .schemas import ChannelCreate
from .services.channels_list import get_channels_list
from .services.periodic_task import (
    check_for_new_messages,
    fetch_messages_form_channel,
    download_media_from_channel,
)

app = FastAPI()

templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.on_event("startup")
def on_startup():
    init_db()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


app.include_router(channels.router, prefix="/channels", tags=["channels"])
app.include_router(media.router, prefix="/media", tags=["media"])


@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request, db: Session = Depends(get_db)):
    sub_channels = get_subscribed_channels(db)
    av_chanels = get_available_channels(db)
    for chan in av_chanels:
        print(chan.channel_name)
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "sub_channels": sub_channels,
            "available_channels": av_chanels,
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
    available_channels = await get_channels_list()

    for channel in available_channels:
        chan = ChannelCreate(channel_id=str(channel.id), channel_name=channel.name)
        create_or_update_channel(db, chan)
    return templates.TemplateResponse(
        "index.html", {"request": request, "available_channels": available_channels}
    )


@app.post("/fetch_messages/", response_class=HTMLResponse)
async def check_messages(
    request: Request, channel_id: str = Query(...), db: Session = Depends(get_db)
):
    await fetch_messages_form_channel(channel_id=channel_id)
    return RedirectResponse("/", status_code=status.HTTP_302_FOUND)


@app.post("/download_media_from_channel/", response_class=HTMLResponse)
async def download_media(
    request: Request, channel_id: str = Query(...), db: Session = Depends(get_db)
):
    await download_media_from_channel(channel_id=channel_id)
    return RedirectResponse("/", status_code=status.HTTP_302_FOUND)


@app.post("/subscribe_to_channel/", response_class=HTMLResponse)
async def add_channel(
    request: Request, channel_id: str = Form(...), db: Session = Depends(get_db)
):
    subscribe_to_channel(db, channel_id)
    return RedirectResponse("/", status_code=status.HTTP_302_FOUND)


@app.post("/unsubscribe_to_channel/", response_class=HTMLResponse)
async def unsubscribe_from_channel(
    request: Request, channel_id: str = Form(...), db: Session = Depends(get_db)
):
    unsubscribe_to_channel(db, channel_id)
    return RedirectResponse("/", status_code=status.HTTP_302_FOUND)
