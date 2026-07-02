from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    hasdata_api_key: str
    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db_name: str = "research"
    event_scraped_content_collection: str = "event_scraped_content"
