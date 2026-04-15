from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Inbound Gmail IMAP
    imap_host: str = "imap.gmail.com"
    imap_port: int = 993
    imap_user: str = "email.translator.2026@gmail.com"
    imap_password: str = ""          # Gmail App Password (not your regular password)
    imap_poll_interval: int = 60     # seconds between inbox checks

    # Outbound SMTP (for forwarding translated emails)
    smtp_send_host: str = "smtp.gmail.com"
    smtp_send_port: int = 587
    smtp_send_user: str = ""
    smtp_send_password: str = ""
    smtp_send_from: str = ""

    # Anthropic
    anthropic_api_key: str = ""
    translation_model: str = "claude-haiku-4-5-20251001"

    # Default destination email
    default_dest_email: str = "wlse66180@gmail.com"

    # App
    app_port: int = 8000
    database_url: str = "sqlite+aiosqlite:///./newsletter_translator.db"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @property
    def relay_email(self) -> str:
        return self.imap_user


settings = Settings()
