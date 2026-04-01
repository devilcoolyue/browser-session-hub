"""CLI entry points for Browser Session Hub."""

from __future__ import annotations

import argparse
import logging
import sys

import uvicorn

from .app import create_app
from .config import BrowserSessionHubConfig


def _setup_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    for handler in root.handlers[:]:
        root.removeHandler(handler)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    )
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))


def main() -> None:
    """Run the service."""
    parser = argparse.ArgumentParser(
        prog="browser-session-hub",
        description="Self-hosted isolated browser sessions with CDP and noVNC previews",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args()

    _setup_logging(args.log_level)
    config = BrowserSessionHubConfig.from_env()
    if args.host:
        config.host = args.host
    if args.port:
        config.port = args.port

    uvicorn.run(
        create_app(config),
        host=config.host,
        port=config.port,
        log_level="warning",
    )
