import platform
from abc import ABC, abstractmethod
from contextlib import contextmanager

import requests
from playwright.sync_api import sync_playwright

from core.cache_manager import CacheManager
from core.listing import Listing

DEFAULT_LOCALE = "he-IL"
DEFAULT_TIMEZONE = "Asia/Jerusalem"
DEFAULT_GEOLOCATION = {"latitude": 32.0853, "longitude": 34.7818}
DEFAULT_VIEWPORT = {"width": 1280, "height": 800}
FALLBACK_CHROME_VERSION = "131.0.0.0"


class BaseScraper(ABC):
    def __init__(self, config: dict):
        self.config = config
        self.cache_manager = CacheManager(config)
        self.has_err = False

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

    def http_headers(self, locale: str = DEFAULT_LOCALE) -> dict[str, str]:
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
        locale: str = DEFAULT_LOCALE,
        timeout: int = 30,
        **kwargs,
    ) -> requests.Response:
        extra_headers = kwargs.pop("headers", {})
        headers = {**self.http_headers(locale=locale), **extra_headers}
        return requests.get(url, headers=headers, timeout=timeout, **kwargs)

    @staticmethod
    def playwright_launch_args() -> list[str]:
        return ["--disable-blink-features=AutomationControlled"]

    def build_playwright_context_options(
        self,
        browser,
        *,
        locale: str = DEFAULT_LOCALE,
    ) -> dict:
        chrome_version = self._normalize_chrome_version(browser.version)
        http_headers = self.http_headers(locale=locale)
        return {
            "user_agent": self.build_user_agent(chrome_version),
            "locale": locale,
            "timezone_id": DEFAULT_TIMEZONE,
            "geolocation": DEFAULT_GEOLOCATION,
            "permissions": ["geolocation"],
            "viewport": DEFAULT_VIEWPORT,
            "extra_http_headers": {
                key: value
                for key, value in http_headers.items()
                if key.lower() != "user-agent"
            },
        }

    @contextmanager
    def playwright_page(self, *, headless: bool = True, locale: str = DEFAULT_LOCALE):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=headless,
                args=self.playwright_launch_args(),
            )
            try:
                context = browser.new_context(
                    **self.build_playwright_context_options(browser, locale=locale)
                )
                yield context.new_page()
            finally:
                browser.close()
