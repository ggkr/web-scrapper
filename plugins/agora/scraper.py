import logging
from datetime import datetime

from playwright.sync_api import Locator

from core.base_scraper import BaseScraper
from core.listing import Listing
from core.registry import register

logger = logging.getLogger(__name__)


@register("agora")
class AgoraScraper(BaseScraper):
    def scan(self) -> list[Listing]:
        agora = self.config["agora"]
        listings = []

        with self.playwright_page() as page:
            logger.debug("Playwright browser launched for Agora")
            logging.info("Fetching Agora listings: %s", agora["base_url"])
            page.goto(agora["base_url"], wait_until="load", timeout=60000)

            table = page.locator("#objectsTable")
            if table.count() == 0:
                raise RuntimeError("Could not find objectsTable on Agora page")

            groups = page.locator("#objectsTable tbody.objectGroup")
            group_count = groups.count()
            logger.debug("Agora found %s listing groups on page", group_count)
            for index in range(group_count):
                listing = self._read_element(page, groups.nth(index), agora)
                if listing is not None:
                    listings.append(listing)

        logger.debug("Agora scan complete: %s listings", len(listings))
        return listings

    def _read_element(self, page, group: Locator, agora: dict) -> Listing | None:
        try:
            onclick = group.locator("tr.objectsTitleTr").get_attribute("onclick")
            load_data = (
                onclick.lstrip("showObjectDetails(")
                .rstrip(")")
                .replace("'", "")
                .split(",")
            )
            date = load_data[0]
            listing_id = int(load_data[1])

            upload_date = datetime.strptime(
                group.locator("td.regDate").get_attribute("title"),
                "%d/%m/%Y %H:%M",
            )
            condition = group.locator("td.objectState").get_attribute("title")
            city = group.locator("td.area").inner_text()

            if self.cache_manager.is_past_expiration(upload_date):
                logger.debug(
                    "Skipping Agora listing %s: older than %s %s",
                    listing_id,
                    self.cache_manager.expiration_value,
                    self.cache_manager.expiration_unit,
                )
                return None

            detail_url = agora["query_url"].format(date=date, id=listing_id)
            logger.debug("Agora fetching details for id=%s: %s", listing_id, detail_url)
            page.goto(detail_url, wait_until="load", timeout=60000)
            description = page.locator("td.details").inner_text()

            listing = Listing(
                id=str(listing_id),
                upload_date=upload_date,
                fields={
                    "condition": condition,
                    "city": city,
                    "desc": description,
                    "link": agora["share_url"].format(date=date, id=listing_id),
                    "image_url": agora["image_url"].format(date=date, id=listing_id),
                },
            )
            logger.debug("Agora parsed listing: id=%s url=%s", listing.id, listing.url)
            return listing
        except Exception:
            logging.exception("failed to parse Agora element")
            self.has_err = True
            return None
