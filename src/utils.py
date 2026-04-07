import logging
import os
from urllib.parse import urljoin, urldefrag, urlparse

import yaml


def setup_logging(config: dict) -> logging.Logger:
    """Set up structured logging with file and console handlers."""
    log_config = config.get("logging", {})
    level_name = log_config.get("level", "INFO")
    log_file = log_config.get("file", "output/crawl_log.txt")

    level = getattr(logging, level_name.upper(), logging.INFO)

    # Configure the root logger so all module-level loggers (src.orchestrator, etc.) inherit
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Also configure the named logger for direct use
    logger = logging.getLogger("safco_scraper")
    logger.setLevel(level)

    # Avoid adding duplicate handlers
    if root_logger.handlers:
        return logger

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # File handler
    log_dir = os.path.dirname(log_file)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
    file_handler = logging.FileHandler(log_file, mode="a", encoding="utf-8")
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    return logger


def normalize_url(url: str, base_url: str) -> str:
    """Resolve relative URLs and strip fragments and trailing slashes."""
    # Resolve relative URL against base
    resolved = urljoin(base_url, url)
    # Strip fragment
    resolved, _ = urldefrag(resolved)
    # Strip trailing slash (but keep root "/" intact)
    if resolved.endswith("/") and urlparse(resolved).path != "/":
        resolved = resolved.rstrip("/")
    return resolved


def load_config(path: str = "config.yaml") -> dict:
    """Load YAML configuration file."""
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)
