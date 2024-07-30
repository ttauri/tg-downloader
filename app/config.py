from pydantic_settings import BaseSettings


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
