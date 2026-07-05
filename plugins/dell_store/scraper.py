import hashlib
import logging
import time
from datetime import datetime

from core.base_scraper import BaseScraper
from core.listing import Listing
from core.registry import register

logger = logging.getLogger(__name__)


@register("dell_store")
class DellStoreScraper(BaseScraper):
    def scan(self) -> list[Listing]:
        dell_cfg = self.config["dell_store"]
        listings = []

        links = dell_cfg.get("links", [])
        price_class = dell_cfg.get(
            "price_class", "h3 font-weight-bold mb-1 text-nowrap sale-price"
        )
        saving_class = dell_cfg.get(
            "saving_class", "h6 align-middle font-weight-bold savings-price"
        )
        alert_threshold = float(dell_cfg.get("alert_threshold", 1.0))
        delay = float(dell_cfg.get("delay", 2.0))

        logger.debug("Dell store Playwright scan starting: %s links", len(links))

        with self.playwright_page() as page:
            logger.debug("Playwright browser launched for Dell Store")
            for idx, link in enumerate(links):
                if idx > 0 and delay > 0:
                    logger.debug(
                        "Sleeping for %s seconds to respect rate limits...", delay
                    )
                    time.sleep(delay)

                listing = self._scan_link(
                    page, link, price_class, saving_class, alert_threshold
                )
                if listing is not None:
                    listings.append(listing)

        logger.debug("Dell store Playwright scan complete: %s listings", len(listings))
        return listings

    def _scan_link(
        self,
        page,
        link: str,
        price_class: str,
        saving_class: str,
        alert_threshold: float,
    ) -> Listing | None:
        try:
            logger.info("Fetching Dell product page: %s", link)
            page.goto(link, wait_until="load", timeout=60000)

            # Build price CSS candidates
            price_candidates = []
            if " " in price_class:
                css_sel = "span." + ".".join(price_class.split())
                price_candidates.append(css_sel)
                price_candidates.append(f"span.{price_class.split()[-1]}")
            else:
                price_candidates.append(f"span.{price_class}")

            price_candidates.extend(["span.sale-price", "span.ps-variant-price-amount"])
            price_or_selector = ", ".join(price_candidates)

            # Wait up to 10 seconds for the pricing elements to lazy-load / render
            logger.debug("Waiting for price selector candidates: %s", price_or_selector)
            try:
                page.wait_for_selector(price_or_selector, timeout=10000)
            except Exception:
                logger.debug("Timeout waiting for price selector on %s", link)

            # Locate price element
            price_loc = page.locator(price_or_selector)
            if price_loc.count() == 0:
                logger.warning("Could not find price element on %s", link)
                return None

            current_price = price_loc.first.inner_text().replace("$", "").strip()

            # Build savings CSS candidates
            savings_candidates = []
            if " " in saving_class:
                css_sel = "span." + ".".join(saving_class.split())
                savings_candidates.append(css_sel)
                savings_candidates.append(f"span.{saving_class.split()[-1]}")
            else:
                savings_candidates.append(f"span.{saving_class}")

            savings_candidates.extend(
                ["span.savings-price", "span.ps-variant-savings-amount"]
            )
            savings_or_selector = ", ".join(savings_candidates)

            # Locate savings element
            savings_loc = page.locator(savings_or_selector)
            if savings_loc.count() > 0:
                savings = savings_loc.first.inner_text().replace("$", "").strip()
            else:
                savings = "0"

            # Parse savings to check against alert threshold
            try:
                savings_val = float(savings)
            except ValueError:
                savings_val = 0.0

            logger.debug(
                "Parsed from %s (Final URL: %s): price=%s, savings=%s (value=%s, threshold=%s)",
                link,
                page.url,
                current_price,
                savings,
                savings_val,
                alert_threshold,
            )

            if savings_val >= alert_threshold:
                model_name = link.rstrip("/").split("/")[-1]
                if not model_name:
                    model_name = hashlib.md5(link.encode("utf-8")).hexdigest()

                # Unique listing ID consists of the model name and the current price.
                # When the price changes, a new ID is generated, triggering a new notification.
                # The old price ID will be cleaned up automatically from the cache.
                listing_id = f"{model_name}_{current_price}"

                return Listing(
                    id=listing_id,
                    upload_date=datetime.now(),
                    fields={
                        "price": current_price,
                        "savings": savings,
                        "link": link,
                    },
                )
            else:
                logger.debug(
                    "Savings (%s) for %s is below threshold (%s)",
                    savings,
                    link,
                    alert_threshold,
                )
                return None
        except Exception:
            logger.exception("Failed to parse Dell element from %s", link)
            self.has_err = True
            return None
