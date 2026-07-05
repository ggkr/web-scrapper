import json
import logging
import os
from datetime import datetime, timedelta

from core.listing import Listing

logger = logging.getLogger(__name__)

DEFAULT_EXPIRATION = {"value": 90, "unit": "days"}
DEFAULT_CLEANUP = {"on_removed": True, "on_expiration": True}
_DURATION_UNITS = {
    "days": lambda value: timedelta(days=value),
    "hours": lambda value: timedelta(hours=value),
    "weeks": lambda value: timedelta(weeks=value),
}


def json_serial(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")


def parse_duration(expiration_cfg: dict) -> timedelta:
    value = expiration_cfg.get("value", DEFAULT_EXPIRATION["value"])
    unit = expiration_cfg.get("unit", DEFAULT_EXPIRATION["unit"])
    if unit not in _DURATION_UNITS:
        supported = ", ".join(sorted(_DURATION_UNITS))
        raise ValueError(
            f"Invalid cache expiration unit: {unit!r}. Use one of: {supported}"
        )
    return _DURATION_UNITS[unit](value)


class CacheManager:
    def __init__(self, config: dict):
        cache_cfg = config["cache"]
        expiration_cfg = cache_cfg.get("expiration", DEFAULT_EXPIRATION)
        cleanup_cfg = {**DEFAULT_CLEANUP, **cache_cfg.get("cleanup", {})}

        self.expiration = parse_duration(expiration_cfg)
        self.expiration_value = expiration_cfg.get("value", DEFAULT_EXPIRATION["value"])
        self.expiration_unit = expiration_cfg.get("unit", DEFAULT_EXPIRATION["unit"])
        self.cleanup_on_removed = cleanup_cfg["on_removed"]
        self.cleanup_on_expiration = cleanup_cfg["on_expiration"]
        self.cache_file = cache_cfg["file"]
        self.source_name = config.get("name", config.get("source", "unknown"))
        self.has_err = False
        logger.debug(
            "Cache manager initialized: file=%s expiration=%s %s cleanup_on_removed=%s cleanup_on_expiration=%s",
            self.cache_file,
            self.expiration_value,
            self.expiration_unit,
            self.cleanup_on_removed,
            self.cleanup_on_expiration,
        )

    def is_past_expiration(self, timestamp: datetime) -> bool:
        return datetime.now() - timestamp >= self.expiration

    def read(self) -> dict[str, datetime]:
        cache = {}
        try:
            with open(self.cache_file, encoding="utf-8") as mem:
                read = json.loads(mem.read())
                cache = {str(k): datetime.fromisoformat(v) for k, v in read.items()}
            logger.debug(
                "Read %s entries from cache file %s", len(cache), self.cache_file
            )
        except FileNotFoundError:
            logger.debug(
                "Cache file not found, starting with empty cache: %s", self.cache_file
            )
        except Exception:
            logger.exception("failed to read cache")
            self.has_err = True
        return cache

    def sync(self, listings: list[Listing]) -> list[Listing]:
        cache = self.read()
        results = {listing.id: listing for listing in listings}
        current_ids = set(results.keys())
        cached_ids = set(cache.keys())

        new_ids = current_ids - cached_ids
        removed_ids = cached_ids - current_ids
        unchanged_ids = current_ids & cached_ids

        logger.debug(
            "Cache sync [%s]: cached=%s current=%s new=%s removed=%s unchanged=%s",
            self.source_name,
            len(cached_ids),
            len(current_ids),
            len(new_ids),
            len(removed_ids),
            len(unchanged_ids),
        )

        for listing_id in sorted(new_ids):
            listing = results[listing_id]
            logging.info(
                "New item found [%s]: url=%s id=%s desc=%s",
                self.source_name,
                listing.url,
                listing_id,
                listing.fields.get("desc", ""),
            )

        for listing_id in sorted(removed_ids):
            logging.info(
                "Item removed [%s]: id=%s last_seen=%s",
                self.source_name,
                listing_id,
                cache[listing_id].isoformat(),
            )

        new_records = {
            listing_id: results[listing_id].upload_date for listing_id in new_ids
        }
        self.update(cache, new_records, removed_ids)

        return [results[listing_id] for listing_id in new_ids]

    def update(
        self,
        cache: dict[str, datetime],
        new_records: dict[str, datetime],
        removed_ids: set[str] | None = None,
    ):
        removed_ids = removed_ids or set()
        to_drop: set[str] = set()

        if self.cleanup_on_expiration:
            expired = {
                key for key, value in cache.items() if self.is_past_expiration(value)
            }
            to_drop |= expired
            if expired:
                logger.debug(
                    "Cache [%s]: expiring %s entries older than %s %s: %s",
                    self.source_name,
                    len(expired),
                    self.expiration_value,
                    self.expiration_unit,
                    sorted(expired),
                )

        if self.cleanup_on_removed and removed_ids:
            to_drop |= removed_ids
            logger.debug(
                "Cache [%s]: removing %s detected-removed entries: %s",
                self.source_name,
                len(removed_ids),
                sorted(removed_ids),
            )

        before_count = len(cache) - len(to_drop)
        clean_cache = {key: value for key, value in cache.items() if key not in to_drop}
        clean_cache.update(new_records)
        logger.debug(
            "Cache [%s]: writing %s entries (%s retained, %s added), saved to %s",
            self.source_name,
            len(clean_cache),
            before_count,
            len(new_records),
            self.cache_file,
        )
        os.makedirs(os.path.dirname(self.cache_file) or ".", exist_ok=True)
        with open(self.cache_file, "w", encoding="utf-8") as mem:
            mem.write(json.dumps(clean_cache, default=json_serial))
