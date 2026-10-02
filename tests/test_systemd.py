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


def _install(tmp_path, monkeypatch, dashboard: bool):
    calls = []
    monkeypatch.setattr(systemd, "_check_run_requirements", lambda: None)
    monkeypatch.setattr(systemd, "_get_username", lambda: "pi")
    monkeypatch.setattr(systemd, "_SYSTEMD_DIR", tmp_path / "units")
    monkeypatch.setattr(systemd, "dashboard_installed", lambda: dashboard)
    monkeypatch.setattr(systemd.subprocess, "run", lambda cmd, **kw: calls.append(cmd))
    config = tmp_path / "config.json"
    config.write_text("{}")
    systemd.install_systemd(config)
    return calls


def test_the_services_run_this_environments_pvpi_with_no_uv_run(tmp_path, monkeypatch):
    calls = _install(tmp_path, monkeypatch, dashboard=True)
    pvpi = Path(systemd.sys.executable).parent / "pvpi"
    manager = (tmp_path / "units" / "pvpi_manager.service").read_text()
    assert f"ExecStart={pvpi} manager --config {tmp_path / 'config.json'}\n" in manager
    assert ["systemctl", "enable", "pvpi_dashboard.service"] in calls
    assert not any("uv" in Path(u.read_text().split("ExecStart=")[1].split()[0]).name for u in (tmp_path / "units").iterdir())


def test_without_the_dashboard_extra_its_service_is_left_out(tmp_path, monkeypatch):
    (tmp_path / "units").mkdir()
    (tmp_path / "units" / "pvpi_dashboard.service").write_text("[Service]\n")  # from an earlier install
    calls = _install(tmp_path, monkeypatch, dashboard=False)
    assert sorted(u.name for u in (tmp_path / "units").iterdir()) == ["pvpi_manager.service", "pvpi_uart.service"]
    assert ["systemctl", "disable", "--now", "pvpi_dashboard.service"] in calls
    assert ["systemctl", "enable", "pvpi_dashboard.service"] not in calls
