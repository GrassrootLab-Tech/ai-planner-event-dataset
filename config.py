from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    hasdata_api_key: str
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db_name: str = "research"
    event_scraped_content_collection: str = "event_scraped_content"
    event_scraped_chunks_collection: str = "event_scraped_chunks"
    chunk_output_dir: str = "output/cleaned"
    chunk_min_chars: int = 100
    openai_classification_model: str = "gpt-5.4-nano"
    anthropic_tagging_model: str = "claude-sonnet-4-5"
