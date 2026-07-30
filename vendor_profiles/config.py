from pydantic_settings import BaseSettings, SettingsConfigDict


class VendorSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    hasdata_api_key: str
    dataforseo_login: str | None = None
    dataforseo_password: str | None = None
    anthropic_api_key: str | None = None
    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db_name: str = "research"
    vendor_data_serp_results_collection: str = "vendor_data_serp_results"
    vendors_scraped_profiles_collection: str = "vendors_scraped_profiles"
    vendors_scraped_directory_urls_collection: str = "vendors_scraped_directory_urls"
    anthropic_link_filter_model: str = "claude-haiku-4-5"
