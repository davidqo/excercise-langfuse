from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from logging import Logger
from pathlib import Path
from typing import ParamSpec, TypeVar

from langfuse import get_client, observe

P = ParamSpec("P")
R = TypeVar("R")


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_dotenv_if_present() -> None:
    env_path = _project_root() / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip().strip("\"'")
        if name and name not in os.environ:
            os.environ[name] = value


_load_dotenv_if_present()


@dataclass(frozen=True)
class LangfuseStatus:
    enabled: bool
    host: str
    missing_env: tuple[str, ...]
    dotenv_loaded: bool


def langfuse_status() -> LangfuseStatus:
    dotenv_path = _project_root() / ".env"
    missing_env = tuple(
        name
        for name in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY")
        if not os.getenv(name)
    )
    return LangfuseStatus(
        enabled=not missing_env,
        host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com"),
        missing_env=missing_env,
        dotenv_loaded=dotenv_path.exists(),
    )


def langfuse_enabled() -> bool:
    return langfuse_status().enabled


def log_langfuse_status(logger: Logger) -> None:
    status = langfuse_status()
    if status.enabled:
        logger.info(
            "Langfuse enabled: host=%s dotenv_present=%s",
            status.host,
            status.dotenv_loaded,
        )
        return

    logger.warning(
        "Langfuse disabled: missing env vars: %s dotenv_present=%s. Traces will not be sent.",
        ", ".join(status.missing_env),
        status.dotenv_loaded,
    )


def observe_if_enabled(*args, **kwargs):
    if langfuse_enabled():
        return observe(*args, **kwargs)

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        return func

    return decorator


def flush_langfuse() -> None:
    if langfuse_enabled():
        get_client().flush()


def flush_langfuse_with_logs(logger: Logger) -> None:
    status = langfuse_status()
    if not status.enabled:
        logger.info("Langfuse flush skipped: client is disabled.")
        return

    logger.info("Langfuse flush started.")
    try:
        get_client().flush()
    except Exception:
        logger.exception("Langfuse flush failed.")
        raise
    logger.info("Langfuse flush finished.")

