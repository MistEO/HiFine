"""Check Mirror 酱 for a full installer and hand a verified file to the desktop."""

import hashlib
import json
from pathlib import Path
import platform
import re
import sys
from urllib.parse import urlencode

from packaging.version import InvalidVersion, Version
from PySide6.QtCore import (
    QFile, QFileDevice, QIODevice, QLockFile, QObject, QSaveFile, QStandardPaths, QTimer, QUrl, Signal,
)
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from . import __version__


API_URL = "https://mirrorchyan.com/api/resources/HiFine/latest"
INSTALLERS = {
    ("win32", "x64"): ("win", "x64", "windows-x64-setup.exe"),
    ("darwin", "arm64"): ("macos", "arm64", "macOS-arm64.dmg"),
    ("darwin", "x64"): ("macos", "x64", "macOS-x86_64.dmg"),
    ("linux", "x64"): ("linux", "x64", "linux-amd64.deb"),
}
ERRORS = {
    7001: "Mirror 酱 CDK 已过期，请在设置中更换或续费。",
    7002: "Mirror 酱 CDK 无效，请在设置中检查输入。",
    7003: "Mirror 酱今日下载次数已用完，请明天再试。",
    7004: "此 Mirror 酱 CDK 不适用于 HiFine，请在设置中更换。",
    7005: "Mirror 酱 CDK 已被封禁，请联系 Mirror 酱售后。",
    8001: "当前平台暂无可用更新。",
    8009: "此 Mirror 酱测试 CDK 不支持下载安装包。",
}
NETWORK_ERROR = "暂时无法检查软件更新，请稍后重试。"
DOWNLOAD_ERROR = "安装包下载失败，下次启动时会重新检查。"
CHUNK_SIZE = 256 * 1024


def installer_target():
    machine = platform.machine().lower()
    arch = {"amd64": "x64", "x86_64": "x64", "aarch64": "arm64"}.get(machine, machine)
    return INSTALLERS.get((sys.platform, arch))


def update_directory() -> Path:
    return Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.CacheLocation)) / "updates"


def _json_object(body):
    try:
        result = json.loads(body)
    except (ValueError, UnicodeError, RecursionError):
        return {}
    return result if isinstance(result, dict) else {}


def _error_message(response, default):
    code = response.get("code")
    if type(code) is int and code:
        return ERRORS.get(code, f"Mirror 酱请求失败（错误码 {code}）。")
    return default


def _http_success(reply):
    status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
    return (reply.error() == QNetworkReply.NetworkError.NoError
            and status is not None and 200 <= status < 300)


class UpdateChecker(QObject):
    notice = Signal(str)
    installer_ready = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._network = QNetworkAccessManager(self)
        self._cached = QFile(self)
        self._cache_timer = QTimer(self, interval=0)
        self._cache_timer.timeout.connect(self._verify_cached)
        self._reply = None
        self._output = None
        self._lock = None

    def _get(self, url):
        request = QNetworkRequest(QUrl(url))
        request.setTransferTimeout(30_000)
        return self._network.get(request)

    def start(self, cdk):
        self.stop()
        target = installer_target()
        if target is None:
            self.notice.emit("当前平台暂无可用更新。")
            return
        os_name, arch, suffix = target
        # Mirror 酱 selects the full installer when current_version is empty.
        query = {"current_version": "", "os": os_name, "arch": arch, "user_agent": "hifine_desktop"}
        if cdk:
            query["cdk"] = cdk
        reply = self._get(f"{API_URL}?{urlencode(query)}")
        self._reply = reply
        has_cdk = bool(cdk)
        reply.finished.connect(lambda: self._checked(reply, has_cdk, suffix))
        reply.finished.connect(reply.deleteLater)

    def _checked(self, reply, has_cdk, suffix):
        if self._reply is not reply:
            return
        self._reply = None
        response = _json_object(reply.read(1024 * 1024).data())
        data = response.get("data")
        if (not _http_success(reply)
                or type(response.get("code")) is not int or response["code"] != 0
                or not isinstance(data, dict)):
            self.notice.emit(_error_message(response, NETWORK_ERROR))
            return
        try:
            version = Version(data["version_name"])
        except (KeyError, TypeError, InvalidVersion):
            self.notice.emit(NETWORK_ERROR)
            return
        if version <= Version(__version__):
            return
        if not has_cdk:
            self.notice.emit(f"发现 HiFine v{version}，在设置中填写 Mirror 酱 CDK 可自动下载。")
            return
        url = data.get("url")
        if not isinstance(url, str) or not url:
            self.notice.emit(f"发现 HiFine v{version}，Mirror 酱暂未提供下载地址。")
            return
        source = QUrl(url)
        checksum = data.get("sha256")
        if (not source.isValid() or source.scheme() != "https" or not source.host()
                or not isinstance(checksum, str) or not re.fullmatch("[0-9a-fA-F]{64}", checksum)
                or data.get("update_type", "full") != "full"):
            self.notice.emit("Mirror 酱返回的安装包信息不完整，无法验证安装包。")
            return

        folder = update_directory()
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError:
            self.notice.emit("无法创建安装包下载目录。")
            return
        self._version = str(version)
        self._path = folder / f"HiFine-{version}-{suffix}"
        self._checksum = checksum.lower()
        # Opening several photos can launch separate viewers at the same time.
        self._lock = QLockFile(str(self._path) + ".lock")
        self._lock.setStaleLockTime(0)
        if not self._lock.tryLock(0):
            if self._lock.error() != QLockFile.LockError.LockFailedError:
                self.notice.emit("无法写入安装包下载目录。")
            self._lock = None
            return
        self._url = url
        self._cached.setFileName(str(self._path))
        if self._cached.open(QIODevice.OpenModeFlag.ReadOnly):
            self._hash = hashlib.sha256()
            self._cache_timer.start()
        else:
            self._download()

    def _verify_cached(self):
        # Give the event loop time to paint photos between reads of a large installer.
        data = self._cached.read(4 * CHUNK_SIZE)
        self._hash.update(data.data())
        if data.size() == 4 * CHUNK_SIZE:
            return
        verified = (self._cached.error() == QFileDevice.FileError.NoError
                    and self._hash.hexdigest() == self._checksum)
        self._cache_timer.stop()
        self._cached.close()
        if verified:
            self._ready()
        else:
            self._download()

    def _download(self):
        self._output = QSaveFile(str(self._path))
        if not self._output.open(QIODevice.OpenModeFlag.WriteOnly):
            self._failed("无法保存安装包，请检查磁盘空间和下载目录。")
            return
        self.notice.emit(f"正在下载 HiFine v{self._version} 安装包…")
        self._hash = hashlib.sha256()
        self._prefix = bytearray()
        reply = self._get(self._url)
        self._reply = reply
        reply.setReadBufferSize(4 * CHUNK_SIZE)
        reply.readyRead.connect(lambda: self._read(reply))
        reply.finished.connect(lambda: self._transferred(reply))
        reply.finished.connect(reply.deleteLater)

    def _read(self, reply):
        if self._reply is not reply:
            return
        while reply.bytesAvailable():
            chunk = reply.read(CHUNK_SIZE)
            if chunk.isEmpty():
                break
            # Keep a small prefix for the JSON business error some CDN links return.
            data = chunk.data()
            if len(self._prefix) < 4096:
                self._prefix.extend(data[:4096 - len(self._prefix)])
            if self._output.write(chunk) != chunk.size():
                self._failed("无法保存安装包，请检查磁盘空间和下载目录。")
                return
            self._hash.update(data)

    def _transferred(self, reply):
        if self._reply is not reply:
            return
        self._read(reply)
        if self._reply is not reply:
            return
        self._reply = None
        successful = _http_success(reply)
        if not successful or self._hash.hexdigest() != self._checksum:
            message = (DOWNLOAD_ERROR if not successful
                       else "安装包 SHA-256 校验失败，已丢弃下载。")
            self._failed(_error_message(_json_object(self._prefix), message))
            return
        if not self._output.commit():
            self._failed("无法保存下载的安装包。")
            return
        self._output = None
        self._ready()

    def _ready(self):
        self._url = ""
        self.installer_ready.emit(self._version, str(self._path))

    def _failed(self, message):
        self.stop()
        self.notice.emit(message)

    def stop(self):
        self._cache_timer.stop()
        self._cached.close()
        reply, self._reply = self._reply, None
        if reply is not None:
            reply.abort()
        if self._output is not None:
            self._output.cancelWriting()
            self._output = None
        if self._lock is not None:
            self._lock.unlock()
            self._lock = None
        self._url = ""
