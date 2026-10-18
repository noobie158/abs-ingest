from __future__ import annotations

import logging

import requests

from .config import Config
from .logsetup import log


class Notifier:
    """Optional phone push through ntfy. Does nothing unless notify.ntfy_topic is set."""

    def __init__(self, cfg: Config):
        """Keep the notification settings from the loaded application configuration."""
        self.cfg = cfg

    @property
    def enabled(self) -> bool:
        """Whether a topic is configured for outbound notifications."""
        return bool(self.cfg.ntfy_topic)

    def send(self, event: str, title: str, message: str) -> None:
        """Send an allowed filed/review/failed event; log network errors without stopping ingest."""
        if not self.enabled or event not in self.cfg.notify_on:
            return
        priority = {"failed": "high", "review": "default"}.get(event, "low")
        try:
            requests.post(
                f"{self.cfg.ntfy_server.rstrip('/')}/{self.cfg.ntfy_topic}",
                data=message.encode("utf-8"),
                headers={"Title": title.encode("utf-8"), "Priority": priority},
                timeout=10,
            ).raise_for_status()
        except requests.RequestException as exc:
            log.log(logging.WARNING, "[notify  ] could not send notification: %s", exc)
