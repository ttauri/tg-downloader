from pathlib import Path

from pydantic_settings import BaseSettings

ENV_FILE_PATH = Path(__file__).parent.parent / "env"

ENV_TEMPLATE = """\
api_id=YOUR_API_ID
api_hash=YOUR_API_HASH
phone=YOUR_PHONE_NUMBER
db_url=sqlite:///./test.db
media_download_path=./media
sorting_type=small
"""

if not ENV_FILE_PATH.exists():
    ENV_FILE_PATH.write_text(ENV_TEMPLATE)
    raise SystemExit(
        f"Created env file at {ENV_FILE_PATH}. "
        "Please fill in your Telegram API credentials and restart."
    )


class Settings(BaseSettings):
    api_id: str
    api_hash: str
    phone: str
    db_url: str = "sqlite:///./test.db"
    # media_download_path: str = "./media"
    media_download_path: str = "/mnt/c/Users/Tau/Documents/media"
    # Sorting typa can be small or large.
    sorting_type: str = "small"

    class Config:
        env_file = "env"


settings = Settings()
