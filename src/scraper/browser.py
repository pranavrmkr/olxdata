"""
Playwright browser management with stealth configuration for OLX scraping.
"""

import asyncio
import random
from typing import Optional, List
from playwright.async_api import async_playwright, Browser, BrowserContext, Page, Playwright
from playwright_stealth import Stealth

from ..utils.logging import get_logger
from ..utils.helpers import random_delay, sleep_random

logger = get_logger(__name__)


# Realistic user agents for rotation
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
]


class StealthBrowser:
    """Manages a stealth-configured Playwright browser for scraping."""

    def __init__(
        self,
        headless: bool = True,
        timeout: int = 30000,
        rotate_user_agents: bool = True,
        viewport: Optional[dict] = None,
    ):
        self.headless = headless
        self.timeout = timeout
        self.rotate_user_agents = rotate_user_agents
        self.viewport = viewport or {"width": 1366, "height": 768}

        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._pages: List[Page] = []

    async def start(self) -> None:
        """Start the browser with stealth configuration."""
        logger.info("Starting stealth browser", headless=self.headless)

        self._playwright = await async_playwright().start()

        # Launch browser with realistic settings
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-web-security",
                "--disable-features=IsolateOrigins,site-per-process",
                "--disable-site-isolation-trials",
                "--disable-infobars",
                "--disable-breakpad",
                "--disable-component-extensions-with-background-pages",
                "--disable-default-apps",
                "--disable-extensions",
                "--disable-sync",
                "--disable-translate",
                "--hide-scrollbars",
                "--mute-audio",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-background-networking",
                "--disable-background-timer-throttling",
                "--disable-renderer-backgrounding",
                "--disable-ipc-flooding-protection",
            ]
        )

        # Create context with realistic settings
        user_agent = random.choice(USER_AGENTS) if self.rotate_user_agents else USER_AGENTS[0]

        self._context = await self._browser.new_context(
            viewport=self.viewport,
            user_agent=user_agent,
            locale="en-IN",
            timezone_id="Asia/Kolkata",
            geolocation={"latitude": 28.6139, "longitude": 77.2090},
            permissions=["geolocation"],
            color_scheme="light",
            reduced_motion="no-preference",
            forced_colors="none",
            device_scale_factor=1,
            is_mobile=False,
            has_touch=False,
            java_script_enabled=True,
            bypass_csp=True,
            ignore_https_errors=True,
            extra_http_headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "Accept-Language": "en-IN,en;q=0.9,hi;q=0.8",
                "Accept-Encoding": "gzip, deflate, br",
                "Cache-Control": "max-age=0",
                "Sec-Ch-Ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
                "Sec-Ch-Ua-Mobile": "?0",
                "Sec-Ch-Ua-Platform": '"Windows"',
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
                "Upgrade-Insecure-Requests": "1",
            }
        )

        # Apply stealth using Stealth class
        stealth = Stealth()
        await stealth.apply_stealth_async(self._context)

        # Add scripts to hide automation
        await self._context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
            window.chrome = { runtime: {} };
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5]
            });
            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-IN', 'en', 'hi']
            });
        """)

        logger.info("Stealth browser started successfully")

    async def new_page(self) -> Page:
        """Create a new page with stealth applied."""
        if not self._context:
            await self.start()

        page = await self._context.new_page()
        page.set_default_timeout(self.timeout)
        page.set_default_navigation_timeout(self.timeout)

        # Apply stealth to each page
        stealth = Stealth()
        await stealth.apply_stealth_async(page)

        # Track page for cleanup
        self._pages.append(page)

        return page

    async def close_page(self, page: Page) -> None:
        """Close a specific page."""
        if page in self._pages:
            self._pages.remove(page)
        await page.close()

    async def close(self) -> None:
        """Close browser and cleanup."""
        logger.info("Closing browser")

        # Close all pages
        for page in self._pages:
            try:
                await page.close()
            except Exception:
                pass
        self._pages.clear()

        if self._context:
            await self._context.close()
            self._context = None

        if self._browser:
            await self._browser.close()
            self._browser = None

        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

        logger.info("Browser closed")

    async def __aenter__(self) -> "StealthBrowser":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    @property
    def browser(self) -> Optional[Browser]:
        return self._browser

    @property
    def context(self) -> Optional[BrowserContext]:
        return self._context

    @property
    def is_running(self) -> bool:
        return self._browser is not None and self._browser.is_connected()


class RateLimitedBrowser(StealthBrowser):
    """Stealth browser with built-in rate limiting."""

    def __init__(
        self,
        headless: bool = True,
        timeout: int = 30000,
        rotate_user_agents: bool = True,
        min_delay: float = 3.0,
        max_delay: float = 8.0,
    ):
        super().__init__(headless, timeout, rotate_user_agents)
        self.min_delay = min_delay
        self.max_delay = max_delay
        self._last_request_time: float = 0

    async def navigate_with_delay(self, page: Page, url: str, **kwargs) -> None:
        """Navigate to URL with random delay."""
        import time

        # Apply delay since last request
        elapsed = time.time() - self._last_request_time
        if elapsed > 0:
            min_wait = self.min_delay - elapsed
            if min_wait > 0:
                await sleep_random(min_wait, self.max_delay)

        # Navigate
        response = await page.goto(url, wait_until="domcontentloaded", **kwargs)
        self._last_request_time = time.time()

        # Wait for page to settle
        await sleep_random(1.0, 3.0)

        return response