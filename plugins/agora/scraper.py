import logging
from datetime import datetime

from bs4 import BeautifulSoup

from core.base_scraper import BaseScraper
from core.listing import Listing
from core.registry import register

logger = logging.getLogger(__name__)


@register("agora")
class AgoraScraper(BaseScraper):
    """Parses Agora bulletin board listings. Fetching (loading the search page
    and each listing's detail page in a real browser) is handled by
    BaseScraper.fetch_rendered_page(); this class only parses the rendered
    HTML into Listings. One browser session is kept open for the whole scan
    so the search page and every detail-page fetch reuse it."""

    def scan(self) -> list[Listing]:
        agora = self.config["agora"]
        listings = []

        with self.playwright_page() as page:
            logger.debug("Playwright browser launched for Agora")
            logging.info("Fetching Agora listings: %s", agora["base_url"])
            content = self.fetch_rendered_page(
                agora["base_url"], page=page, wait_for_selector="#objectsTable"
            )

            soup = BeautifulSoup(content, "html.parser")
            table = soup.select_one("#objectsTable")
            if table is None:
                raise RuntimeError("Could not find objectsTable on Agora page")

            groups = table.select("tbody.objectGroup")
            logger.debug("Agora found %s listing groups on page", len(groups))
            for group in groups:
                listing = self._read_element(page, group, agora)
                if listing is not None:
                    listings.append(listing)

        logger.debug("Agora scan complete: %s listings", len(listings))
        return listings

    def _read_element(self, page, group, agora: dict) -> Listing | None:
        try:
            title_row = group.select_one("tr.objectsTitleTr")
            if title_row is None:
                raise ValueError("Agora listing group is missing its title row")

            onclick = title_row.get("onclick", "")
            load_data = (
                onclick.lstrip("showObjectDetails(")
                .rstrip(")")
                .replace("'", "")
                .split(",")
            )
            date = load_data[0]
            listing_id = int(load_data[1])

            reg_date_el = group.select_one("td.regDate")
            upload_date = datetime.strptime(
                reg_date_el.get("title", ""),
                "%d/%m/%Y %H:%M",
            )
            condition_el = group.select_one("td.objectState")
            condition = condition_el.get("title") if condition_el else None
            city_el = group.select_one("td.area")
            city = city_el.get_text(strip=True) if city_el else ""

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
            detail_content = self.fetch_rendered_page(detail_url, page=page)
            detail_soup = BeautifulSoup(detail_content, "html.parser")
            description_el = detail_soup.select_one("td.details")
            description = description_el.get_text(strip=True) if description_el else ""

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
