import logging
import re
import time
from datetime import datetime
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from bs4 import BeautifulSoup

from core.base_scraper import BaseScraper
from core.listing import Listing
from core.registry import register

logger = logging.getLogger(__name__)

DEFAULT_PAGE_SIZE = 25
DEFAULT_MAX_PAGES = 4
JOB_ID_RE = re.compile(r"jobPosting:(\d+)")


@register("linkedin")
class LinkedInScraper(BaseScraper):
    """Parses LinkedIn's public "guest" job search endpoint
    (jobs-guest/jobs/api/seeMoreJobPostings/search). Fetching each page is
    delegated to BaseScraper.fetch_static_page(); this class owns its own
    pagination strategy (offset-based, stop once a page returns fewer than
    `page_size` results) since that's specific to how this endpoint paginates
    - see the plugin README for how to discover a guest search URL.
    """

    def scan(self) -> list[Listing]:
        cfg = self.config["linkedin"]
        listings_by_id: dict[str, Listing] = {}

        search_urls = cfg.get("search_urls", [])
        page_size = int(cfg.get("page_size", DEFAULT_PAGE_SIZE))
        max_pages = int(cfg.get("max_pages", DEFAULT_MAX_PAGES))
        delay = float(cfg.get("delay", 1.5))

        logger.debug(
            "LinkedIn guest scan starting: %s search URLs, page_size=%s max_pages=%s",
            len(search_urls),
            page_size,
            max_pages,
        )

        for search_url in search_urls:
            self._scan_search_url(
                search_url, page_size, max_pages, delay, listings_by_id
            )

        logger.debug(
            "LinkedIn guest scan complete: %s unique listings", len(listings_by_id)
        )
        return list(listings_by_id.values())

    def _scan_search_url(
        self,
        search_url: str,
        page_size: int,
        max_pages: int,
        delay: float,
        listings_by_id: dict[str, Listing],
    ) -> None:
        for page_num in range(max_pages):
            start = page_num * page_size
            page_url = self._set_start_param(search_url, start)

            try:
                logging.info("Fetching LinkedIn guest jobs page: %s", page_url)
                content = self.fetch_static_page(page_url)
            except Exception:
                logging.exception("Failed to fetch LinkedIn guest page %s", page_url)
                self.has_err = True
                break

            listings = self._parse_page(content)
            logger.debug("Page start=%s returned %s listings", start, len(listings))
            if not listings:
                logger.debug(
                    "No more job cards, stopping pagination for %s", search_url
                )
                break

            for listing in listings:
                listings_by_id[listing.id] = listing

            if len(listings) < page_size:
                logger.debug(
                    "Short page (%s < %s), assuming last page", len(listings), page_size
                )
                break

            if delay > 0 and page_num < max_pages - 1:
                logger.debug("Sleeping for %s seconds to respect rate limits...", delay)
                time.sleep(delay)

    @staticmethod
    def _set_start_param(url: str, start: int) -> str:
        parsed = urlparse(url)
        query = parse_qs(parsed.query, keep_blank_values=True)
        query["start"] = [str(start)]
        flat_query = {key: values[0] for key, values in query.items()}
        return urlunparse(parsed._replace(query=urlencode(flat_query)))

    def _parse_page(self, html_text: str) -> list[Listing]:
        listings = []
        for card in self._select_job_cards(html_text):
            listing = self._parse_card(card)
            if listing is not None:
                listings.append(listing)
        return listings

    @staticmethod
    def _select_job_cards(html_text: str) -> list:
        soup = BeautifulSoup(html_text, "html.parser")
        cards = soup.select("li")
        return [
            card
            for card in cards
            if card.select_one("a.base-card__full-link, a.base-search-card__full-link")
        ]

    def _parse_card(self, card) -> Listing | None:
        try:
            link_el = card.select_one(
                "a.base-card__full-link, a.base-search-card__full-link"
            )
            link = link_el["href"].split("?")[0] if link_el else ""

            entity_urn = card.get("data-entity-urn", "")
            match = JOB_ID_RE.search(entity_urn)
            if match:
                job_id = match.group(1)
            elif link:
                job_id = link.rstrip("/").split("-")[-1]
            else:
                logger.debug("Skipping job card without an id or link")
                return None

            title_el = card.select_one(
                "h3.base-search-card__title, h3.base-card__title"
            )
            title = title_el.get_text(strip=True) if title_el else ""

            company_el = card.select_one(
                "h4.base-search-card__subtitle a, h4.base-search-card__subtitle"
            )
            company = company_el.get_text(strip=True) if company_el else ""

            location_el = card.select_one("span.job-search-card__location")
            location = location_el.get_text(strip=True) if location_el else ""

            time_el = card.select_one("time")
            upload_date = self._parse_upload_date(
                time_el.get("datetime") if time_el else None
            )

            listing = Listing(
                id=job_id,
                upload_date=upload_date,
                fields={
                    "title": title,
                    "company": company,
                    "location": location,
                    "link": link,
                },
            )
            logger.debug(
                "LinkedIn guest parsed listing: id=%s url=%s", listing.id, listing.url
            )
            return listing
        except Exception:
            logging.exception("Failed to parse LinkedIn guest job card")
            self.has_err = True
            return None

    @staticmethod
    def _parse_upload_date(value: str | None) -> datetime:
        if value:
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(
                    tzinfo=None
                )
            except ValueError:
                pass
        return datetime.now()
