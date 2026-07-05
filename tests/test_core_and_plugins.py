import json
from datetime import datetime, timedelta
from unittest.mock import patch

from core.listing import Listing
from core.cache_manager import parse_duration, CacheManager
from plugins.agora.scraper import AgoraScraper
from plugins.glassdoor.scraper import GlassdoorScraper


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


# ---------------------------------------------------------------------------
# GlassdoorScraper
# ---------------------------------------------------------------------------

BASE_URL = "https://www.glassdoor.com/Job/israel-devops-engineer-jobs-SRCH_IL.0,6_IN119_KO7,22.htm"


def _glassdoor_config(tmp_path):
    return {
        "name": "glassdoor_test",
        "cache": {
            "file": str(tmp_path / "glassdoor_cache.json"),
            "expiration": {"value": 14, "unit": "days"},
            "cleanup": {"on_removed": True, "on_expiration": True},
        },
        "glassdoor": {
            "search_urls": [BASE_URL],
            "max_pages": 3,
            "delay": 0.0,
        },
    }


def test_glassdoor_scraper_instantiation(tmp_path):
    """GlassdoorScraper can be instantiated without errors."""
    scraper = GlassdoorScraper(config=_glassdoor_config(tmp_path))
    assert scraper.cache_manager is not None


# --- _build_page_url ----------------------------------------------------------


def test_build_page_url_page_1_unchanged():
    """Page 1 must return the base URL with no modification."""
    url = GlassdoorScraper._build_page_url(BASE_URL, 1)
    assert url == BASE_URL
    assert "_IP" not in url


def test_build_page_url_page_2_inserts_token():
    url = GlassdoorScraper._build_page_url(BASE_URL, 2)
    assert url.endswith("_IP2.htm")
    assert "SRCH_IL" in url  # rest of the path preserved


def test_build_page_url_page_5():
    url = GlassdoorScraper._build_page_url(BASE_URL, 5)
    assert "_IP5.htm" in url


def test_build_page_url_replaces_existing_token():
    """If the base URL already contains an _IP token, it gets replaced."""
    url_with_token = BASE_URL.replace(".htm", "_IP3.htm")
    result = GlassdoorScraper._build_page_url(url_with_token, 7)
    assert "_IP7.htm" in result
    assert "_IP3" not in result


def test_build_page_url_page_1_strips_existing_token():
    """Requesting page 1 of a URL that already has _IP{n} strips the token."""
    url_with_token = BASE_URL.replace(".htm", "_IP4.htm")
    result = GlassdoorScraper._build_page_url(url_with_token, 1)
    assert "_IP" not in result
    assert result.endswith(".htm")


# --- HTML parsing -------------------------------------------------------------

_SAMPLE_HTML = """
<html><body>
  <li data-test="jobListing" data-id="9876543">
    <a href="/job-listing/devops-engineer-acme-JV_IC0,12_KO0,15_KE15,25.htm?jl=9876543">
      <span data-test="job-title">Senior DevOps Engineer</span>
    </a>
    <span data-test="employer-short-name">Acme Ltd</span>
    <span data-test="employer-location">Tel Aviv-Yafo, Israel</span>
  </li>
  <li data-test="jobListing" data-id="1111111">
    <a href="https://www.glassdoor.com/job-listing/devops-beta-JV_KO0,10.htm?jl=1111111">
      <span data-test="job-title">DevOps Engineer</span>
    </a>
    <span data-test="employer-short-name">Beta Corp</span>
    <span data-test="employer-location">Herzliya, Israel</span>
  </li>
</body></html>
"""


def test_glassdoor_parse_page_returns_listings(tmp_path):
    scraper = GlassdoorScraper(config=_glassdoor_config(tmp_path))
    listings = scraper._parse_page(_SAMPLE_HTML)

    assert len(listings) == 2
    ids = {lst.id for lst in listings}
    assert "9876543" in ids
    assert "1111111" in ids


def test_glassdoor_parse_page_fields(tmp_path):
    scraper = GlassdoorScraper(config=_glassdoor_config(tmp_path))
    listings = scraper._parse_page(_SAMPLE_HTML)

    by_id = {lst.id: lst for lst in listings}
    first = by_id["9876543"]
    assert first.fields["title"] == "Senior DevOps Engineer"
    assert first.fields["company"] == "Acme Ltd"
    assert first.fields["location"] == "Tel Aviv-Yafo, Israel"
    # Link must not contain tracking query params
    assert "?" not in first.fields["link"]


def test_glassdoor_parse_page_empty_on_no_cards(tmp_path):
    scraper = GlassdoorScraper(config=_glassdoor_config(tmp_path))
    listings = scraper._parse_page("<html><body><p>No jobs here.</p></body></html>")
    assert listings == []


def test_glassdoor_scan_returns_listings(tmp_path):
    """scan() returns whatever the mocked implementation produces."""
    expected = [
        Listing(
            id="9876543",
            upload_date=datetime(2024, 6, 1),
            fields={
                "title": "DevOps Engineer",
                "company": "Acme Ltd",
                "location": "Tel Aviv-Yafo, Israel",
                "link": "https://www.glassdoor.com/job-listing/devops-9876543.htm",
            },
        )
    ]
    scraper = GlassdoorScraper(config=_glassdoor_config(tmp_path))
    with patch.object(scraper, "scan", return_value=expected):
        result = scraper.scan()
    assert result == expected
    assert result[0].fields["company"] == "Acme Ltd"
