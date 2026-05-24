from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Mailgun
    mailgun_api_key: str = ""
    mailgun_domain: str = "example.com"
    mailgun_from_addr: str = ""

    # Anthropic
    anthropic_api_key: str = ""
    translation_model: str = "claude-sonnet-4-6"

    # Comma-separated list of allowed sender addresses (empty = allow all)
    allowed_senders: str = ""

    # Relay address config (local part of the inbound address configured in Mailgun routing)
    relay_token: str = "translate"

    # Default destination email
    default_dest_email: str = "wlse66180@gmail.com"

    # App
    app_port: int = 8000
    database_url: str = "sqlite+aiosqlite:///./newsletter_translator.db"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @property
    def relay_email(self) -> str:
        return f"{self.relay_token}@{self.mailgun_domain}"

    @property
    def from_addr(self) -> str:
        return self.mailgun_from_addr or self.relay_email


settings = Settings()
