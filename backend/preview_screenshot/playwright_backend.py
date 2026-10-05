import asyncio
import sys
import threading
from typing import Optional

from playwright.async_api import (
    Browser,
    Playwright,
    TimeoutError as PlaywrightTimeoutError,
    async_playwright,
)

from preview_screenshot.base import VIEWPORT_SIZES

PAGE_LOAD_TIMEOUT_MS = 15000
RENDER_SETTLE_MS = 250


class PlaywrightBackend:
    """Default backend: renders in local headless Chromium.

    Runs locally, so the page can load assets served from localhost
    (e.g. /local-assets/ URLs) that an external screenshot API cannot reach.
    Holds one shared browser, launched lazily and reused across captures.
    Operates in a dedicated event loop thread with ProactorEventLoop on Windows
    to ensure full compatibility with uvicorn and other server loops.
    """

    def __init__(self) -> None:
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._lock: Optional[asyncio.Lock] = None
        self._worker_loop: Optional[asyncio.AbstractEventLoop] = None
        self._worker_thread: Optional[threading.Thread] = None

    def _ensure_worker(self) -> asyncio.AbstractEventLoop:
        if self._worker_loop is None or self._worker_loop.is_closed():
            if sys.platform == "win32":
                self._worker_loop = asyncio.ProactorEventLoop()
            else:
                self._worker_loop = asyncio.new_event_loop()
            self._lock = None
            self._worker_thread = threading.Thread(
                target=self._worker_loop.run_forever,
                daemon=True,
                name="playwright-worker",
            )
            self._worker_thread.start()
        return self._worker_loop

    async def _get_browser(self) -> Browser:
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            if self._browser is None or not self._browser.is_connected():
                if self._playwright is None:
                    self._playwright = await async_playwright().start()
                # --no-sandbox: Chromium refuses to launch as root (the user in
                # most containers/hosted Linux) unless the sandbox is disabled.
                self._browser = await self._playwright.chromium.launch(
                    headless=True,
                    args=["--no-sandbox"],
                )
            return self._browser

    async def _do_available(self) -> bool:
        """Launch (and warm up) Chromium on the worker loop; report whether it works."""
        try:
            await self._get_browser()
            print("[screenshot_preview] Chromium available - tool enabled.")
            return True
        except Exception as exc:
            err_msg = str(exc).encode("ascii", "replace").decode("ascii")
            print(
                "[screenshot_preview] Chromium unavailable - tool disabled. "
                f"Install it with `playwright install chromium`. Cause: {err_msg}"
            )
            return False

    async def _do_capture(
        self,
        html: str,
        device: str = "desktop",
        full_page: bool = True,
    ) -> bytes:
        browser = await self._get_browser()
        width, height = VIEWPORT_SIZES.get(device, VIEWPORT_SIZES["desktop"])
        page = await browser.new_page(
            viewport={"width": width, "height": height},
            device_scale_factor=1,
        )
        try:
            try:
                await page.set_content(
                    html,
                    wait_until="networkidle",
                    timeout=PAGE_LOAD_TIMEOUT_MS,
                )
            except PlaywrightTimeoutError:
                # Content is already set; capture whatever rendered if the
                # network never settles (e.g. pages that poll).
                pass
            try:
                await page.evaluate("document.fonts.ready")
            except Exception:
                pass
            await page.wait_for_timeout(RENDER_SETTLE_MS)
            return await page.screenshot(full_page=full_page, type="png")
        finally:
            await page.close()

    async def _do_capture_url(
        self,
        url: str,
        device: str = "desktop",
        full_page: bool = True,
    ) -> bytes:
        browser = await self._get_browser()
        width, height = VIEWPORT_SIZES.get(device, VIEWPORT_SIZES["desktop"])
        page = await browser.new_page(
            viewport={"width": width, "height": height},
            device_scale_factor=1,
        )
        try:
            try:
                await page.goto(url, wait_until="load", timeout=30000)
            except PlaywrightTimeoutError:
                pass
            try:
                await page.evaluate("document.fonts.ready")
            except Exception:
                pass
            await page.wait_for_timeout(RENDER_SETTLE_MS)
            return await page.screenshot(full_page=full_page, type="png")
        finally:
            await page.close()

    async def available(self) -> bool:
        """Check whether the active backend can run here."""
        loop = self._ensure_worker()
        future = asyncio.run_coroutine_threadsafe(self._do_available(), loop)
        try:
            curr_loop = asyncio.get_running_loop()
            return await asyncio.wrap_future(future, loop=curr_loop)
        except RuntimeError:
            return future.result()

    async def capture(
        self,
        html: str,
        device: str = "desktop",
        full_page: bool = True,
    ) -> bytes:
        """Render HTML to PNG via headless Chromium."""
        loop = self._ensure_worker()
        future = asyncio.run_coroutine_threadsafe(
            self._do_capture(html, device, full_page), loop
        )
        try:
            curr_loop = asyncio.get_running_loop()
            return await asyncio.wrap_future(future, loop=curr_loop)
        except RuntimeError:
            return future.result()

    async def capture_url(
        self,
        url: str,
        device: str = "desktop",
        full_page: bool = True,
    ) -> bytes:
        """Render a remote URL to PNG via headless Chromium."""
        loop = self._ensure_worker()
        future = asyncio.run_coroutine_threadsafe(
            self._do_capture_url(url, device, full_page), loop
        )
        try:
            curr_loop = asyncio.get_running_loop()
            return await asyncio.wrap_future(future, loop=curr_loop)
        except RuntimeError:
            return future.result()
