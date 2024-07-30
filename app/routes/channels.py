from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import crud, models, schemas
from ..database import SessionLocal, init_db

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("/channels/", response_model=schemas.Channel)
def create_channel(channel: schemas.ChannelCreate, db: Session = Depends(get_db)):
    db_channel = crud.get_channel_by_id(db, channel.channel_id)
    if db_channel:
        raise HTTPException(status_code=400, detail="Channel already registered")
    return crud.create_channel(db=db, channel=channel)

