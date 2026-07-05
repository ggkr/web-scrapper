import json
from datetime import datetime, timedelta

from core.listing import Listing
from core.cache_manager import parse_duration, CacheManager
from plugins.agora.scraper import AgoraScraper


def test_listing_serialization():
    lst = Listing(
        id="1",
        url="https://example.com",
        title="Test",
        description="Desc",
        fields={"extra": 42},
        upload_date=datetime(2023, 1, 1, 12, 0, 0),
    )
    d = lst.to_dict()
    assert d["id"] == "1"
    assert d["url"] == "https://example.com"
    assert d["title"] == "Test"
    assert d["description"] == "Desc"
    assert d["fields"]["extra"] == 42
    assert d["upload_date"] == "2023-01-01T12:00:00"
    rebuilt = Listing.from_dict(d)
    assert rebuilt == lst


def test_parse_duration_days():
    cfg = {"value": 2, "unit": "days"}
    delta = parse_duration(cfg)
    assert isinstance(delta, timedelta)
    assert delta == timedelta(days=2)


def test_cache_manager_basic(tmp_path):
    cache_file = tmp_path / "cache.json"
    config = {
        "name": "test",
        "cache": {
            "file": str(cache_file),
            "expiration": {"value": 1, "unit": "days"},
            "cleanup": {"on_removed": False, "on_expiration": False},
        },
    }
    cm = CacheManager(config)
    assert cm.read() == {}
    lst = Listing(id="a", url="https://example.com/a")
    new = cm.sync([lst])
    assert new == [lst]
    cached = cm.read()
    assert "a" in cached
    past = datetime.now() - timedelta(days=2)
    cached["a"] = past
    with open(str(cache_file), "w", encoding="utf-8") as f:
        json.dump({"a": past.isoformat()}, f)
    cm.cleanup_on_expiration = True
    cm.sync([])
    assert cm.read() == {}


def test_agora_scraper_fetch():
    scraper = AgoraScraper(config={})
    listing = scraper.fetch_listing("https://example.com/item")
    assert isinstance(listing, Listing)
    assert listing.id == "123"
    assert listing.url == "https://example.com/item"
