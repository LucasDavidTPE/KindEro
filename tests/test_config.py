import os
import sys

import pytest

from kindero import config
from kindero.models import Config, ConfigError


def test_config_path_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("KINDERO_CONFIG", str(tmp_path / "x.toml"))
    assert config.config_path() == tmp_path / "x.toml"


@pytest.mark.skipif(sys.platform in ("win32", "darwin"), reason="XDG only")
def test_config_path_xdg(monkeypatch, tmp_path):
    monkeypatch.delenv("KINDERO_CONFIG", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert config.config_path() == tmp_path / "kindero" / "config.toml"


def test_round_trip_with_escaping(tmp_path):
    cfg = Config(
        zotero_library_id="123", zotero_api_key='k"ey\\x', zotero_library_type="group",
        kindle_email="me_a@kindle.com", sender_email="me@example.com",
        smtp_host="smtp.example.com", smtp_port=465, smtp_user="me",
        smtp_password='pa"ss\\wo\nrd é', smtp_ssl=True,
    )
    path = config.save_config(cfg, tmp_path / "sub" / "c.toml")
    assert path.is_file()
    assert config.load_config(path) == cfg


@pytest.mark.skipif(os.name != "posix", reason="POSIX permissions")
def test_save_permissions(tmp_path):
    path = config.save_config(Config(), tmp_path / "c.toml")
    assert path.stat().st_mode & 0o777 == 0o600


def test_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="kindero init"):
        config.load_config(tmp_path / "nope.toml")


def test_env_overrides(tmp_path, monkeypatch):
    path = config.save_config(Config(smtp_password="file", zotero_api_key="file"), tmp_path / "c.toml")
    monkeypatch.setenv("KINDERO_SMTP_PASSWORD", "envpw")
    monkeypatch.setenv("KINDERO_ZOTERO_API_KEY", "envkey")
    cfg = config.load_config(path)
    assert cfg.smtp_password == "envpw"
    assert cfg.zotero_api_key == "envkey"


def test_invalid_library_type(tmp_path):
    path = tmp_path / "c.toml"
    path.write_text('[zotero]\nlibrary_type = "team"\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="library_type"):
        config.load_config(path)


def test_invalid_toml(tmp_path):
    path = tmp_path / "c.toml"
    path.write_text("[zotero\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        config.load_config(path)
