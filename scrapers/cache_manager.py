import json
import logging
import os
from datetime import datetime, timedelta

from scrapers.listing import Listing


def json_serial(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")


class CacheManager:
    def __init__(self, config: dict):
        cache_cfg = config["cache"]
        self.clean_cache_days = cache_cfg["clean_cache_days"]
        self.cache_file = cache_cfg["file"]
        self.source_name = config.get("name", config.get("source", "unknown"))
        self.has_err = False

    def read(self) -> dict[str, datetime]:
        cache = {}
        try:
            with open(self.cache_file, encoding="utf-8") as mem:
                read = json.loads(mem.read())
                cache = {str(k): datetime.fromisoformat(v) for k, v in read.items()}
        except FileNotFoundError:
            pass
        except Exception:
            logging.exception("failed to read cache")
            self.has_err = True
        return cache

    def sync(self, listings: list[Listing]) -> list[Listing]:
        cache = self.read()
        results = {listing.id: listing for listing in listings}
        current_ids = set(results.keys())
        cached_ids = set(cache.keys())

        new_ids = current_ids - cached_ids
        removed_ids = cached_ids - current_ids

        for listing_id in sorted(new_ids):
            listing = results[listing_id]
            logging.info(
                "New item found [%s]: id=%s link=%s desc=%s",
                self.source_name,
                listing_id,
                listing.fields.get("link", ""),
                listing.fields.get("desc", ""),
            )

        for listing_id in sorted(removed_ids):
            logging.debug(
                "Item removed [%s]: id=%s last_seen=%s",
                self.source_name,
                listing_id,
                cache[listing_id].isoformat(),
            )

        new_records = {
            listing_id: results[listing_id].upload_date for listing_id in new_ids
        }
        self.update(cache, new_records)

        return [results[listing_id] for listing_id in new_ids]

    def update(self, cache: dict[str, datetime], new_records: dict[str, datetime]):
        clean_cache = {
            key: value
            for key, value in cache.items()
            if datetime.now() - value < timedelta(days=self.clean_cache_days)
        }
        clean_cache.update(new_records)
        os.makedirs(os.path.dirname(self.cache_file) or ".", exist_ok=True)
        with open(self.cache_file, "w", encoding="utf-8") as mem:
            mem.write(json.dumps(clean_cache, default=json_serial))
