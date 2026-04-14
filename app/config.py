from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Inbound SMTP server
    smtp_host: str = "0.0.0.0"
    smtp_port: int = 8025

    # Outbound SMTP relay
    smtp_send_host: str = "smtp.gmail.com"
    smtp_send_port: int = 587
    smtp_send_user: str = ""
    smtp_send_password: str = ""
    smtp_send_from: str = ""

    # Anthropic
    anthropic_api_key: str = ""
    translation_model: str = "claude-haiku-4-5-20251001"

    # Relay address config
    relay_domain: str = "translate.example.com"
    relay_token: str = "translate"

    # Default destination email
    default_dest_email: str = "wlse66180@gmail.com"

    # App
    app_port: int = 8000
    database_url: str = "sqlite+aiosqlite:///./newsletter_translator.db"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @property
    def relay_email(self) -> str:
        return f"{self.relay_token}@{self.relay_domain}"


settings = Settings()
