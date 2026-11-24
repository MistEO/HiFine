# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import os
import plistlib
import shutil
import subprocess
import sys
import sysconfig
import tomllib

from PyInstaller.utils.hooks import copy_metadata

packaging = Path(SPECPATH)
root = packaging.parent
with (root / "pyproject.toml").open("rb") as stream:
    version = tomllib.load(stream)["project"]["version"]
if sys.platform == "win32":
    # Qt imports Windows' ICU ABI. Unrelated ICU/OpenSSL builds on a developer's
    # PATH can have the same DLL names but export different functions.
    windows = Path(os.environ["SystemRoot"])
    os.environ["PATH"] = os.pathsep.join(map(str, (
        Path(sys.executable).parent, Path(sys.base_prefix), windows / "System32", windows,
    )))
assets = root / "src" / "hifine" / "assets"
data = [(str(assets), "hifine/assets"), (str(packaging / "licenses"), "licenses"),
        (str(root / "LICENSE"), "licenses/HiFine")]
python_license = next(path for path in (Path(sys.base_prefix) / "LICENSE.txt",
                                       Path(sysconfig.get_path("stdlib")) / "LICENSE.txt")
                      if path.is_file())
data.append((str(python_license), "licenses/CPython"))
for dependency in ("Pillow", "pillow-heif", "PySide6-Essentials", "shiboken6", "pyinstaller", "packaging"):
    data.extend(copy_metadata(dependency))

analysis = Analysis(
    [str(root / "src/hifine/__main__.py")],
    pathex=[str(root / "src")],
    datas=data,
    excludes=["tkinter", "unittest", "pytest", "numpy", "matplotlib", "IPython"],
)
if sys.platform.startswith("linux") and shutil.which("dpkg-query"):
    # PyInstaller can collect host libraries as well as the Python wheels.
    # Obtain the exact notices from the Debian packages that own their files.
    system_files = set()
    for _, source, kind in analysis.binaries:
        path = Path(source)
        if kind != "SYMLINK" and path.is_absolute() and path.resolve().is_relative_to("/usr/lib"):
            system_files.add(str(path))
            system_files.add(str(path.resolve()))
    if system_files:
        owners = subprocess.run(["dpkg-query", "-S", *sorted(system_files)], text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        packages = sorted({line.split(":", 1)[0] for line in owners.stdout.splitlines() if ": " in line})
        for name in packages:
            notice = Path("/usr/share/doc") / name / "copyright"
            if notice.is_file():
                analysis.datas.append((f"licenses/debian/{name}/copyright", str(notice), "DATA"))
        if packages:
            sources = subprocess.check_output(
                ["dpkg-query", "-W", "-f=${Package}\t${source:Package}\t${source:Version}\n", *packages],
                text=True)
            index = Path(workpath) / "debian-sources.txt"
            index.write_text("Binary package\tSource package\tSource version\n" + sources, encoding="utf-8")
            analysis.datas.append(("licenses/debian/sources.txt", str(index), "DATA"))
pyz = PYZ(analysis.pure)
app_icon = packaging / ("macos/HiFine.icns" if sys.platform == "darwin" else "HiFine.ico")
exe = EXE(pyz, analysis.scripts, [], exclude_binaries=True, name="HiFine",
          console=False, icon=str(app_icon), upx=False)
coll = COLLECT(exe, analysis.binaries, analysis.datas, name="HiFine", upx=False)

if sys.platform == "darwin":
    with (packaging / "macos/Documents.plist").open("rb") as stream:
        document_types = plistlib.load(stream)
    document_types["CFBundleVersion"] = version
    document_types["CFBundleShortVersionString"] = version
    app = BUNDLE(coll, name="HiFine.app", icon=str(app_icon),
                 bundle_identifier="io.github.hifine.HiFine", version=version,
                 info_plist=document_types)
