"""Connect to a locally running Chromium browser through loopback CDP."""
from __future__ import annotations

import asyncio
import subprocess
import time
import urllib.request
from urllib.parse import urlparse

from playwright.async_api import Browser, BrowserContext, Playwright, async_playwright

from app import config


def _is_loopback_endpoint(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and parsed.hostname in {
        "127.0.0.1", "localhost", "::1"
    } and parsed.port is not None


def _probe_endpoint(value: str) -> bool:
    if not _is_loopback_endpoint(value):
        return False
    try:
        with urllib.request.urlopen(value.rstrip("/") + "/json/version", timeout=1.0) as response:
            return response.status == 200
    except Exception:
        return False


class BrowserSession:
    """Owns a Playwright connection, and terminates only browsers it launched."""

    def __init__(self) -> None:
        self.playwright: Playwright | None = None
        self.browser: Browser | None = None
        self.context: BrowserContext | None = None
        self.process: subprocess.Popen | None = None

    async def start(self) -> BrowserContext:
        endpoint = config.BROWSER_CDP_URL
        if not _is_loopback_endpoint(endpoint):
            raise RuntimeError("CDP adresi yalnızca localhost/127.0.0.1 üzerinde olabilir.")

        self.playwright = await async_playwright().start()
        available = await asyncio.to_thread(_probe_endpoint, endpoint)
        if not available and config.AUTO_LAUNCH_BROWSER:
            self._launch_browser()
            deadline = time.monotonic() + 25
            while time.monotonic() < deadline:
                available = await asyncio.to_thread(_probe_endpoint, endpoint)
                if available:
                    break
                await asyncio.sleep(0.25)

        if not available:
            await self.close()
            raise RuntimeError(
                "Tarayıcı CDP portunda bulunamadı. Chrome/Brave'i loopback debugging portuyla "
                "başlatın veya AUTO_LAUNCH_BROWSER ve BROWSER_EXECUTABLE ayarlarını yapın."
            )

        try:
            self.browser = await self.playwright.chromium.connect_over_cdp(endpoint, timeout=10000)
            contexts = self.browser.contexts
            self.context = contexts[0] if contexts else await self.browser.new_context()
            self.context.set_default_timeout(config.NAVIGATION_TIMEOUT_MS)
            self.context.set_default_navigation_timeout(config.NAVIGATION_TIMEOUT_MS)
            return self.context
        except Exception:
            await self.close()
            raise

    def _launch_browser(self) -> None:
        if not config.BROWSER_EXECUTABLE:
            raise RuntimeError("AUTO_LAUNCH_BROWSER için BROWSER_EXECUTABLE gerekli.")
        config.BROWSER_USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
        args = [
            config.BROWSER_EXECUTABLE,
            f"--remote-debugging-port={config.BROWSER_CDP_PORT}",
            "--remote-debugging-address=127.0.0.1",
            f"--user-data-dir={config.BROWSER_USER_DATA_DIR}",
            f"--profile-directory={config.BROWSER_PROFILE_DIRECTORY}",
            "--no-first-run",
            "--no-default-browser-check",
        ]
        self.process = subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    async def close(self) -> None:
        # Stop our Playwright client; do not close a browser that the user launched.
        if self.playwright is not None:
            try:
                await self.playwright.stop()
            except Exception:
                pass
            self.playwright = None
        if self.process is not None:
            try:
                self.process.terminate()
                await asyncio.to_thread(self.process.wait, 5)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None
        self.browser = None
        self.context = None
