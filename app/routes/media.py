from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import crud, schemas
from ..database import get_db

router = APIRouter()


@router.get("/media/{channel_id}", response_model=list[schemas.Media])
def read_media(channel_id: str, db: Session = Depends(get_db)):
    return crud.get_all_media(db, channel_id)

