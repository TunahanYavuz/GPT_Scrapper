"""Read-only extraction from publicly accessible campaign pages."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

from playwright.async_api import BrowserContext, Page

from app import config
from app.models import CampaignRecord, Source, normalize_space, validate_public_http_url
from app.path_guard import looks_like_private_banking_area
from app.storage import campaign_hash, make_campaign_id


class PageBlockedError(RuntimeError):
    """Raised when a page requests authentication or human verification."""


def _safe_link(base_url: str, href: str | None) -> str:
    if not href:
        return ""
    candidate = urljoin(base_url, href.strip())
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return ""
    # We record links but never automatically visit campaign destination links.
    return candidate[:2048]


async def _is_access_gate(page: Page, status: int | None) -> str | None:
    if status in {401, 403, 407, 429}:
        return f"Sunucu erişimi reddetti veya hız sınırına ulaşıldı (HTTP {status})."
    title = (await page.title()).lower()
    body = ""
    try:
        body = (await page.locator("body").inner_text(timeout=1500)).lower()[:5000]
    except Exception:
        pass
    gate_phrases = (
        "verify you are human",
        "checking your browser before accessing",
        "unusual traffic",
        "automated requests",
        "access denied",
        "robot or human",
        "complete the security check",
    )
    if any(phrase in title or phrase in body for phrase in gate_phrases):
        return "Sayfada güvenlik doğrulaması/erişim engeli algılandı; otomasyon durduruldu."
    try:
        if await page.locator(
            'input[type="password"], iframe[src*="captcha"], [id*="captcha"], '
            '[class*="captcha"], #challenge-form'
        ).count():
            return "Giriş veya CAPTCHA öğesi algılandı; otomasyon durduruldu."
    except Exception:
        pass
    return None


async def _first_text(container, selector: str, limit: int = 4000) -> str:
    if not selector:
        return ""
    try:
        locator = container.locator(selector).first
        if await locator.count():
            return normalize_space(await locator.inner_text(timeout=1500), limit)
    except Exception:
        return ""
    return ""


async def _first_href(container, selector: str, base_url: str) -> str:
    if not selector:
        selector = "a"
    try:
        locator = container.locator(selector).first
        if await locator.count():
            return _safe_link(base_url, await locator.get_attribute("href"))
    except Exception:
        return ""
    return ""


async def _extract_page(source: Source, page: Page, page_url: str) -> list[CampaignRecord]:
    selectors = source.selectors
    cards = None
    if selectors.card:
        try:
            cards = page.locator(selectors.card)
            card_count = min(await cards.count(), config.MAX_CAMPAIGNS_PER_SOURCE)
        except Exception:
            card_count = 0
    else:
        cards = None
        card_count = 0

    entries: list[tuple[object, bool]] = []
    if cards is not None and card_count > 0:
        entries = [(cards.nth(i), False) for i in range(card_count)]
    else:
        heading_selector = selectors.title or "main h2, main h3, h2, h3"
        try:
            headings = page.locator(heading_selector)
            heading_count = min(await headings.count(), config.MAX_CAMPAIGNS_PER_SOURCE)
            for i in range(heading_count):
                heading = headings.nth(i)
                try:
                    entries.append((heading.locator("xpath=.."), True))
                except Exception:
                    entries.append((heading, True))
        except Exception:
            entries = []

    results: list[CampaignRecord] = []
    seen_in_page: set[str] = set()
    for container, is_heading in entries:
        try:
            if is_heading:
                title = await _first_text(container, selectors.title or "h2, h3")
                if not title:
                    title = await _first_text(container, "body")
                # Use a short parent excerpt rather than saving full page text.
                description = await _first_text(container, selectors.description or "p", 1800)
            else:
                title = await _first_text(container, selectors.title or "h2, h3, h4")
                description = await _first_text(container, selectors.description or "p", 1800)

            title = normalize_space(title, 300)
            if not title or len(title) < 3 or title in seen_in_page:
                continue
            seen_in_page.add(title)

            link = await _first_href(container, selectors.link or "a", page_url)
            start_date = await _first_text(container, selectors.start_date, 120) if selectors.start_date else ""
            end_date = await _first_text(container, selectors.end_date, 120) if selectors.end_date else ""
            # Do not visit extracted links. Store only a URL field for downstream review.
            digest = campaign_hash(source.id, title, link)
            results.append(CampaignRecord(
                id=make_campaign_id(digest),
                source_id=source.id,
                bank_name=source.bank_name,
                title=title,
                description=description,
                url=link,
                start_date=start_date,
                end_date=end_date,
                scraped_at=datetime.now(timezone.utc).isoformat(),
                content_hash=digest,
            ))
            if len(results) >= config.MAX_CAMPAIGNS_PER_SOURCE:
                break
        except Exception:
            # A malformed card should not prevent other cards being read.
            continue
    return results


async def scrape_source(context: BrowserContext, source: Source) -> list[CampaignRecord]:
    if not source.active:
        return []

    validate_public_http_url(source.campaign_url, resolve_host=True)
    if looks_like_private_banking_area(source.campaign_url):
        raise PageBlockedError("URL internet şubesi/hesap alanına benziyor; herkese açık kampanya liste sayfası kullanın.")
    original = urlparse(source.campaign_url)
    original_host = (original.hostname or "").lower()
    page = await context.new_page()
    try:
        response = await page.goto(source.campaign_url, wait_until="domcontentloaded")
        if response is not None and response.status in {401, 403, 407, 429}:
            raise PageBlockedError(
                f"Sunucu erişimi reddetti veya hız sınırına ulaşıldı (HTTP {response.status})."
            )
        final = urlparse(page.url)
        if final.scheme not in {"http", "https"} or (final.hostname or "").lower() != original_host:
            raise PageBlockedError("Sayfa farklı bir hosta yönlendi; güvenlik için gezinme durduruldu.")
        if looks_like_private_banking_area(page.url):
            raise PageBlockedError("Yönlendirme internet şubesi/hesap alanına gitti; içerik çıkarımı durduruldu.")
        gate_message = await _is_access_gate(page, response.status if response else None)
        if gate_message:
            raise PageBlockedError(gate_message)

        try:
            await page.wait_for_load_state("networkidle", timeout=2500)
        except Exception:
            pass

        items = await _extract_page(source, page, page.url)
        # Bounded pagination: follow only a same-host rel=next or configured selector.
        next_selector = getattr(source.selectors, "next_page", "") or 'a[rel="next"]'
        for _ in range(4):
            if len(items) >= config.MAX_CAMPAIGNS_PER_SOURCE:
                break
            try:
                next_link = await _first_href(page, next_selector, page.url)
                if not next_link:
                    break
                next_url = urlparse(next_link)
                if next_url.scheme not in {"http", "https"} or (next_url.hostname or "").lower() != original_host:
                    break
                if next_link == page.url:
                    break
                response = await page.goto(next_link, wait_until="domcontentloaded")
                if response is not None and response.status in {401, 403, 407, 429}:
                    raise PageBlockedError(f"Sonraki sayfa HTTP {response.status} döndürdü.")
                if (urlparse(page.url).hostname or "").lower() != original_host:
                    raise PageBlockedError("Sayfalama farklı bir hosta yönlendi.")
                if looks_like_private_banking_area(page.url):
                    raise PageBlockedError("Sayfalama bir hesap/portal alanına yönlendi; tarama durduruldu.")
                gate_message = await _is_access_gate(page, response.status if response else None)
                if gate_message:
                    raise PageBlockedError(gate_message)
                items.extend(await _extract_page(source, page, page.url))
                await asyncio.sleep(config.PAGE_DELAY_SECONDS)
            except PageBlockedError:
                raise
            except Exception:
                break

        deduped: dict[str, CampaignRecord] = {}
        for item in items[: config.MAX_CAMPAIGNS_PER_SOURCE]:
            deduped[item.content_hash] = item
        return list(deduped.values())
    finally:
        await page.close()
