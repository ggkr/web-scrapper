import logging
import re
import time
from datetime import datetime

from bs4 import BeautifulSoup

from core.base_scraper import BaseScraper
from core.listing import Listing
from core.registry import register

logger = logging.getLogger(__name__)

# Glassdoor pagination inserts _IP{n} just before .htm, e.g.:
#   …jobs-SRCH_IL.0,6_IN119_KO7,22.htm          (page 1)
#   …jobs-SRCH_IL.0,6_IN119_KO7,22_IP2.htm      (page 2)
#   …jobs-SRCH_IL.0,6_IN119_KO7,22_IP3.htm      (page 3)
_PAGE_RE = re.compile(r"(_IP\d+)?(\.htm)$", re.IGNORECASE)

DEFAULT_MAX_PAGES = 5
DEFAULT_DELAY = 3.0

# Selectors — prefer stable data-test attributes over hashed class names.
# Glassdoor uses React-generated class names that change on every deploy;
# data-test attributes are part of the QA harness and are far more stable.
_SEL_CARD = "[data-test='jobListing']"
_SEL_TITLE = "[data-test='job-title']"
_SEL_COMPANY = "[data-test='employer-short-name']"
_SEL_LOCATION = "[data-test='employer-location']"

# Fallback selectors used when data-test attributes are absent — these
# target common structural patterns rather than hashed class tokens.
_SEL_CARD_FALLBACK = "li.react-job-listing, article[data-id]"
_SEL_TITLE_FALLBACK = "a[data-test='job-title'], .job-title, h3, h2"

# The canonical job URL base; job IDs appear in the listing anchor href.
GLASSDOOR_JOB_BASE = "https://www.glassdoor.com/job-listing/"
JOB_ID_RE = re.compile(r"jobListingId=(\d+)|/(\d+)\.htm")


@register("glassdoor")
class GlassdoorScraper(BaseScraper):
    """Scrapes Glassdoor public job search pages.

    Glassdoor renders its job cards client-side via React, so plain HTTP
    requests only return a nearly-empty shell.  This plugin uses Playwright
    to render each page in a real (headless) browser before parsing.

    Pagination follows Glassdoor's ``_IP{n}.htm`` convention; the plugin
    derives subsequent page URLs by injecting (or replacing) that token in
    the base URL supplied in config — no JavaScript interaction required,
    just navigating to the correctly-constructed URL on each iteration.

    See ``plugins/glassdoor/README.md`` for how to find a valid search URL
    and for a description of every config key.
    """

    def scan(self) -> list[Listing]:
        cfg = self.config["glassdoor"]
        search_urls: list[str] = cfg.get("search_urls", [])
        max_pages: int = int(cfg.get("max_pages", DEFAULT_MAX_PAGES))
        delay: float = float(cfg.get("delay", DEFAULT_DELAY))

        logger.debug(
            "Glassdoor scan starting: %s search URL(s), max_pages=%s delay=%s",
            len(search_urls),
            max_pages,
            delay,
        )

        listings_by_id: dict[str, Listing] = {}

        with self.playwright_page(locale="en-US") as page:
            logger.debug("Playwright browser launched for Glassdoor")
            for search_url in search_urls:
                self._scan_search_url(
                    page, search_url, max_pages, delay, listings_by_id
                )

        logger.debug("Glassdoor scan complete: %s unique listings", len(listings_by_id))
        return list(listings_by_id.values())

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _scan_search_url(
        self,
        page,
        search_url: str,
        max_pages: int,
        delay: float,
        listings_by_id: dict[str, Listing],
    ) -> None:
        for page_num in range(1, max_pages + 1):
            url = self._build_page_url(search_url, page_num)
            logger.info("Fetching Glassdoor page %s: %s", page_num, url)

            try:
                html = self.fetch_rendered_page(
                    url,
                    page=page,
                    wait_for_selector=_SEL_CARD,
                    wait_for_selector_timeout=15_000,
                )
            except Exception:
                logger.exception("Failed to fetch Glassdoor page %s", url)
                self.has_err = True
                break

            listings = self._parse_page(html)
            logger.debug("Page %s returned %s listings", page_num, len(listings))

            if not listings:
                logger.debug(
                    "No job cards found — stopping pagination for %s", search_url
                )
                break

            before = len(listings_by_id)
            for listing in listings:
                listings_by_id[listing.id] = listing

            logger.debug(
                "Page %s: added %s new listings (total %s)",
                page_num,
                len(listings_by_id) - before,
                len(listings_by_id),
            )

            if page_num < max_pages and delay > 0:
                logger.debug("Sleeping %.1fs between Glassdoor pages…", delay)
                time.sleep(delay)

    @staticmethod
    def _build_page_url(base_url: str, page_num: int) -> str:
        """Insert (or replace) the ``_IP{n}`` pagination token in *base_url*.

        Page 1 uses the URL as-is (no token); pages 2+ have ``_IP{n}``
        inserted immediately before the trailing ``.htm``.

        Examples::

            _build_page_url("…KO7,22.htm", 1)  → "…KO7,22.htm"
            _build_page_url("…KO7,22.htm", 2)  → "…KO7,22_IP2.htm"
            _build_page_url("…KO7,22_IP3.htm", 4)  → "…KO7,22_IP4.htm"
        """
        # Strip any existing _IP token so we always start from the base
        clean = _PAGE_RE.sub(r"\2", base_url)
        if page_num == 1:
            return clean
        return _PAGE_RE.sub(rf"_IP{page_num}\2", clean)

    def _parse_page(self, html: str) -> list[Listing]:
        listings: list[Listing] = []
        for card in self._select_job_cards(html):
            listing = self._parse_card(card)
            if listing is not None:
                listings.append(listing)
        return listings

    @staticmethod
    def _select_job_cards(html: str) -> list:
        soup = BeautifulSoup(html, "html.parser")
        cards = soup.select(_SEL_CARD)
        if not cards:
            # Fallback: look for any element carrying a data-id that looks
            # like a job listing (Glassdoor's class names are unstable).
            cards = soup.select(_SEL_CARD_FALLBACK)
        logger.debug("Found %s job card element(s)", len(cards))
        return cards

    def _parse_card(self, card) -> Listing | None:
        try:
            # --- job ID ---------------------------------------------------
            job_id = (
                card.get("data-id")
                or card.get("data-jobid")
                or self._extract_id_from_link(card)
            )
            if not job_id:
                logger.debug("Skipping card without a detectable job ID")
                return None

            # --- title ----------------------------------------------------
            title_el = card.select_one(_SEL_TITLE) or card.select_one(
                _SEL_TITLE_FALLBACK
            )
            title = title_el.get_text(strip=True) if title_el else ""

            # --- link -----------------------------------------------------
            link = title_el.get("href")
            # leave AI code in as fallback:
            if not link or not link.startswith("https://www.glassdoor.com/"):
                link_el = card.select_one(
                    "a[href*='glassdoor.com/']"
                ) or card.select_one("a")
                link = link_el["href"] if link_el and link_el.get("href") else ""
                # Normalise relative URLs
                if link.startswith("/"):
                    link = "https://www.glassdoor.com" + link


            # --- company --------------------------------------------------
            company_el = card.select_one(_SEL_COMPANY)
            company = company_el.get_text(strip=True) if company_el else ""

            # --- location -------------------------------------------------
            location_el = card.select_one(_SEL_LOCATION)
            location = location_el.get_text(strip=True) if location_el else ""

            listing = Listing(
                id=str(job_id),
                upload_date=datetime.now(),
                fields={
                    "title": title,
                    "company": company,
                    "location": location,
                    "link": link,
                },
            )
            logger.debug("Glassdoor parsed listing: id=%s title=%r", listing.id, title)
            return listing

        except Exception:
            logger.exception("Failed to parse Glassdoor job card")
            self.has_err = True
            return None

    @staticmethod
    def _extract_id_from_link(card) -> str:
        """Pull a numeric job ID from any anchor href inside *card*."""
        for anchor in card.select("a[href]"):
            href = anchor.get("href", "")
            m = JOB_ID_RE.search(href)
            if m:
                return m.group(1) or m.group(2)
        return ""
