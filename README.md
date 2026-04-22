# IP 延迟与丢包批量监控工具

一个使用 Python + Tkinter 编写的图形化监控程序，支持批量监控 IP 延迟、丢包率，并导出 CSV 结果。

仓库地址：[github.com/cheenwe/ip_monitor_tool](https://github.com/cheenwe/ip_monitor_tool)

## 功能特性

- 左侧维护监控 IP 列表，支持新增、修改、删除。
- 支持导入/导出 IP 列表（`txt/csv`），入口在菜单 `IP管理`。
- `ip.txt` 自动持久化；文件缺失会自动创建默认内容，不报错。
- 支持设置监控间隔（默认 1 秒，范围 1~60 秒）。
- 支持设置曲线采样点数（默认 60，范围 10~600）。
- 开始/停止监控按钮位于 IP 列表上方，操作更快。
- 实时展示每个 IP 的状态、延迟、丢包率、收发次数、更新时间。
- 实时延迟曲线图支持多 IP 同屏显示。
- IP 列表和实时监控表格均支持滚动条，数量多时可滚动查看。
- 图标加载策略：优先外部图标（`icon.png` / `app_icon.png` / `icon.ico` / `app_icon.ico`），失败时回退内置图标。
- 监控结果自动写入 `csv/` 目录（目录不存在自动创建）。

## 运行环境

- Python 3.10+（建议）
- 标准库即可，无需第三方运行依赖

## 本地运行

```bash
python monitor_gui.py
```

## 数据输出

- `ip.txt`：监控 IP 列表
- `csv/monitor_YYYYMMDD_HHMMSS.csv`：每次监控生成一个 CSV

CSV 格式（宽表）：

- 第一列固定为 `ip`
- 后续列为每个采样时刻（`HH:MM:SS`）
- 单元格值为该 IP 在对应时刻的延迟（ms）

## 本地打包

推荐使用 PyInstaller。

### 安装

```bash
pip install pyinstaller
```

### Windows 打包（在 Windows 环境执行）

```bash
pyinstaller --noconfirm --onefile --windowed --name ip-monitor --icon icon.ico --add-data "icon.png;." monitor_gui.py
```

产物：`dist/ip-monitor.exe`

### Linux 打包（在 Linux 环境执行）

```bash
pyinstaller --noconfirm --onefile --windowed --name ip-monitor --icon icon.png --add-data "icon.png:." monitor_gui.py
```

产物：`dist/ip-monitor`

### macOS 打包（在 macOS 环境执行）

先安装 Pillow（用于将 `png` 图标转换为 macOS 需要的 `icns`）：

```bash
pip install pillow
```

再执行：

```bash
pyinstaller --noconfirm --onedir --windowed --name ip-monitor --icon icon.png --add-data "icon.png:." monitor_gui.py
```

产物：

- macOS: `dist/ip-monitor.app`

> 说明：本地直接跨平台打包通常不可行，建议在目标系统或 CI 上构建。

## GitHub Actions 多平台构建

已提供工作流：`.github/workflows/build-multi-platform.yml`

- 同时构建 `macOS + Windows + Linux`
- 触发方式：
  - push 到 `main`
  - 手动触发 `workflow_dispatch`
  - push `v*` 标签（如 `v1.0.0`）
- 输出结果：
  - 每个平台生成一个 zip 并上传到 Actions Artifacts
  - 打标签时自动创建 GitHub Release，并附带所有平台 zip
