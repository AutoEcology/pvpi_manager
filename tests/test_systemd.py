from pathlib import Path

from pvpi import systemd


def test_the_config_path_is_the_installed_services_one(tmp_path, monkeypatch):
    monkeypatch.setattr(systemd, "_get_project_dir", lambda: tmp_path / "repo")
    assert systemd.config_path(tmp_path) == tmp_path / "repo" / "config.json"  # nothing installed
    (tmp_path / "pvpi_manager.service").write_text(
        "[Service]\nExecStart=/usr/bin/uv run --project /x pvpi manager --config /etc/pvpi/site.json\n"
    )
    assert systemd.config_path(tmp_path) == Path("/etc/pvpi/site.json")
    (tmp_path / "pvpi_manager.service").write_text("[Service]\nExecStart=/usr/bin/pvpi manager\n")
    assert systemd.config_path(tmp_path) == tmp_path / "repo" / "config.json"


def test_an_installed_package_keeps_its_config_in_the_users_config_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(systemd, "_get_project_dir", lambda: None)
    monkeypatch.setattr(systemd, "_user_home", lambda: tmp_path)
    assert systemd.default_config_path() == tmp_path / ".config" / "pvpi" / "config.json"


def test_the_services_names_are_public():
    assert systemd.SERVICES == ["pvpi_uart.service", "pvpi_manager.service", "pvpi_dashboard.service"]
