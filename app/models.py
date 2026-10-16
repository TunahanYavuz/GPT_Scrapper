"""Pydantic contracts and URL validation."""
from __future__ import annotations

import ipaddress
import re
import socket
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator


def validate_public_http_url(value: str, *, resolve_host: bool = False) -> str:
    """Validate URL syntax; optionally resolve and reject private DNS targets at scrape time."""
    value = value.strip()
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Yalnızca http/https URL'leri kullanılabilir.")
    if not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("URL geçerli bir hostname içermeli ve kullanıcı bilgisi içermemeli.")
    host = parsed.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        raise ValueError("Yerel ağ ve localhost adresleri kabul edilmez.")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        if resolve_host:
            try:
                answers = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
            except socket.gaierror as exc:
                raise ValueError("Hostname çözümlenemedi; tarama güvenlik için durduruldu.") from exc
            for answer in answers:
                resolved = ipaddress.ip_address(answer[4][0])
                if not resolved.is_global:
                    raise ValueError("Hostname özel veya loopback bir IP adresine çözülüyor.")
    else:
        if not ip.is_global:
            raise ValueError("Özel, loopback veya ayrılmış IP adreslerine izin verilmez.")
    if parsed.port is not None and not 1 <= parsed.port <= 65535:
        raise ValueError("Port aralık dışında.")
    return value


class Selectors(BaseModel):
    card: str = Field(default="", max_length=300)
    title: str = Field(default="", max_length=300)
    description: str = Field(default="", max_length=300)
    link: str = Field(default="a", max_length=300)
    start_date: str = Field(default="", max_length=300)
    end_date: str = Field(default="", max_length=300)
    next_page: str = Field(default="", max_length=300)


class SourceCreate(BaseModel):
    bank_name: str = Field(min_length=2, max_length=120)
    campaign_url: str = Field(min_length=8, max_length=2048)
    active: bool = True
    selectors: Selectors = Field(default_factory=Selectors)

    @field_validator("bank_name")
    @classmethod
    def normalize_bank_name(cls, value: str) -> str:
        value = re.sub(r"\s+", " ", value).strip()
        if not value:
            raise ValueError("Banka adı boş olamaz.")
        return value

    @field_validator("campaign_url")
    @classmethod
    def safe_campaign_url(cls, value: str) -> str:
        return validate_public_http_url(value)


class Source(SourceCreate):
    id: str


class CampaignRecord(BaseModel):
    id: str
    source_id: str
    bank_name: str
    title: str
    description: str = ""
    url: str = ""
    start_date: str = ""
    end_date: str = ""
    scraped_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    content_hash: str


def normalize_space(value: Any, max_length: int = 4000) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()[:max_length]
