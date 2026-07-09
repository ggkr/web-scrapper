# Bulletin Web Scrapper

Scans websites for new listings and sends Telegram notifications when something new appears. Each source runs independently with its own YAML config and cache.

Built-in plugins live under `plugins/` (e.g. bulletin boards, classifieds, store price checks). See each plugin package for site-specific behavior.

## Setup

```bash
pip install -r requirements.txt
playwright install firefox    # required for browser-based plugins (uses Camoufox)
camoufox fetch
```

Telegram subscribers are configured in `subscribers/<name>.conf` with a bot token and chat ID. See `subscribers/createSubscribers.md` for setup.

## Running

Each source requires a separate run with its own config file:

```bash
python scanner.py --config config/example.yaml
```

Copy `config/example.yaml` to `config/<your_source>.yaml`, set `source` to a registered plugin name, and fill in the plugin-specific section. The scanner loads listings, compares them against the configured cache, and notifies subscribers when new entries appear.

## Configuration

| File | Purpose |
|------|---------|
| `config/example.yaml` | Template for a new source (cache, logging, notifications, plugin settings) |
| `config/*.yaml` | One YAML file per scheduled source |
| `subscribers/*.conf` | Telegram bot token and chat ID per subscriber |

Edit a YAML file to change search filters, message templates, cache paths, or Telegram recipients. Each source maintains its own cache file, so they can be scheduled independently (e.g. separate cron jobs).

## Project structure

```
core/           Shared framework (cache, runner, base scraper, registry)
plugins/        Site-specific scraper plugins (one package per website)
config/         Per-source YAML configs
cache/          Listing caches (paths configured in YAML)
scanner.py      Entry point
```

### Built-in plugins

| Plugin | Source | Fetch method | What it scrapes |
|--------|--------|--------------|-----------------|
| `linkedin` | LinkedIn | Static HTTP | Public "guest" job search endpoint (`/jobs-guest/…`) |
| `glassdoor` | Glassdoor | Playwright | Public job search pages (`/Job/…SRCH….htm`) |
| `yad2` | Yad2 | Playwright | Real-estate listings via embedded `__NEXT_DATA__` |
| `agora` | Agora | Playwright | Bulletin-board / auction listings |
| `dell_store` | Dell IL store | Playwright | Product price checks |

### Adding a new scraper

See `plugins/README.md`. In short: create `plugins/<name>/scraper.py`, subclass `BaseScraper`, decorate with `@register("<name>")`, and add a matching `config/<name>.yaml`. No core code changes are needed.

## Logs

Logging is configured per source in the YAML config. Logs are printed to the console by default; set `console: false` to disable.

```yaml
logging:
  file: logs/example.log    # log file path (directory created automatically)
  level: INFO               # DEBUG | INFO | WARNING | ERROR | CRITICAL
  timestamp: false          # when true, writes to logs/example-2026-06-30.log
```

CLI flags override the config values:

```bash
python scanner.py --config config/example.yaml --log-file logs/debug.log --log-level DEBUG
python scanner.py --config config/example.yaml --log-timestamp
```

| Level | What you see |
|-------|--------------|
| `INFO` | Normal operation — fetches, new/removed items, scan summary |
| `DEBUG` | Operational and technical detail — cache sync, pagination, per-listing parses, Telegram sends, Playwright steps |

If errors occur, an email with the log file attached is sent when a log file is configured (see `notifications.email` in the YAML).

# Known errors

## TypeError: Cannot read properties of undefined (reading 'url')
it's a known compatibility bug between recent versions of Playwright (1.60+) and Camoufox.
run to resolve:
```
pip install --upgrade camoufox playwright
camoufox fetch
playwright install firefox
```