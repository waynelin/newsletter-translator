from datetime import datetime

from pydantic import BaseModel, EmailStr


class ConfigResponse(BaseModel):
    relay_email: str
    source_lang: str
    target_lang: str
    dest_email: str


class ConfigUpdate(BaseModel):
    dest_email: EmailStr | None = None
    source_lang: str | None = None
    target_lang: str | None = None


class EmailLogItem(BaseModel):
    id: int
    received_at: datetime
    from_addr: str
    subject: str
    status: str
    error_message: str | None
    input_tokens: int | None
    output_tokens: int | None
    cache_read_tokens: int | None

    model_config = {"from_attributes": True}


class LogsResponse(BaseModel):
    items: list[EmailLogItem]
    total: int


class HealthResponse(BaseModel):
    status: str
