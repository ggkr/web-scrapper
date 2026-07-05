import configparser
import html
import logging
import os
import smtplib
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests

from core.logging_config import (
    clear_exception_traces,
    get_exception_traces,
    get_log_file,
)
from core.registry import get_scraper

logger = logging.getLogger(__name__)


class ScannerRunner:
    def __init__(self, config: dict):
        self.config = config
        self.has_err = False

    def sync_with_cache(self, scraper, listings):
        return scraper.cache_manager.sync(listings)

    @staticmethod
    def _format_error_email_bodies(log_file: str | None) -> tuple[str, str]:
        traces = get_exception_traces()
        if traces:
            trace_block = "\n\n".join(
                f"--- Error {index} ---\n{entry}"
                for index, entry in enumerate(traces, 1)
            )
            text = (
                "Exceptions were thrown during scrapping operations.\n\n"
                f"{trace_block}\n"
            )
            html_traces = html.escape(trace_block)
            html_body = (
                "<html><body>"
                "<p>Exceptions were thrown during scrapping operations.</p>"
                f"<pre>{html_traces}</pre>"
            )
        else:
            text = "Some exceptions were thrown during scrapping operations.\n"
            html_body = (
                "<html><body>"
                "<p>Some exceptions were thrown during scrapping operations.</p>"
            )

        if log_file:
            text += "\nPlease review the attached log file for the full run log.\n"
            html_body += (
                "<p>Please review the attached log file for the full run log.</p>"
            )
        else:
            text += "\nNo log file was configured; check console output for details.\n"
            html_body += (
                "<p>No log file was configured; check console output for details.</p>"
            )

        html_body += "</body></html>"
        return text, html_body

    def send_mail(self):
        email_cfg = self.config["notifications"].get("email", {})
        if not email_cfg.get("enabled_on_error", True):
            logger.debug("Error email disabled in config, skipping send")
            return

        log_file = get_log_file()
        logging.error(
            "Error encountered in script - sending email%s",
            f" with log: {log_file}" if log_file else " (no log file configured)",
        )
        message = MIMEMultipart("alternative")
        message["Subject"] = email_cfg.get("subject", "Scrapper - Encountered Errors")
        message["From"] = email_cfg["sender"]
        message["To"] = email_cfg["recipient"]
        text, html_body = self._format_error_email_bodies(log_file)
        message.attach(MIMEText(text, "plain"))
        message.attach(MIMEText(html_body, "html"))

        if log_file:
            part = MIMEBase("application", "octet-stream")
            with open(log_file, "rb") as log_file_handle:
                part.set_payload(log_file_handle.read())
            encoders.encode_base64(part)
            part.add_header(
                "Content-Disposition",
                f"attachment; filename={os.path.basename(log_file)}",
            )
            message.attach(part)

        with smtplib.SMTP(email_cfg["smtp_server"], email_cfg["smtp_port"]) as server:
            server.sendmail(
                email_cfg["sender"], email_cfg["recipient"], message.as_string()
            )
        logger.debug("Error email sent to %s", email_cfg["recipient"])

    def send_telegram(self, new_results):
        notifications = self.config["notifications"]
        message_template = notifications["message_template"]
        subscriptions = notifications["telegram_subscriptions"]

        if not new_results:
            logger.debug("No new results, skipping Telegram notifications")
            return

        logger.debug(
            "Sending Telegram notifications for %s new listings to %s subscribers",
            len(new_results),
            len(subscriptions),
        )

        for result in new_results:
            try:
                msg = message_template.format(**result.fields)
                for subscriber in subscriptions:
                    conf_path = f"./subscribers/{subscriber}.conf"
                    logger.debug(
                        "Sending Telegram notification for id=%s to subscriber=%s",
                        result.id,
                        subscriber,
                    )
                    self._send_telegram_message(msg, conf_path)
            except Exception:
                logging.exception("failed to send telegram notification")
                self.has_err = True

    @staticmethod
    def _send_telegram_message(message: str, conf_path: str) -> None:
        parser = configparser.ConfigParser()
        parser.read(conf_path, encoding="utf-8")
        token = parser["telegram"]["token"]
        chat_id = parser["telegram"]["chat_id"]
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        logger.debug(
            "Posting Telegram message to chat_id=%s via %s", chat_id, conf_path
        )
        response = requests.post(
            url,
            json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"},
            timeout=30,
        )
        response.raise_for_status()

    def run(self):
        clear_exception_traces()
        source_name = self.config.get("name", self.config["source"])
        try:
            self._run_scan(source_name)
        except Exception:
            logging.exception("Scan aborted for %s", source_name)
            self.send_mail()
            raise

    def _run_scan(self, source_name: str) -> None:
        source = self.config["source"]
        scraper_cls = get_scraper(source)
        if scraper_cls is None:
            raise ValueError(f"No scraper plugin registered for source: {source}")

        logger.debug("Running scraper plugin %s (%s)", source, scraper_cls.__name__)
        scraper = scraper_cls(self.config)

        logger.debug("Starting scan for %s", source_name)
        listings = scraper.scan()
        logger.debug("Scan returned %s listings", len(listings))

        new_results = self.sync_with_cache(scraper, listings)

        logging.info(
            "Scan complete for %s: %s listings, %s new",
            source_name,
            len(listings),
            len(new_results),
        )

        self.send_telegram(new_results)

        self.has_err = self.has_err or scraper.has_err or scraper.cache_manager.has_err
        if self.has_err:
            self.send_mail()
        else:
            logger.debug("Scan finished without errors")
