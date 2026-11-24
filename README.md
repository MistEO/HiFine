# HiFine

HiFine 是 Windows、macOS 和 Linux 上的桌面图片查看器，内置 HIF / HEIF 解码器，可读取相机拍摄的 10 位 HIF 和照片中的 EXIF 信息。双击打开一张照片，就能用方向键连续翻页，或从左侧缩略图直接跳到同文件夹的另一张。HiFine 会在后台预读相邻图片。

[下载最新版][latest-release] · [版本记录](https://github.com/MistEO/HiFine/releases)

![HiFine 在 Windows 上打开 HIF 样片，左侧为文件夹缩略图，右侧为照片信息](docs/preview.webp)

## 下载

在发布页按系统选择安装包，也可以在附件列表（Assets）中按文件名结尾查找。[打开最新版发布页][latest-release]

| 系统 | 安装包文件名结尾 |
| --- | --- |
| Windows x64 | `windows-x64-setup.exe` |
| Ubuntu 24.04 amd64 | `linux-amd64.deb` |
| macOS 14 及以上，Apple 芯片 | `macOS-arm64.dmg` |
| macOS 14 及以上，Intel 处理器 | `macOS-x86_64.dmg` |

最新版安装包及 HEIF 组件源码包的 SHA-256 校验值见 [SHA256SUMS.txt](https://github.com/MistEO/HiFine/releases/latest/download/SHA256SUMS.txt)。

### 安装与双击打开

- **Windows**　运行安装程序。安装按当前用户生效。完成后右击一张图片，选择“打开方式”中的 HiFine，并选择始终使用，即可双击打开同一扩展名的图片。也可以从安装完成页进入系统“默认应用”逐项设置。资源管理器使用中图标或更大图标时，可显示 HIF、HEIF、HEIC 缩略图。其他图片由系统已安装的缩略图程序处理。
- **Ubuntu**　在下载目录运行 `sudo apt install ./HiFine-*-linux-amd64.deb`。如果目录里有多个版本，把 `*` 换成要安装的版本号。在文件管理器的图片属性中将 HiFine 设为默认应用。安装包还包含供 GNOME Files 和 Thunar 使用的 HEIF 缩略图程序。
- **macOS**　打开对应芯片的 DMG，将 HiFine 拖入“应用程序”。在 Finder 中选中图片，按 ⌘I，在“打开方式”中选择 HiFine，再点“全部更改”。若不清楚芯片型号，可在苹果菜单的“关于本机”中查看。

macOS 版采用 ad-hoc 本地签名，尚未经 Apple 公证。首次启动如果系统提示无法验证，确认下载来源后可在“系统设置 → 隐私与安全性”中选择“仍要打开”。随包的 Quick Look 扩展使用 macOS ImageIO 解码，Finder 中不同相机 HIF 的缩略图兼容性仍待实机验证。[Apple 的首次打开说明](https://support.apple.com/zh-cn/102445)

### 软件更新

每次启动查看器时，HiFine 会在后台通过 Mirror 酱检查当前平台的最新版本。CDK 留空时，发现新版会在窗口底部提示。要自动下载安装包，在“设置 → 软件更新”中填写 CDK 并保存。HiFine 将 CDK 存入当前用户的本地设置，下次查版本时一并发送给 Mirror 酱。输入框右侧的链接可打开 HiFine 的 Mirror 酱项目页。

下次启动发现新版时，HiFine 会下载安装包，校验 SHA-256 后交给系统打开。你可以继续看图，也可以关闭 HiFine 后按安装程序的提示完成更新。在 macOS 上将新版拖入“应用程序”即可。若系统无法打开安装包，窗口底部会提示文件位置。

## 看图

| 操作 | 快捷方式 |
| --- | --- |
| 打开图片 | 拖入窗口，或按 Ctrl+O（macOS 为 ⌘O） |
| 同文件夹上一张 / 下一张 | ← / →，按文件名自然排序，如 2 在 10 之前 |
| 跳到指定图片 | 单击左侧列表中的缩略图。当前图片会高亮，翻页时列表会自动滚到对应位置 |
| 文件操作 | 右键点主图或左侧缩略图。操作作用于点到的文件，右键其他缩略图时会保留当前预览 |
| 缩放 | 滚动鼠标滚轮，以指针所在位置为中心，也可用 + / − |
| 平移 | 图片超出画布时，按住鼠标左键拖动 |
| 原始尺寸 / 适应窗口 | 按 1 / 0，或双击画布切换 |
| 显示 / 隐藏照片信息 | Tab，可查看尺寸、大小和文件中记录的相机、镜头、光圈、快门与 ISO |
| 全屏 | F11 切换，Esc 退出 |
| 暂停 / 播放动图 | 空格 |
| 打开设置 | 点击右上角的“设置”，或按 Ctrl+,（macOS 为 ⌘,） |

Windows 会弹出资源管理器的经典文件菜单，对应 Windows 11 的“显示更多选项”。菜单包含适用于这张图片的系统命令和已安装的右键扩展。“重命名”会在资源管理器中进入文件名编辑状态。macOS 和 Linux 的右键菜单可以在 Finder 或文件管理器中定位图片。若 Linux 文件管理器不支持选中文件，HiFine 会打开所在文件夹。

通过右键菜单操作文件后，重命名或删除会同步反映在缩略图列表中。如果文件夹里只有一张图片，编辑器先删除它再以原名保存时，HiFine 会恢复主图和缩略图。

看图时，HiFine 会在后台预读前后各一张图片，优先读取翻页方向的下一张。回看时会复用已解码的图片和照片信息，文件有改动则重新读取。在“设置”的“图片缓存”中，可以调整最多缓存多少张图片，以及这些图片的像素数据合计可用多少内存，默认分别为 8 张和 256 MiB。保存后立即生效，下次启动会沿用。单张图片超出内存上限时，仍可正常打开。

支持 JPEG、PNG、GIF、WebP、BMP、TIFF、ICO、AVIF，以及 HIF / HEIF / HEIC。GIF 和动画 WebP 自动播放。多图 HEIF 显示文件指定的主图，多页 TIFF 显示首页。高位深 HIF 以 8 位桌面预览显示。所有查看操作均在本地进行。

## 从源码运行

使用 Python 3.12，在仓库根目录运行以下命令。

```sh
python -m venv .venv
```

在 Windows PowerShell 执行 `.\.venv\Scripts\Activate.ps1`，在 macOS 或 Linux 执行 `source .venv/bin/activate`，然后安装依赖并启动查看器。

```sh
python -m pip install -e ".[build,test]"
python -m hifine
python -m pytest -q
```

也可运行 `python -m hifine "照片路径"` 直接打开指定文件。无文件参数时会打开随包提供的 HIF 样片。

样片《大棱镜泉》由美国国家公园管理局摄影师 Jim Peaco 于 2001 年 7 月在黄石国家公园拍摄。原作在美国属于公有领域，HiFine 将其转为 HEIF 供试用。[原图与版权说明](https://commons.wikimedia.org/wiki/File:Grand_prismatic_spring.jpg)

## 构建安装包

在目标系统上运行 `python -m PyInstaller --noconfirm packaging/HiFine.spec`，再运行该平台的打包命令。安装包写入 `release` 目录。

| 平台 | 打包命令 | 所需工具 |
| --- | --- | --- |
| Windows x64 | `python packaging/windows/build_installer.py` | Visual Studio C++ x64、Windows SDK、CMake 3.21+、NSIS 3 |
| Ubuntu 24.04 | `sh packaging/linux/build-deb.sh` | dpkg-deb |
| macOS | `sh packaging/macos/build-dmg.sh` | Xcode Command Line Tools |

macOS 脚本生成与构建机架构一致的 DMG。

## 发布新版本

同步更新 `pyproject.toml` 和 `src/hifine/__init__.py` 的版本号，在 `docs/releases/v<版本>.md` 中写好变更和下载说明。将修改合并至 `main`，待 Desktop builds 的四项平台构建通过，在这一提交上创建并推送 `v<版本>` 标签。

发布工作流会在每版说明末尾自动附上 HiFine 的 Mirror 酱高速下载链接。标签会触发正式构建。工作流收齐四个安装包、生成对应的 HEIF 组件源码包和 SHA-256 清单，将附件上传到草稿 Release，并核对 GitHub 记录的每个文件摘要。全部一致后才会公开该版本，再将四个平台的安装包和更新说明同步到 Mirror 酱。[发布工作流](.github/workflows/desktop.yml)

HiFine 源码采用 MIT 许可证。随安装包分发的 Qt、Python 运行时和图像编解码组件适用各自的许可，安装包也附有许可文本及对应源码入口。[项目许可](LICENSE) · [第三方组件与源码](packaging/licenses/THIRD-PARTY.txt)

[latest-release]: https://github.com/MistEO/HiFine/releases/latest
