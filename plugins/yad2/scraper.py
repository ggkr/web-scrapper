import json
import logging
from datetime import datetime
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from bs4 import BeautifulSoup

from core.base_scraper import BaseScraper
from core.listing import Listing
from core.registry import register

logger = logging.getLogger(__name__)

ITEM_BASE = "https://www.yad2.co.il/realestate/item"
FEED_SECTIONS = (
    "private",
    "agency",
    "yad1",
    "platinum",
    "kingOfTheHar",
    "trio",
    "booster",
    "leadingBroker",
)


@register("yad2")
class Yad2Scraper(BaseScraper):
    """Parses Yad2 real-estate search results embedded in each page's
    server-rendered __NEXT_DATA__ blob. Fetching (loading each search/item
    page in a real browser, since Yad2 has bot protection that blocks plain
    HTTP requests) is handled by BaseScraper.fetch_rendered_page(); this
    class only parses the fetched HTML into Listings.

    Pagination here can't use BaseScraper.fetch_paginated() directly, since
    the total page count is only known after parsing the first page's
    __NEXT_DATA__ - so this plugin drives its own pagination loop, using
    fetch_rendered_page() for each individual fetch.
    """

    def scan(self) -> list[Listing]:
        yad2 = self.config["yad2"]
        listings_by_id: dict[str, Listing] = {}

        logger.debug(
            "Yad2 scan starting: %s search URLs, fetch_item_details=%s",
            len(yad2["search_urls"]),
            yad2.get("fetch_item_details", False),
        )

        with self.playwright_page() as page:
            logger.debug("Playwright browser launched for Yad2")
            for search_url in yad2["search_urls"]:
                self._scan_search_url(page, search_url, yad2, listings_by_id)

            if yad2.get("fetch_item_details"):
                self._enrich_with_item_details(page, listings_by_id, yad2)

        logger.debug("Yad2 scan complete: %s unique listings", len(listings_by_id))
        return list(listings_by_id.values())

    def _scan_search_url(
        self, page, search_url: str, yad2: dict, listings_by_id: dict[str, Listing]
    ):
        query_key = yad2["query_key"]
        before_count = len(listings_by_id)
        feed = self._load_feed_data(page, search_url, query_key)
        self._add_feed_items(feed, listings_by_id)
        logger.debug(
            "Yad2 search URL parsed: added %s listings (total %s) from %s",
            len(listings_by_id) - before_count,
            len(listings_by_id),
            search_url,
        )

        if yad2.get("paginate", True) is False:
            logger.debug("Pagination disabled for %s", search_url)
            return

        pagination = feed.get("pagination") or {}
        total_pages = int(pagination.get("totalPages") or 1)
        if total_pages <= 1:
            logger.debug("Single page result for %s", search_url)
            return

        logging.info("Yad2 pagination: %s pages for %s", total_pages, search_url)
        parsed = urlparse(search_url)
        query = parse_qs(parsed.query, keep_blank_values=True)
        for page_num in range(2, total_pages + 1):
            page_query = {key: values[0] for key, values in query.items()}
            page_query["page"] = str(page_num)
            page_url = urlunparse(parsed._replace(query=urlencode(page_query)))
            logger.debug(
                "Yad2 fetching page %s/%s: %s", page_num, total_pages, page_url
            )
            next_feed = self._load_feed_data(page, page_url, query_key)
            self._add_feed_items(next_feed, listings_by_id)

    def _add_feed_items(self, feed: dict, listings_by_id: dict[str, Listing]):
        items = self._collect_feed_items(feed)
        logger.debug("Processing %s feed items", len(items))
        for item in items:
            listing = self._parse_feed_item(item)
            if listing is not None:
                listings_by_id[listing.id] = listing
                logger.debug(
                    "Yad2 parsed listing: id=%s url=%s", listing.id, listing.url
                )

    def _load_feed_data(self, page, url: str, query_key: str) -> dict:
        logging.info("Fetching Yad2 feed: %s", url)
        content = self.fetch_rendered_page(
            url, page=page, wait_for_selector="#__NEXT_DATA__"
        )
        logger.debug("Page loaded, extracting __NEXT_DATA__ query_key=%s", query_key)
        return self._extract_next_data(content, query_key)

    @staticmethod
    def _extract_next_data(content: str, query_key: str) -> dict:
        soup = BeautifulSoup(content, "html.parser")
        script_tag = soup.select_one("#__NEXT_DATA__")
        if script_tag is None or not script_tag.string:
            raise RuntimeError("__NEXT_DATA__ not found on Yad2 page (bot protection?)")

        parsed = json.loads(script_tag.string)
        queries = (
            parsed.get("props", {})
            .get("pageProps", {})
            .get("dehydratedState", {})
            .get("queries", [])
        )
        for query in queries:
            query_key_value = query.get("queryKey")
            if isinstance(query_key_value, list) and query_key_value[0] == query_key:
                data = query.get("state", {}).get("data")
                if isinstance(data, dict):
                    logger.debug('Found __NEXT_DATA__ query "%s"', query_key)
                    return data

        available = [
            query.get("queryKey")[0]
            for query in queries
            if isinstance(query.get("queryKey"), list) and query.get("queryKey")
        ]
        logger.debug("Available __NEXT_DATA__ query keys: %s", available)
        raise RuntimeError(f'Query "{query_key}" not found in __NEXT_DATA__')

    def _collect_feed_items(self, feed: dict) -> list[dict]:
        items = []
        for section in FEED_SECTIONS:
            section_items = feed.get(section)
            if isinstance(section_items, list):
                logger.debug(
                    "Yad2 feed section %s: %s items", section, len(section_items)
                )
                items.extend(section_items)
        return items

    def _parse_feed_item(self, item: dict) -> Listing | None:
        try:
            token = str(item.get("token") or item.get("orderId") or "")
            if not token:
                logger.debug("Skipping Yad2 feed item without token/orderId")
                return None

            address = item.get("address") or {}
            details = item.get("additionalDetails") or {}
            city = (address.get("city") or {}).get("text", "")
            neighborhood = (address.get("neighborhood") or {}).get("text", "")
            street = (address.get("street") or {}).get("text", "")
            house = (address.get("house") or {}).get("number")
            rooms = details.get("roomsCount")
            price = item.get("price")
            description = (item.get("searchText") or "").strip()
            title = description.split("\n", 1)[0].strip() if description else ""
            upload_date = self._parse_upload_date(item.get("dateAdded"))

            location_parts = [
                str(house) if house is not None else None,
                street,
                neighborhood,
                city,
            ]
            location = ", ".join(part for part in location_parts if part)

            return Listing(
                id=token,
                upload_date=upload_date,
                fields={
                    "city": city,
                    "neighborhood": neighborhood,
                    "price": f"{price:,}"
                    if isinstance(price, (int, float))
                    else str(price or ""),
                    "rooms": str(rooms) if rooms is not None else "",
                    "desc": title or description,
                    "link": f"{ITEM_BASE}/{token}",
                    "location": location,
                },
            )
        except Exception:
            logging.exception("failed to parse Yad2 feed item")
            self.has_err = True
            return None

    def _parse_upload_date(self, value) -> datetime:
        if not value:
            return datetime.now()
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(
                value / 1000 if value > 1_000_000_000_000 else value
            )
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(
                    tzinfo=None
                )
            except ValueError:
                pass
        return datetime.now()

    def _enrich_with_item_details(
        self, page, listings_by_id: dict[str, Listing], yad2: dict
    ):
        item_template = yad2.get("item_url_template", f"{ITEM_BASE}/{{token}}")
        item_query_key = yad2.get("item_query_key", "item")
        logger.debug(
            "Yad2 enriching %s listings with item details", len(listings_by_id)
        )

        for listing in listings_by_id.values():
            try:
                item_url = item_template.format(token=listing.id)
                logger.debug("Yad2 fetching item details: %s", item_url)
                content = self.fetch_rendered_page(
                    item_url, page=page, wait_for_selector="#__NEXT_DATA__"
                )
                item_data = self._extract_next_data(content, item_query_key)
                description = (item_data.get("searchText") or "").strip()
                if description:
                    listing.fields["desc"] = (
                        description.split("\n", 1)[0].strip() or description
                    )
            except Exception:
                logging.exception(
                    "failed to fetch Yad2 item details for %s", listing.id
                )
                self.has_err = True
