# Glassdoor Jobs Plugin

Scrapes Glassdoor public job search pages using Playwright (headless Chromium).
Glassdoor renders its job cards client-side via React, so plain HTTP requests only
return a nearly-empty HTML shell — a real browser is required.

## How it works

1. Playwright navigates to the configured search URL and waits for job cards to appear.
2. BeautifulSoup parses the rendered HTML, targeting stable `data-test` attributes.
3. Pagination follows Glassdoor's `_IP{n}.htm` convention — pages 2+ have that token
   inserted just before `.htm`.  The plugin iterates up to `max_pages`, stopping early
   when a page returns no cards.

## Finding a search URL

1. Go to [glassdoor.com/Job](https://www.glassdoor.com/Job) and run the job search
   you want (keywords, location, date posted, etc.).
2. Copy the URL from your browser's address bar once the results are shown.
   It will look similar to:
   ```
   https://www.glassdoor.com/Job/israel-devops-engineer-jobs-SRCH_IL.0,6_IN119_KO7,22.htm
   ```
3. Paste that URL as a value under `glassdoor.search_urls` in your config file.
   The plugin automatically builds the paginated variants (`_IP2.htm`, `_IP3.htm`, …).

> **Note:** The scraper targets the *public*, logged-out version of the search page.
> It does not log in or use any session cookies.

## Configuration reference

```yaml
source: glassdoor
name: Glassdoor DevOps Jobs (Israel)

glassdoor:
  search_urls:
    - "https://www.glassdoor.com/Job/israel-devops-engineer-jobs-SRCH_IL.0,6_IN119_KO7,22.htm"

  # Maximum number of pages to fetch per URL (Glassdoor shows ~30 cards/page).
  max_pages: 5

  # Seconds to wait between page requests.  Keep this ≥ 2 to avoid rate-limiting.
  delay: 3.0
```

## Selectors used

| Field   | Selector (primary)                      | Notes |
|---------|-----------------------------------------|-------|
| Card    | `[data-test="jobListing"]`              | Falls back to `li.react-job-listing, article[data-id]` |
| Title   | `[data-test="job-title"]`               | Falls back to common heading elements |
| Company | `[data-test="employer-short-name"]`     | |
| Location| `[data-test="employer-location"]`       | |
| Link    | First `<a href*="glassdoor.com/job">` in card | Removing tracking params will break the link |
| Job ID  | `data-id` / `data-jobid` attribute, or extracted from href | |

Glassdoor's hashed React class names (e.g. `JobCard_jobCard__abc12`) change on every
deploy; `data-test` attributes are part of their own QA tooling and are significantly
more stable.  If the primary selectors stop matching, inspect the rendered page in
DevTools and update the `_SEL_*` constants in `scraper.py`.

## Message template fields

| Field      | Example value                                          |
|------------|--------------------------------------------------------|
| `title`    | `DevOps Engineer`                                      |
| `company`  | `Acme Corp`                                            |
| `location` | `Tel Aviv-Yafo, Israel`                                |
| `link`     | `https://www.glassdoor.com/job-listing/devops-…`       |

## Notes

- Scraping Glassdoor may conflict with their Terms of Service — use responsibly.
- Keep `delay` ≥ 2 and `max_pages` reasonable; aggressive polling risks IP bans.
- Run `playwright install chromium` once before using this plugin.
