# Adding a new scraper plugin

1. Create a package under `plugins/`, e.g. `plugins/mysite/`
2. Add `scraper.py` with a class that extends `BaseScraper` and implements `scan()`
3. Decorate the class with `@register("mysite")` — the name must match the `source` field in config
4. Add `config/mysite.yaml` with `source: mysite` and site-specific settings (use `config/example.yaml` as a starting point)

Plugins are discovered automatically — no changes to core code are required.

## Division of responsibility

`BaseScraper` owns *fetching* — plain HTTP requests and Playwright-rendered page loads. It deliberately does **not** own pagination: how a site paginates (blind offset with a "short page = done" heuristic, a declared total-pages count, cursor tokens, "load more" clicks, ...) varies enough that folding it into the base class either forces every plugin into one shape it doesn't fit, or turns into a pile of callback parameters that's harder to use than just writing the loop. So pagination strategy lives in the plugin, next to the parsing logic it's paired with - see `plugins/linkedin/scraper.py` for a simple offset-based example and `plugins/yad2/scraper.py` for one driven by a declared page count.

A plugin's `scan()` is responsible for:

1. Building the URL(s) it needs, including any pagination loop.
2. Parsing fetched content into `Listing`s.

### Fetching a page

Use the underlying fetch helpers for each individual request - one call per page/link, however your own loop decides to keep going:

- `fetch_static_page(url)` — plain HTTP GET, returns the raw response body. The default choice when no JS rendering is needed.
- `fetch_rendered_page(url, wait_for_selector=...)` — loads the URL in a real (short-lived) Playwright browser and returns the rendered HTML.

```python
listings = []
for link in cfg["links"]:
    html = self.fetch_static_page(link)
    listing = self._parse_listing(html, link)
    if listing:
        listings.append(listing)
```

### Multi-step flows: reusing one browser across several fetches

Some sites need more than one fetch per scan that isn't a simple "page 1, 2, 3..." sequence — e.g. loading a search page, then fetching a separate detail page per result (`agora`), or discovering how many pages exist only after parsing the first one (`yad2`). For these, open `browser_page()` once for the whole scan and pass the same `page` into each `fetch_rendered_page()` call, so every fetch reuses one browser instead of relaunching per request:

```python
with self.browser_page() as page:
    search_html = self.fetch_rendered_page(cfg["search_url"], page=page, wait_for_selector="#results")
    for result_url in extract_result_urls(search_html):
        detail_html = self.fetch_rendered_page(result_url, page=page)
        # parse detail_html into a Listing
```

### When you need the live browser itself

Occasionally a plugin genuinely needs to interact with the DOM rather than just read its rendered output — clicking, filling forms, or calling `page.evaluate()` for something not present in `page.content()`. In that case, use the `page` yielded by `browser_page()` directly instead of going through `fetch_rendered_page()`:

```python
with self.browser_page() as page:
    page.goto(cfg["search_url"], wait_until="load", timeout=60000)
    # interact with page directly: locators, page.evaluate(), clicks, etc.
```

Optional arguments: `headless=False` to show the browser window; `locale="en-US"` to override the default locale. Lower-level helpers `browser_launch_args()` and `build_browser_context_options()` are also available for advanced cases.

Run `playwright install chromium` once before using any Playwright-based plugin.

### Cache

`self.cache_manager` is initialized from config. Use it to skip expired listings, or rely on the runner to diff against the cache after `scan()` returns.

## Listing output

`scan()` must return a `list[Listing]`. Each `Listing` has an `id`, `upload_date`, and a `fields` dict. Field names become available in the YAML `message_template` (e.g. `{price}`, `{link}`).

## Error handling

Set `self.has_err = True` when a non-fatal parse error occurs (or a fetch fails partway through a scan) so the runner can trigger error notifications without aborting the whole scan.
