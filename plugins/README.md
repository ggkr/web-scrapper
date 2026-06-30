# Adding a new scraper plugin

1. Create a package under `plugins/`, e.g. `plugins/mysite/`
2. Add `scraper.py` with a class that extends `BaseScraper` and implements `scan()`
3. Decorate the class with `@register("mysite")` — the name must match the `source` field in config
4. Add `config/mysite.yaml` with `source: mysite` and site-specific settings (use `config/example.yaml` as a starting point)

Plugins are discovered automatically — no changes to core code are required.

## BaseScraper helpers

`BaseScraper` provides shared utilities so plugins can focus on site-specific parsing.

### Playwright (browser-based scraping)

Use `playwright_page()` for plugins that need a real browser. It launches Chromium with anti-automation defaults, builds a realistic browser context (user agent, locale, timezone, viewport), yields a `Page`, and closes the browser when done.

```python
from core.base_scraper import BaseScraper
from core.listing import Listing
from core.registry import register

@register("mysite")
class MySiteScraper(BaseScraper):
    def scan(self) -> list[Listing]:
        listings = []
        cfg = self.config["mysite"]

        with self.playwright_page() as page:
            page.goto(cfg["search_url"], wait_until="load", timeout=60000)
            # locate elements, parse into Listing objects, append to listings

        return listings
```

Optional arguments: `headless=False` to show the browser window; `locale="en-US"` to override the default locale.

For advanced cases, lower-level helpers are also available: `playwright_launch_args()` and `build_playwright_context_options()`.

Run `playwright install chromium` once before using Playwright-based plugins.

### HTTP requests (no browser)

Use `http_get()` for simple HTTP fetching with the same user-agent and header defaults:

```python
response = self.http_get(url, timeout=30)
html = response.text
```

### Cache

`self.cache_manager` is initialized from config. Use it to skip expired listings or rely on the runner to diff against the cache after `scan()` returns.

## Listing output

`scan()` must return a `list[Listing]`. Each `Listing` has an `id`, `upload_date`, and a `fields` dict. Field names become available in the YAML `message_template` (e.g. `{price}`, `{link}`).

## Error handling

Set `self.has_err = True` when a non-fatal parse error occurs so the runner can trigger error notifications without aborting the whole scan.
