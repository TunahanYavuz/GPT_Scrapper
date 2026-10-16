"""Conservative path checks for URLs that look like authenticated banking areas."""
from __future__ import annotations

from urllib.parse import unquote, urlparse

_RESTRICTED_SEGMENTS = {
    "login", "signin", "sign-in", "auth", "giris", "giriş", "oturum",
    "internet-subesi", "internet-sube", "internet-bankaciligi", "internet-bankacilik",
    "online-banking", "onlinebanking", "dashboard", "portal", "account-summary",
    "account-details", "accounts-summary", "transaction-history", "transactions",
    "hesap-ozeti", "hesap-hareketleri", "hesaplarim", "hesabim", "hesabım",
    "hesaplarım", "profilim", "profile", "musteri-paneli", "müşteri-paneli",
    "customer-portal", "client-portal",
}


def looks_like_private_banking_area(value: str) -> bool:
    """Return True for common login, account-summary and internet-branch path segments."""
    path = unquote(urlparse(value).path).lower()
    segments = {segment.strip().lower() for segment in path.split("/") if segment}
    return bool(segments & _RESTRICTED_SEGMENTS)
