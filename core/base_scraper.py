import logging
import platform
from abc import ABC, abstractmethod
from contextlib import contextmanager

import requests
from playwright.sync_api import Page, sync_playwright
from playwright_stealth import Stealth

from core.cache_manager import CacheManager
from core.listing import Listing

logger = logging.getLogger(__name__)

DEFAULT_LOCALE = "he-IL"
DEFAULT_TIMEZONE = "Asia/Jerusalem"
DEFAULT_GEOLOCATION = {"latitude": 32.0853, "longitude": 34.7818}
DEFAULT_VIEWPORT = {"width": 1280, "height": 800}
FALLBACK_CHROME_VERSION = "131.0.0.0"


class BaseScraper(ABC):
    """Base class for scraper plugins.

    BaseScraper owns *fetching*: plain HTTP requests and Playwright-rendered
    page loads. Plugins are responsible for building the URL(s) they need
    (including any pagination strategy - the right approach varies enough
    per site that it's left to the plugin) and parsing fetched content into
    `Listing` objects - see `fetch_static_page` and `fetch_rendered_page`
    below.
    """

    def __init__(
        self,
        config: dict,
        stealth: bool = False,
        headless: bool = True,
        locale: str = DEFAULT_LOCALE,
        timezone: str = DEFAULT_TIMEZONE,
        geolocation: dict = DEFAULT_GEOLOCATION,
        viewport: dict = DEFAULT_VIEWPORT,
    ):
        self.config = config
        self.cache_manager = CacheManager(config)
        self.has_err = False
        self.stealth = stealth
        self.headless = headless  # already the new mode by default
        self.locale = locale
        self.timezone = timezone
        self.geolocation = geolocation
        self.viewport = viewport

    @abstractmethod
    def scan(self) -> list[Listing]:
        pass

    @staticmethod
    def _platform_user_agent_token() -> str:
        system = platform.system()
        if system == "Darwin":
            return "Macintosh; Intel Mac OS X 10_15_7"
        if system == "Windows":
            release = platform.release()
            if release == "10":
                return "Windows NT 10.0; Win64; x64"
            if release == "11":
                return "Windows NT 10.0; Win64; x64"
            return f"Windows NT {release}; Win64; x64"
        machine = platform.machine().lower()
        if machine in {"x86_64", "amd64"}:
            return "X11; Linux x86_64"
        if machine in {"aarch64", "arm64"}:
            return "X11; Linux aarch64"
        return f"X11; Linux {machine}"

    @classmethod
    def _normalize_chrome_version(cls, version: str) -> str:
        major = version.split(".", maxsplit=1)[0]
        if not major.isdigit():
            return FALLBACK_CHROME_VERSION
        return f"{major}.0.0.0"

    @classmethod
    def build_user_agent(cls, chrome_version: str | None = None) -> str:
        version = chrome_version or FALLBACK_CHROME_VERSION
        token = cls._platform_user_agent_token()
        return (
            f"Mozilla/5.0 ({token}) "
            f"AppleWebKit/537.36 (KHTML, like Gecko) "
            f"Chrome/{version} Safari/537.36"
        )

    def http_headers(self, locale: str = None) -> dict[str, str]:
        if not locale:
            locale = self.locale
        language = locale.split("-", maxsplit=1)[0]
        return {
            "User-Agent": self.build_user_agent(),
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,image/apng,*/*;q=0.8"
            ),
            "Accept-Language": f"{locale},{language};q=0.9,en-US;q=0.8,en;q=0.7",
            "Cache-Control": "max-age=0",
            "Upgrade-Insecure-Requests": "1",
        }

    def http_get(
        self,
        url: str,
        *,
        timeout: int = 30,
        **kwargs,
    ) -> requests.Response:
        extra_headers = kwargs.pop("headers", {})
        headers = {**self.http_headers(locale=self.locale), **extra_headers}
        return requests.get(url, headers=headers, timeout=timeout, **kwargs)

    def fetch_static_page(
        self,
        url: str,
        *,
        timeout: int = 30,
    ) -> str:
        """Fetch a URL's raw response body via a plain HTTP GET - the default,
        lightweight way to get a page's content when nothing needs to run
        client-side JavaScript to produce it."""
        response = self.http_get(url, locale=self.locale, timeout=timeout)
        response.raise_for_status()
        return response.text

    @staticmethod
    def playwright_launch_args() -> list[str]:
        return ["--disable-blink-features=AutomationControlled"]

    def build_playwright_context_options(
        self,
        browser,
    ) -> dict:
        chrome_version = self._normalize_chrome_version(browser.version)
        http_headers = self.http_headers(locale=self.locale)
        return {
            "user_agent": self.build_user_agent(chrome_version),
            "locale": self.locale,
            "timezone_id": self.timezone,
            "geolocation": self.geolocation,
            "permissions": ["geolocation"],
            "viewport": self.viewport,
            "extra_http_headers": {
                key: value
                for key, value in http_headers.items()
                if key.lower() != "user-agent"
            },
        }

    @contextmanager
    def playwright_page(
        self,
    ):
        """Yields a live Playwright `Page` for plugins that need to interact with
        a real browser directly (locators, clicks, waiting on lazy-loaded
        elements, reading `__NEXT_DATA__`, etc.), or that want to reuse one
        browser across several `fetch_rendered_page()` calls. Prefer
        `fetch_rendered_page()` on its own when a plugin only needs a single
        page's resulting HTML content."""
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=self.headless,
                args=self.playwright_launch_args(),
            )
            try:
                context = browser.new_context(
                    **self.build_playwright_context_options(browser)
                )
                if self.stealth:
                    stealth_obj = Stealth()
                    stealth_obj.apply_stealth_sync(context)
                yield context.new_page()
            finally:
                browser.close()

    def fetch_rendered_page(
        self,
        url: str,
        *,
        page: Page | None = None,
        wait_for_selector: str | None = None,
        wait_for_selector_timeout: int = 10000,
        goto_timeout: int = 60000,
        headless: bool = True,
    ) -> str:
        """Fetch a URL's fully-rendered HTML via a real Playwright browser (for
        pages that need JS execution to produce their content). Pass an
        already-open `page` from an active `playwright_page()` session to reuse
        one browser across multiple calls; otherwise a short-lived browser is
        launched just for this call."""
        if page is not None:
            return self._goto_and_get_content(
                page, url, wait_for_selector, wait_for_selector_timeout, goto_timeout
            )
        with self.playwright_page(headless=headless, locale=self.locale) as own_page:
            return self._goto_and_get_content(
                own_page,
                url,
                wait_for_selector,
                wait_for_selector_timeout,
                goto_timeout,
            )

    @staticmethod
    def _goto_and_get_content(
        page: Page,
        url: str,
        wait_for_selector: str | None,
        wait_for_selector_timeout: int,
        goto_timeout: int,
    ) -> str:
        page.goto(url, wait_until="load", timeout=goto_timeout)
        if wait_for_selector:
            try:
                page.wait_for_selector(
                    wait_for_selector, timeout=wait_for_selector_timeout
                )
            except Exception:
                logger.debug(
                    "Timeout waiting for selector %r on %s", wait_for_selector, url
                )
        return page.content()
