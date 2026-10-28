"""Read and write the KindEro configuration file (TOML)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from .models import Config, ConfigError

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

_LIBRARY_TYPES = {"user", "group"}


def config_path() -> Path:
    """Return the config file location for this platform."""
    override = os.environ.get("KINDERO_CONFIG")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "kindero" / "config.toml"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "kindero" / "config.toml"
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "kindero" / "config.toml"


def load_config(path: Path | None = None) -> Config:
    """Load the config; environment variables override stored secrets."""
    path = Path(path) if path else config_path()
    if not path.is_file():
        raise ConfigError(f"No configuration found at {path}. Run `kindero init` first.")
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError, UnicodeDecodeError) as exc:
        raise ConfigError(f"Cannot read configuration {path}: {exc}") from exc

    zotero = data.get("zotero", {})
    kindle = data.get("kindle", {})
    smtp = data.get("smtp", {})
    try:
        cfg = Config(
            zotero_library_id=str(zotero.get("library_id", "")),
            zotero_api_key=str(zotero.get("api_key", "")),
            zotero_library_type=str(zotero.get("library_type", "user")),
            kindle_email=str(kindle.get("email", "")),
            sender_email=str(smtp.get("sender", "")),
            smtp_host=str(smtp.get("host", "")),
            smtp_port=int(smtp.get("port", 587)),
            smtp_user=str(smtp.get("user", "")),
            smtp_password=str(smtp.get("password", "")),
            smtp_ssl=bool(smtp.get("ssl", False)),
        )
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"Invalid value in {path}: {exc}") from exc

    if cfg.zotero_library_type not in _LIBRARY_TYPES:
        raise ConfigError(
            f"Invalid library_type {cfg.zotero_library_type!r} in {path} "
            "(expected 'user' or 'group')."
        )
    cfg.smtp_password = os.environ.get("KINDERO_SMTP_PASSWORD") or cfg.smtp_password
    cfg.zotero_api_key = os.environ.get("KINDERO_ZOTERO_API_KEY") or cfg.zotero_api_key
    return cfg


def _q(value: object) -> str:
    """Render a value as a TOML basic string / bool / int."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    out = []
    for ch in str(value):
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif ord(ch) < 0x20 or ord(ch) == 0x7F:
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def save_config(cfg: Config, path: Path | None = None) -> Path:
    """Write the config as TOML (owner-only permissions on POSIX); return its path."""
    path = Path(path) if path else config_path()
    sections = {
        "zotero": {
            "library_id": cfg.zotero_library_id,
            "api_key": cfg.zotero_api_key,
            "library_type": cfg.zotero_library_type,
        },
        "kindle": {"email": cfg.kindle_email},
        "smtp": {
            "host": cfg.smtp_host,
            "port": cfg.smtp_port,
            "user": cfg.smtp_user,
            "password": cfg.smtp_password,
            "ssl": cfg.smtp_ssl,
            "sender": cfg.sender_email,
        },
    }
    lines: list[str] = []
    for name, values in sections.items():
        lines.append(f"[{name}]")
        lines.extend(f"{key} = {_q(val)}" for key, val in values.items())
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    if os.name == "posix":
        os.chmod(path, 0o600)
    return path
