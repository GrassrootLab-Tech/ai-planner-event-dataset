from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    hasdata_api_key: str
    serpapi_api_key: str | None = None
    reddit_client_id: str | None = None
    reddit_client_secret: str | None = None
    reddit_user_agent: str = "ai-planner-dataset-experiment/0.1 by partyhub"
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db_name: str = "research"
    event_scraped_content_collection: str = "event_scraped_content"
    event_scraped_chunks_collection: str = "event_scraped_chunks"
    chunk_output_dir: str = "output/cleaned"
    chunk_min_chars: int = 100
    openai_classification_model: str = "gpt-5.4-nano"
    openai_embedding_model: str = "text-embedding-3-small"
    anthropic_tagging_model: str = "claude-sonnet-4-5"
    anthropic_query_tagging_model: str = "claude-haiku-4-5"
    pinecone_api_key: str | None = None
    pinecone_index_name: str = "ai-planner-dataset"
    pinecone_tags_index_name: str = "ai-planner-tags"
