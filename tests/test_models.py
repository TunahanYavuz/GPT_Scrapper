import pytest
from pydantic import ValidationError

from app.models import SourceCreate, validate_public_http_url


def test_normalizes_bank_name_and_selectors():
    source = SourceCreate(
        bank_name="  Örnek   Banka ",
        campaign_url="https://8.8.8.8/campaigns",
        selectors={"card": "article", "next_page": "a.next"},
    )
    assert source.bank_name == "Örnek Banka"
    assert source.selectors.card == "article"
    assert source.selectors.next_page == "a.next"


@pytest.mark.parametrize("url", [
    "javascript:alert(1)",
    "file:///etc/passwd",
    "http://localhost/admin",
    "http://127.0.0.1:8000/",
    "http://192.168.1.1/",
    "http://user:secret@example.com/path",
])
def test_rejects_unsafe_source_urls(url):
    with pytest.raises(ValueError):
        validate_public_http_url(url)


def test_rejects_invalid_bank_name():
    with pytest.raises(ValidationError):
        SourceCreate(bank_name=" ", campaign_url="https://8.8.8.8/campaigns")


def test_accepts_public_ip_literal():
    assert validate_public_http_url("https://8.8.8.8/campaigns") == "https://8.8.8.8/campaigns"
