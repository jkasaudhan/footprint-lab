from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    secret_key: str = "dev-insecure-change-me"

    email_mode: str = "console"  # "console" | "smtp"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "noreply@deepfakefinance.com"

    hibp_api_key: str = ""

    app_name: str = "Footprint Lab"
    rate_limit: str = "10/hour"

    # --- Localhost-only research page (advanced OSINT tools) ---
    enable_research: bool = False           # off by default; on in local .env only
    research_top_sites: int = 300
    research_per_site_timeout: int = 10


settings = Settings()
