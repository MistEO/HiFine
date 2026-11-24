"""Exercise the startup updater with Qt networking and local HTTP responses."""

from collections import deque
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
from threading import Event, Thread
from time import monotonic, sleep
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QSettings, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkProxy, QNetworkRequest
from PySide6.QtWidgets import QApplication

from hifine import updates


PACKAGE = b"HiFine test installer\n" * 8000
SIGNED_URL = "https://downloads.example.test/installer?signature=example"
CDK = "example key +&/"


def version_response(version="v0.10.0", **fields):
    return {"code": 0, "data": {"version_name": version, **fields}}


def download_response(**overrides):
    fields = dict(url=SIGNED_URL, sha256=hashlib.sha256(PACKAGE).hexdigest(),
                  filesize=len(PACKAGE), update_type="full")
    fields.update(overrides)
    return version_response(**fields)


@pytest.fixture(scope="module")
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def wait_until(app, predicate):
    deadline = monotonic() + 5
    while not predicate():
        assert monotonic() < deadline, "timed out waiting for the updater"
        app.processEvents()
        sleep(0.002)


@pytest.fixture
def mirror(app, monkeypatch, tmp_path):
    answers = deque()
    requests, finished, readable = [], [], []
    resume = Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if not answers:
                self.send_error(500, "unexpected request")
                return
            status, body, pause = answers.popleft()
            is_json = isinstance(body, dict)
            if is_json:
                body = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json" if is_json else "application/octet-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                if pause:
                    prefix = len(body) // 2
                    self.wfile.write(body[:prefix])
                    self.wfile.flush()
                    resume.wait(5)
                    body = body[prefix:]
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass  # stop() closed the connection during the partial download.

        def log_message(self, fmt, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
    thread.start()
    local_url = QUrl(f"http://127.0.0.1:{server.server_port}/")
    real_get = QNetworkAccessManager.get

    def local_get(manager, request):
        url = bytes(request.url().toEncoded()).decode("ascii")
        requests.append(url)
        manager.setProxy(QNetworkProxy(QNetworkProxy.ProxyType.NoProxy))
        routed = QNetworkRequest(request)
        routed.setUrl(local_url)
        reply = real_get(manager, routed)
        reply.finished.connect(lambda: finished.append(url))
        reply.readyRead.connect(lambda: readable.append(url))
        return reply

    def answer(body, *, status=200, pause=False):
        answers.append((status, body, pause))

    monkeypatch.setattr(QNetworkAccessManager, "get", local_get)
    monkeypatch.setattr(updates, "installer_target", lambda: ("win", "x64", "windows-x64-setup.exe"))
    monkeypatch.setattr(updates, "update_directory", lambda: tmp_path)
    monkeypatch.setattr(updates, "__version__", "0.9.0")
    checker = updates.UpdateChecker()
    notices, opened = [], []
    checker.notice.connect(notices.append)
    checker.installer_ready.connect(lambda version, path: opened.append((version, Path(path))))
    try:
        yield SimpleNamespace(checker=checker, answer=answer, requests=requests, opened=opened,
                              notices=notices, readable=readable, resume=resume,
                              wait=lambda count: wait_until(app, lambda: len(finished) >= count))
    finally:
        checker.stop()
        resume.set()
        checker.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        server.shutdown()
        server.server_close()
        thread.join(2)


def query(url):
    return parse_qs(urlsplit(url).query, keep_blank_values=True)


@pytest.mark.parametrize(("os_id", "machine", "target"), [
    ("win32", "AMD64", ("win", "x64", "windows-x64-setup.exe")),
    ("darwin", "arm64", ("macos", "arm64", "macOS-arm64.dmg")),
    ("darwin", "x86_64", ("macos", "x64", "macOS-x86_64.dmg")),
    ("linux", "x86_64", ("linux", "x64", "linux-amd64.deb")),
    ("linux", "aarch64", None),
    ("win32", "ARM64", None),
])
def test_published_installer_targets(monkeypatch, os_id, machine, target):
    monkeypatch.setattr(updates, "sys", SimpleNamespace(platform=os_id))
    monkeypatch.setattr(updates.platform, "machine", lambda: machine)
    assert updates.installer_target() == target


@pytest.mark.parametrize("extra", [{}, {"url": SIGNED_URL}])
def test_new_version_without_cdk_only_notifies(mirror, extra):
    mirror.answer(version_response(**extra))
    mirror.checker.start("")
    mirror.wait(1)
    assert len(mirror.requests) == 1
    url = mirror.requests[0]
    assert url.split("?")[0] == "https://mirrorchyan.com/api/resources/HiFine/latest"
    params = query(url)
    assert (params["os"], params["arch"], params["current_version"]) == (["win"], ["x64"], [""])
    assert "cdk" not in params
    assert any("0.10.0" in notice for notice in mirror.notices)
    assert not mirror.opened


@pytest.mark.parametrize("remote", ["v0.9.0", "v0.8.10", "v0.9.0-rc.2"])
def test_same_older_and_prerelease_versions_never_download(mirror, remote):
    mirror.answer(version_response(remote, url=SIGNED_URL))
    mirror.checker.start(CDK)
    mirror.wait(1)
    assert len(mirror.requests) == 1
    assert query(mirror.requests[0])["cdk"] == [CDK]
    assert not mirror.opened


def test_downloads_full_installer_and_opens_only_after_verification(mirror):
    mirror.answer(download_response())
    mirror.answer(PACKAGE)
    mirror.checker.start(CDK)
    mirror.wait(2)
    authorized, download = mirror.requests
    assert query(authorized)["cdk"] == [CDK]
    assert query(authorized)["current_version"] == [""]
    assert download == SIGNED_URL
    (version, path), = mirror.opened
    assert version.lstrip("v") == "0.10.0"
    assert path.is_absolute() and path.name.endswith("windows-x64-setup.exe")
    assert path.read_bytes() == PACKAGE


def test_rejects_corrupt_installer(mirror, tmp_path):
    mirror.answer(download_response())
    mirror.answer(b"x" * len(PACKAGE))
    mirror.checker.start(CDK)
    mirror.wait(2)
    assert not mirror.opened
    assert mirror.notices and not any(path.is_file() for path in tmp_path.rglob("*"))


@pytest.mark.parametrize("fields", [{"sha256": ""}, {"url": "http://example.test/installer"},
                                     {"update_type": "incremental"}])
def test_requires_a_verifiable_full_installer_before_downloading(mirror, fields):
    mirror.answer(download_response(**fields))
    mirror.checker.start(CDK)
    mirror.wait(1)
    assert len(mirror.requests) == 1 and not mirror.opened
    assert mirror.notices


@pytest.mark.parametrize("matching", [True, False])
def test_cached_installer_checked_before_reuse(mirror, app, tmp_path, matching):
    path = tmp_path / "HiFine-0.10.0-windows-x64-setup.exe"
    path.write_bytes(PACKAGE if matching else b"incomplete")
    mirror.answer(download_response())
    if not matching:
        mirror.answer(PACKAGE)
    mirror.checker.start(CDK)
    wait_until(app, lambda: bool(mirror.opened))
    assert mirror.requests.count(SIGNED_URL) == (0 if matching else 1)
    assert len(mirror.opened) == 1 and mirror.opened[0][1] == path
    assert path.read_bytes() == PACKAGE


def test_cdk_error_explained_without_disclosing_credentials(mirror):
    mirror.answer({"code": 7002, "msg": "invalid"}, status=403)
    mirror.checker.start(CDK)
    mirror.wait(1)
    assert len(mirror.requests) == 1 and not mirror.opened
    assert "CDK" in mirror.notices[-1]
    assert CDK not in "".join(mirror.notices)


def test_invalid_version_response_reports_failure(mirror):
    mirror.answer(b"<html>Service unavailable</html>", status=503)
    mirror.checker.start("")
    mirror.wait(1)
    assert len(mirror.requests) == 1
    assert mirror.notices and not mirror.opened


def test_expired_download_waits_until_next_launch(mirror):
    mirror.answer(download_response())
    mirror.answer(b"expired", status=410)
    mirror.checker.start(CDK)
    mirror.wait(2)
    assert len(mirror.requests) == 2 and mirror.requests[1] == SIGNED_URL
    assert not mirror.opened and mirror.notices


def test_stopping_partial_download_removes_it_and_does_not_open(mirror, app, tmp_path):
    mirror.answer(download_response())
    mirror.answer(PACKAGE, pause=True)
    mirror.checker.start(CDK)
    wait_until(app, lambda: SIGNED_URL in mirror.readable)
    mirror.checker.stop()
    mirror.resume.set()
    mirror.wait(2)
    assert not mirror.opened
    assert not any(path.is_file() for path in tmp_path.rglob("*"))


@pytest.mark.parametrize("can_open", [True, False])
def test_viewer_uses_saved_cdk_and_opens_the_local_package(mirror, monkeypatch, tmp_path, can_open):
    from hifine.settings import AppSettings
    from hifine.viewer import MainWindow

    store = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    AppSettings(mirrorchyan_cdk=CDK).save(store)
    mirror.answer(download_response())
    mirror.answer(PACKAGE)
    paths = []

    def open_package(url):
        assert url.isLocalFile()
        paths.append(Path(url.toLocalFile()))
        return can_open

    monkeypatch.setattr(QDesktopServices, "openUrl", open_package)
    window = MainWindow(settings_store=store)
    try:
        window.show()
        window.start_update_check()
        mirror.wait(2)
        assert query(mirror.requests[0])["cdk"] == [CDK]
        path, = paths
        assert path.read_bytes() == PACKAGE
        message = window.statusBar().currentMessage()
        assert ("0.10.0" if can_open else path.name) in message
        assert window.statusBar().isVisible()
    finally:
        window.close()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
