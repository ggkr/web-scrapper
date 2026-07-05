# LinkedIn Guest Jobs Plugin

Scrapes LinkedIn's public "guest" job search endpoint
(`/jobs-guest/jobs/api/seeMoreJobPostings/search`). This is the endpoint
LinkedIn's own job search page calls in the background to lazy-load more
results, and — unlike the rest of linkedin.com — it's served without
requiring a logged-in session, which is why it's called a "guest" endpoint.
Because it's plain server-rendered HTML, this plugin uses `http_get()`
instead of Playwright.

## Finding a guest search URL from your own logged-in account

You don't need to log out to find the URL — you're just reading the request
your browser already makes, not anything tied to your session.

1. **Run the search you want normally.** Log into linkedin.com, go to
   **Jobs**, and set up your search: keywords, location, "Date posted",
   experience level, remote/hybrid/onsite, etc. Get the results looking the
   way you want them.

2. **Open DevTools → Network tab, filter to Fetch/XHR.** Keep it open, then
   scroll down the job results list. LinkedIn loads additional results in
   batches of 25, and each batch triggers a new request.

3. **Find the request to `seeMoreJobPostings/search`.** Click it, copy the
   full request URL (Network tab → right-click → Copy → Copy link address).
   That URL is the guest endpoint — right-click it and open it in a private/
   incognito window (logged out) to confirm it loads the same job cards
   without any cookies. If it does, it's safe to reuse outside your browser.

4. **Read the query parameters off that URL** — these are the ones this
   plugin's config relies on:

   | Param | Meaning |
   |---|---|
   | `keywords` | Free-text search terms |
   | `location` | Free-text location (LinkedIn will resolve it to a `geoId`) |
   | `geoId` | Numeric id for a resolved location; more reliable than `location` alone |
   | `f_TPR` | Date-posted filter, as `r<seconds>` — e.g. `r604800` = past week, `r86400` = past 24h |
   | `f_E` | Experience level (`2` = entry, `3` = associate, `4` = mid-senior, etc.) |
   | `f_WT` | Workplace type (`1` = on-site, `2` = remote, `3` = hybrid) |
   | `f_JT` | Job type (`F` = full-time, `P` = part-time, `C` = contract, etc.) |
   | `distance` | Search radius in miles from the location |
   | `start` | Pagination offset, in steps of 25 — this plugin manages it for you |

   Only `keywords` combined with either `location` or `geoId` is required;
   the rest are optional filters you can add or drop from the URL.

5. **To get a `geoId` for a new location**, type it into the normal Jobs
   search location box and watch DevTools for the typeahead request (or just
   check the `geoId` param on the resulting search page's own URL once you
   hit enter) — copy the id it resolves to.

## Notes

- This plugin only ever calls the guest endpoint, never an authenticated
  one — no cookies or tokens are sent or needed.
- Keep `delay` in the config reasonable and `max_pages` bounded; this is
  still LinkedIn's infrastructure and aggressive polling can get an IP
  rate-limited or blocked regardless of the endpoint being public.
- Scraping LinkedIn may conflict with their Terms of Service — that's a
  decision for whoever runs this config, not something this plugin enforces.
