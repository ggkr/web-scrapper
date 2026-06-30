import logging
from typing import Type

from core.base_scraper import BaseScraper

logger = logging.getLogger(__name__)

_SCRAPERS: dict[str, Type[BaseScraper]] = {}


def register(source_name: str):
    """Decorator that registers a scraper class as a plugin for the given source name."""

    def decorator(cls: Type[BaseScraper]) -> Type[BaseScraper]:
        if source_name in _SCRAPERS:
            raise ValueError(f"Scraper already registered for source: {source_name}")
        _SCRAPERS[source_name] = cls
        logger.debug("Registered scraper plugin: %s -> %s", source_name, cls.__name__)
        return cls

    return decorator


def get_scraper(source_name: str) -> Type[BaseScraper] | None:
    return _SCRAPERS.get(source_name)


def list_scrapers() -> dict[str, Type[BaseScraper]]:
    return dict(_SCRAPERS)
