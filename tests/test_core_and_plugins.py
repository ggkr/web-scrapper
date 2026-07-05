import json
from datetime import datetime, timedelta
from unittest.mock import patch

from core.listing import Listing
from core.cache_manager import parse_duration, CacheManager
from plugins.agora.scraper import AgoraScraper


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------

def test_listing_url_from_fields_link():
    lst = Listing(
        id="1",
        upload_date=datetime(2023, 1, 1, 12, 0, 0),
        fields={"link": "https://example.com/item/1", "desc": "Test item"},
    )
    assert lst.url == "https://example.com/item/1"


def test_listing_url_from_fields_url():
    lst = Listing(
        id="2",
        upload_date=datetime(2023, 6, 15),
        fields={"url": "https://example.com/item/2"},
    )
    assert lst.url == "https://example.com/item/2"


def test_listing_url_empty_when_no_url_field():
    lst = Listing(id="3", upload_date=datetime.now(), fields={"desc": "no url here"})
    assert lst.url == ""


# ---------------------------------------------------------------------------
# parse_duration
# ---------------------------------------------------------------------------

def test_parse_duration_days():
    cfg = {"value": 2, "unit": "days"}
    delta = parse_duration(cfg)
    assert isinstance(delta, timedelta)
    assert delta == timedelta(days=2)


def test_parse_duration_hours():
    cfg = {"value": 6, "unit": "hours"}
    assert parse_duration(cfg) == timedelta(hours=6)


def test_parse_duration_weeks():
    cfg = {"value": 1, "unit": "weeks"}
    assert parse_duration(cfg) == timedelta(weeks=1)


# ---------------------------------------------------------------------------
# CacheManager
# ---------------------------------------------------------------------------

def _make_config(tmp_path, expiration_days=1):
    return {
        "name": "test",
        "cache": {
            "file": str(tmp_path / "cache.json"),
            "expiration": {"value": expiration_days, "unit": "days"},
            "cleanup": {"on_removed": False, "on_expiration": False},
        },
    }


def test_cache_manager_read_empty(tmp_path):
    cm = CacheManager(_make_config(tmp_path))
    assert cm.read() == {}


def test_cache_manager_sync_new_listing(tmp_path):
    cm = CacheManager(_make_config(tmp_path))
    lst = Listing(
        id="a",
        upload_date=datetime(2024, 1, 1),
        fields={"link": "https://example.com/a"},
    )
    new = cm.sync([lst])
    assert new == [lst]
    cached = cm.read()
    assert "a" in cached


def test_cache_manager_cleanup_on_expiration(tmp_path):
    cache_file = tmp_path / "cache.json"
    config = {
        "name": "test",
        "cache": {
            "file": str(cache_file),
            "expiration": {"value": 1, "unit": "days"},
            "cleanup": {"on_removed": False, "on_expiration": True},
        },
    }
    cm = CacheManager(config)
    # Seed the cache with an entry that is 2 days old
    past = datetime.now() - timedelta(days=2)
    with open(str(cache_file), "w", encoding="utf-8") as f:
        json.dump({"old": past.isoformat()}, f)
    # Syncing an empty list with cleanup_on_expiration=True should remove the expired entry
    cm.sync([])
    assert cm.read() == {}


# ---------------------------------------------------------------------------
# AgoraScraper
# ---------------------------------------------------------------------------

def _agora_config(tmp_path):
    return {
        "name": "agora",
        "cache": {
            "file": str(tmp_path / "agora_cache.json"),
            "expiration": {"value": 90, "unit": "days"},
            "cleanup": {"on_removed": True, "on_expiration": True},
        },
        "agora": {
            "base_url": "https://example.com/agora",
            "query_url": "https://example.com/agora/detail?date={date}&id={id}",
            "share_url": "https://example.com/agora/share?date={date}&id={id}",
            "image_url": "https://example.com/agora/img?date={date}&id={id}",
        },
    }


def test_agora_scraper_instantiation(tmp_path):
    """AgoraScraper can be created without errors when given a valid config."""
    scraper = AgoraScraper(config=_agora_config(tmp_path))
    assert scraper.cache_manager is not None


def test_agora_scraper_scan_returns_listings(tmp_path):
    """scan() returns whatever listings the mocked implementation produces."""
    expected = [
        Listing(
            id="123",
            upload_date=datetime(2024, 3, 1),
            fields={"link": "https://example.com/agora/share?date=20240301&id=123"},
        )
    ]
    scraper = AgoraScraper(config=_agora_config(tmp_path))
    with patch.object(scraper, "scan", return_value=expected):
        result = scraper.scan()
    assert result == expected
    assert result[0].id == "123"
    assert "agora" in result[0].url
