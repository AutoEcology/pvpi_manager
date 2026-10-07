from pathlib import Path

import pytest

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


def _install(tmp_path, monkeypatch, dashboard: bool | None, disabled=()):
    calls = []
    monkeypatch.setattr(systemd, "_check_run_requirements", lambda: None)
    monkeypatch.setattr(systemd, "_get_username", lambda: "pi")
    monkeypatch.setattr(systemd, "_SYSTEMD_DIR", tmp_path / "units")

    def run(cmd, **kw):
        calls.append(cmd)
        enabled = cmd[:3] == ["systemctl", "is-enabled", "--quiet"] and cmd[3] not in disabled
        return systemd.subprocess.CompletedProcess(cmd, 0 if enabled or cmd[1] != "is-enabled" else 1)

    monkeypatch.setattr(systemd.subprocess, "run", run)
    config = tmp_path / "config.json"
    config.write_text("{}")
    systemd.install_systemd(config, dashboard=dashboard)
    return calls


def test_the_services_run_this_environments_pvpi_with_no_uv_run(tmp_path, monkeypatch):
    calls = _install(tmp_path, monkeypatch, dashboard=True)
    pvpi = Path(systemd.sys.executable).parent / "pvpi"
    manager = (tmp_path / "units" / "pvpi_manager.service").read_text()
    assert f"ExecStart={pvpi} manager --config {tmp_path / 'config.json'}\n" in manager
    assert ["systemctl", "enable", "pvpi_dashboard.service"] in calls
    assert not any(
        "uv" in Path(u.read_text().split("ExecStart=")[1].split()[0]).name for u in (tmp_path / "units").iterdir()
    )


@pytest.mark.parametrize(
    "dashboard, installed_before, installed_after",
    [
        (True, False, True),
        (False, True, False),
        (None, True, True),  # installing again (e.g. after an update) keeps it
        (None, False, False),  # and it's opt-in
    ],
)
def test_the_dashboard_service_is_opt_in(tmp_path, monkeypatch, dashboard, installed_before, installed_after):
    (tmp_path / "units").mkdir()
    if installed_before:
        (tmp_path / "units" / "pvpi_dashboard.service").write_text("[Service]\n")
    calls = _install(tmp_path, monkeypatch, dashboard=dashboard)
    assert (tmp_path / "units" / "pvpi_dashboard.service").exists() == installed_after
    assert (["systemctl", "enable", "pvpi_dashboard.service"] in calls) == installed_after
    assert (["systemctl", "disable", "--now", "pvpi_dashboard.service"] in calls) == (
        installed_before and not installed_after
    )
    assert ["systemctl", "restart", "pvpi_manager.service"] in calls


def test_a_service_disabled_since_it_was_installed_stays_disabled(tmp_path, monkeypatch):
    (tmp_path / "units").mkdir()
    for name in systemd.SERVICES:
        (tmp_path / "units" / name).write_text("[Service]\n")
    calls = _install(tmp_path, monkeypatch, dashboard=True, disabled=("pvpi_dashboard.service",))
    assert "pvpi dashboard" in (tmp_path / "units" / "pvpi_dashboard.service").read_text()  # updated
    assert ["systemctl", "enable", "pvpi_dashboard.service"] not in calls
    assert ["systemctl", "restart", "pvpi_dashboard.service"] not in calls
    assert ["systemctl", "restart", "pvpi_manager.service"] in calls
