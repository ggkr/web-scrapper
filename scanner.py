#!/usr/bin/env python3

import argparse
import logging

import yaml

import plugins
from core.logging_config import setup_logging
from core.registry import list_scrapers
from core.runner import ScannerRunner


def load_config(path: str) -> dict:
    with open(path, encoding="utf-8") as config_file:
        return yaml.safe_load(config_file)


def main():
    parser = argparse.ArgumentParser(description="Scan bulletin boards for new listings.")
    parser.add_argument(
        "--config",
        required=True,
        help="Path to YAML config file (e.g. config/agora.yaml or config/yad2.yaml)",
    )
    parser.add_argument(
        "--log-file",
        help="Log file path (overrides logging.file in config)",
    )
    parser.add_argument(
        "--log-level",
        help="Log level: DEBUG, INFO, WARNING, ERROR, or CRITICAL (overrides logging.level in config)",
    )
    parser.add_argument(
        "--log-timestamp",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Include the current date in the log file name (overrides logging.timestamp in config)",
    )
    args = parser.parse_args()

    config = load_config(args.config)
    setup_logging(
        config,
        log_file=args.log_file,
        log_level=args.log_level,
        log_timestamp=args.log_timestamp,
    )
    plugins.discover_plugins()

    if config["source"] not in list_scrapers():
        available = ", ".join(sorted(list_scrapers())) or "(none)"
        raise SystemExit(
            f"Unsupported source: {config['source']}. Available plugins: {available}"
        )

    logging.info("Starting scan with config: %s", args.config)
    ScannerRunner(config).run()
    print("script ended")


if __name__ == "__main__":
    main()