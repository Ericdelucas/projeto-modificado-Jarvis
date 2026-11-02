"""Dynamic desktop discovery and detached launches, without opening real windows."""

import importlib
import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from openjarvis.tools.open_app import (
    DesktopApp,
    OpenAppTool,
    application_directories,
    desktop_apps,
    exec_arguments,
    launch_environment,
)


def desktop(
    directory,
    filename="custom.desktop",
    *,
    name="Minha Aplicação",
    command="custom-app %U",
    extra="",
):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    path.write_text(
        f"[Desktop Entry]\nType=Application\nName={name}\nExec={command}\n{extra}\n"
    )
    return path


@pytest.fixture
def child():
    process = MagicMock(pid=1234)
    process.poll.return_value = None
    return process


@pytest.mark.parametrize(
    "query", ["Android Studio", "abra o Android Studio", "androidstudio"]
)
def test_discovers_unlisted_app_and_native_desktop_launch(tmp_path, child, query):
    desktop(
        tmp_path, name="Android Studio", command='"/opt/android studio/bin/studio" %f'
    )
    with (
        patch(
            "openjarvis.tools.open_app.shutil.which",
            side_effect=lambda command: "/usr/bin/gio" if command == "gio" else None,
        ),
        patch(
            "openjarvis.tools.open_app.subprocess.Popen", return_value=child
        ) as popen,
    ):
        result = OpenAppTool(directories=[tmp_path]).execute(app=query)
    assert result.success
    assert popen.call_args.args == (["/opt/android studio/bin/studio"],)
    args = popen.call_args.kwargs
    assert args["shell"] is False and args["start_new_session"] is True
    assert args["stdin"] == args["stdout"] == subprocess.DEVNULL
    assert hasattr(args["stderr"], "read")
    child.wait.assert_called_once_with(timeout=0.75)


def test_localized_name_and_vscode_abbreviation(tmp_path, child):
    desktop(
        tmp_path, name="Visual Studio Code", extra="Name[pt_BR]=Editor Fantástico\n"
    )
    with (
        patch("openjarvis.tools.open_app.shutil.which", return_value="/usr/bin/gio"),
        patch("openjarvis.tools.open_app.subprocess.Popen", return_value=child),
    ):
        tool = OpenAppTool(directories=[tmp_path])
        assert tool.execute(app="Editor Fantástico").success
        assert tool.execute(app="abra o VS Code").success


def test_user_hidden_entry_masks_system_entry(tmp_path):
    user, system = tmp_path / "user", tmp_path / "system"
    desktop(user, name="Hidden App", extra="Hidden=true")
    desktop(system, name="System App")
    assert desktop_apps([user, system]) == []


def test_duplicate_names_return_candidates_instead_of_random_launch(tmp_path, child):
    desktop(tmp_path, "one.desktop", name="Studio", command="studio-one")
    desktop(tmp_path, "two.desktop", name="Studio", command="studio-two")
    with patch("openjarvis.tools.open_app.subprocess.Popen") as popen:
        result = OpenAppTool(directories=[tmp_path]).execute(app="Studio")
    assert not result.success
    assert len(json.loads(result.content)["candidates"]) == 2
    popen.assert_not_called()


def test_exec_fallback_preserves_quoted_args_and_expands_field_codes(tmp_path, child):
    entry = desktop(
        tmp_path,
        name="Custom Tool",
        command='"/opt/custom app/start" --label %c %i %k %% %F',
        extra="Icon=custom-icon",
    )
    with (
        patch("openjarvis.tools.open_app.shutil.which", return_value=None),
        patch(
            "openjarvis.tools.open_app.subprocess.Popen", return_value=child
        ) as popen,
    ):
        result = OpenAppTool(directories=[tmp_path]).execute(app="Custom Tool")
    assert result.success
    assert popen.call_args.args[0] == [
        "/opt/custom app/start",
        "--label",
        "Custom Tool",
        "--icon",
        "custom-icon",
        str(entry),
        "%",
    ]


def test_terminal_and_invalid_field_code_in_fallback(tmp_path):
    app = DesktopApp(
        tmp_path / "cli.desktop", ("My CLI",), (), "my-cli %u", terminal=True
    )
    with patch(
        "openjarvis.tools.open_app.shutil.which",
        return_value="/usr/bin/x-terminal-emulator",
    ):
        assert exec_arguments(app) == ["/usr/bin/x-terminal-emulator", "-e", "my-cli"]
    with pytest.raises(ValueError):
        exec_arguments(DesktopApp(tmp_path / "bad.desktop", ("Bad",), (), "my-cli %Z"))


@pytest.mark.parametrize(
    "command",
    [
        "my-new-app",
        "firefox",
        "code",
        "google-chrome",
        "gnome-terminal",
        "/opt/AppImage",
    ],
)
def test_any_existing_executable_can_launch_without_desktop(tmp_path, child, command):
    with (
        patch(
            "openjarvis.tools.open_app.shutil.which",
            side_effect=lambda name: "/resolved/app" if name == command else None,
        ),
        patch(
            "openjarvis.tools.open_app.subprocess.Popen", return_value=child
        ) as popen,
    ):
        assert OpenAppTool(directories=[tmp_path]).execute(app=command).success
    assert popen.call_args.args == (["/resolved/app"],)


@pytest.mark.parametrize(
    "value", ["not-installed", "firefox; touch /tmp/injected", "$(id)", "", None]
)
def test_missing_executables_and_shell_fragments_are_not_interpreted(tmp_path, value):
    with (
        patch("openjarvis.tools.open_app.shutil.which", return_value=None),
        patch("openjarvis.tools.open_app.subprocess.Popen") as popen,
    ):
        assert not OpenAppTool(directories=[tmp_path]).execute(app=value).success
    popen.assert_not_called()


def test_discovery_skips_bad_entries_and_refreshes_new_installations(tmp_path, child):
    (tmp_path / "bad.desktop").write_text("invalid data")
    tool = OpenAppTool(directories=[tmp_path])
    with (
        patch("openjarvis.tools.open_app.shutil.which", return_value=None),
        patch("openjarvis.tools.open_app.subprocess.Popen", return_value=child),
    ):
        assert not tool.execute(app="New Tool").success
        desktop(tmp_path, name="New Tool", command="/opt/new-tool")
        assert tool.execute(app="New Tool").success


def test_xdg_directories_and_packaged_app_exports(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "personal"))
    monkeypatch.setenv("XDG_DATA_DIRS", str(tmp_path / "system"))
    paths = application_directories()
    assert tmp_path / "personal/applications" in paths
    assert tmp_path / "system/applications" in paths
    assert any(str(path) == "/var/lib/snapd/desktop/applications" for path in paths)
    assert any("flatpak/exports" in str(path) for path in paths)


def test_discovery_cache_reuses_parsing_and_invalidates_changes(tmp_path):
    entry = desktop(tmp_path, name="Original", command="original")
    assert desktop_apps([tmp_path])[0].name == "Original"
    with patch("configparser.ConfigParser.read_string") as parse:
        assert desktop_apps([tmp_path])[0].name == "Original"
        parse.assert_not_called()
    entry.write_text(entry.read_text().replace("Original", "Updated Name"))
    assert desktop_apps([tmp_path])[0].name == "Updated Name"
    entry.unlink()
    assert desktop_apps([tmp_path]) == []


def test_permission_error_is_reported(tmp_path):
    with (
        patch(
            "openjarvis.tools.open_app.shutil.which", return_value="/usr/bin/example"
        ),
        patch(
            "openjarvis.tools.open_app.subprocess.Popen", side_effect=PermissionError
        ),
    ):
        assert not OpenAppTool(directories=[tmp_path]).execute(app="example").success


def test_delayed_launch_failure_reports_stderr(tmp_path, child):
    child.poll.return_value = 1

    def launch(*args, **kwargs):
        kwargs["stderr"].write("cannot open display")
        return child

    with (
        patch("openjarvis.tools.open_app.shutil.which", return_value="/usr/bin/app"),
        patch("openjarvis.tools.open_app.subprocess.Popen", side_effect=launch),
    ):
        result = OpenAppTool(directories=[tmp_path]).execute(app="example")
    assert not result.success
    assert "cannot open display" in result.content
    child.wait.assert_called_once_with(timeout=0.75)


def test_tool_registry_and_capability_inventory():
    import openjarvis.tools.open_app as module
    from openjarvis.core.registry import ToolRegistry
    from openjarvis.security.capabilities import canonical_tool_capabilities

    importlib.reload(module)
    assert ToolRegistry.get("open_app") is module.OpenAppTool
    assert canonical_tool_capabilities(module.OpenAppTool()) == ["code:execute"]


def test_desktop_id_disambiguates_two_installations(tmp_path, child):
    desktop(tmp_path, "one.desktop", name="Studio", command="studio-one")
    desktop(tmp_path, "two.desktop", name="Studio", command="studio-two")
    with (
        patch("openjarvis.tools.open_app.shutil.which", return_value="/usr/bin/gio"),
        patch(
            "openjarvis.tools.open_app.subprocess.Popen", return_value=child
        ) as popen,
    ):
        assert OpenAppTool(directories=[tmp_path]).execute(app="two.desktop").success
    assert popen.call_args.args[0] == ["studio-two"]


def test_browser_uses_desktop_default_without_app_catalogue(tmp_path, child):
    desktop(
        tmp_path, "unique.desktop", name="Some New Browser", command="new-browser %u"
    )
    with (
        patch(
            "openjarvis.tools.open_app.shutil.which",
            side_effect=lambda name: (
                "/usr/bin/" + name if name in {"gio", "xdg-settings"} else None
            ),
        ),
        patch(
            "openjarvis.tools.open_app.subprocess.run",
            return_value=MagicMock(stdout="unique.desktop\n"),
        ),
        patch(
            "openjarvis.tools.open_app.subprocess.Popen", return_value=child
        ) as popen,
    ):
        assert (
            OpenAppTool(directories=[tmp_path]).execute(app="abra o navegador").success
        )
    assert popen.call_args.args[0] == ["new-browser"]


def test_launch_removes_editor_snap_libraries_preserving_desktop(monkeypatch):
    monkeypatch.setenv("SNAP_NAME", "code")
    monkeypatch.setenv("GSETTINGS_SCHEMA_DIR", "/snap/code/schemas")
    monkeypatch.setenv("GTK_PATH", "/snap/code/gtk")
    monkeypatch.setenv("XDG_DATA_DIRS", "/snap/code/share:/usr/share")
    monkeypatch.setenv("XDG_DATA_DIRS_VSCODE_SNAP_ORIG", "/usr/share")
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/run/user/1000/bus")
    env = launch_environment()
    assert "GSETTINGS_SCHEMA_DIR" not in env
    assert "GTK_PATH" not in env
    assert "SNAP_NAME" not in env
    assert env["XDG_DATA_DIRS"] == "/usr/share"
    assert env["DISPLAY"] == ":0"
    assert env["DBUS_SESSION_BUS_ADDRESS"] == "unix:path=/run/user/1000/bus"


def test_browser_url_is_passed_as_single_argument_to_desktop_launcher(tmp_path, child):
    entry = desktop(tmp_path, name="Test Browser", command="browser %U")
    with (
        patch("openjarvis.tools.open_app.shutil.which", return_value="/usr/bin/gio"),
        patch(
            "openjarvis.tools.open_app.subprocess.Popen", return_value=child
        ) as popen,
    ):
        result = OpenAppTool(directories=[tmp_path]).execute(
            app="Test Browser",
            url="https://example.com/?q=hello%20world",
        )
    assert result.success
    assert popen.call_args.args[0] == [
        "/usr/bin/gio",
        "launch",
        str(entry),
        "https://example.com/?q=hello%20world",
    ]


@pytest.mark.parametrize("url", ["file:///etc/passwd", "javascript:alert(1)", "-flag"])
def test_browser_url_rejects_non_http_schemes(tmp_path, url):
    with patch("openjarvis.tools.open_app.subprocess.Popen") as popen:
        assert (
            not OpenAppTool(directories=[tmp_path])
            .execute(app="Browser", url=url)
            .success
        )
    popen.assert_not_called()
