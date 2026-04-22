from __future__ import annotations

import csv
import datetime as dt
import platform
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk


IP_FILE = Path("ip.txt")
CSV_DIR = Path("csv")
CSV_PREFIX = "monitor"
DEFAULT_INTERVAL_SECONDS = 1
DEFAULT_HISTORY_POINTS = 60
APP_VERSION = "1.0"
APP_DEVELOPER = "cheenwe"
APP_EMAIL = "cxhyun@126.com"
EXTERNAL_ICON_CANDIDATES = ("icon.png", "app_icon.png", "icon.ico", "app_icon.ico")


class IpMonitorApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("IP 延迟与丢包监控")
        self.root.geometry("1100x650")
        self._set_app_icon()

        self.ips: list[str] = []
        self.monitor_threads: list[threading.Thread] = []
        self.stop_event = threading.Event()
        self.data_lock = threading.Lock()

        self.stats: dict[str, dict[str, float | int | str]] = {}
        self.latency_history: dict[str, list[float]] = {}
        self.current_csv_path = None
        self.csv_time_columns: list[str] = []
        self.csv_latency_table: dict[str, dict[str, str]] = {}
        self.interval_var = tk.StringVar(value=str(DEFAULT_INTERVAL_SECONDS))
        self.current_interval_seconds = float(DEFAULT_INTERVAL_SECONDS)
        self.history_points_var = tk.StringVar(value=str(DEFAULT_HISTORY_POINTS))
        self.current_history_points = int(DEFAULT_HISTORY_POINTS)

        self._build_ui()
        self._ensure_ip_file()
        self._load_ips()
        self._refresh_ip_listbox()
        self._refresh_tree()
        self._schedule_ui_refresh()

    def _set_app_icon(self) -> None:
        if self._try_load_external_icon():
            return
        self._set_builtin_icon()

    def _try_load_external_icon(self) -> bool:
        search_dirs: list[Path] = [Path(__file__).resolve().parent, Path.cwd()]
        if getattr(sys, "frozen", False):
            search_dirs.insert(0, Path(sys.executable).resolve().parent)
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            search_dirs.insert(0, Path(meipass))

        checked: set[Path] = set()
        for directory in search_dirs:
            if directory in checked:
                continue
            checked.add(directory)
            for icon_name in EXTERNAL_ICON_CANDIDATES:
                icon_path = directory / icon_name
                if not icon_path.exists():
                    continue
                try:
                    if icon_path.suffix.lower() == ".ico":
                        self.root.iconbitmap(str(icon_path))
                        return True
                    image = tk.PhotoImage(file=str(icon_path))
                    self._icon_image = image
                    self.root.iconphoto(True, self._icon_image)
                    return True
                except Exception:
                    continue
        return False

    def _set_builtin_icon(self) -> None:
        try:
            icon_size = 32
            icon = tk.PhotoImage(width=icon_size, height=icon_size)

            # 深色背景
            icon.put("#1f2a44", to=(0, 0, icon_size, icon_size))

            # 绿色心跳线
            heartbeat_points = [
                (2, 18),
                (8, 18),
                (11, 13),
                (15, 24),
                (20, 9),
                (24, 18),
                (30, 18),
            ]
            for idx in range(len(heartbeat_points) - 1):
                x1, y1 = heartbeat_points[idx]
                x2, y2 = heartbeat_points[idx + 1]
                steps = max(abs(x2 - x1), abs(y2 - y1), 1)
                for step in range(steps + 1):
                    x = int(x1 + (x2 - x1) * step / steps)
                    y = int(y1 + (y2 - y1) * step / steps)
                    icon.put("#2ecc71", (x, y))

            # 网络节点
            for x, y in [(8, 8), (24, 8), (16, 27)]:
                icon.put("#ffffff", to=(x - 2, y - 2, x + 2, y + 2))

            self._icon_image = icon
            self.root.iconphoto(True, self._icon_image)
        except Exception:
            # 图标加载失败时保持默认图标，不影响主流程。
            pass

    def _build_ui(self) -> None:
        self._build_menu()

        main_paned = ttk.Panedwindow(self.root, orient=tk.HORIZONTAL)
        main_paned.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)

        left_frame = ttk.LabelFrame(main_paned, text="监控 IP 列表", padding=8)
        right_frame = ttk.LabelFrame(main_paned, text="实时监控信息", padding=8)
        main_paned.add(left_frame, weight=1)
        main_paned.add(right_frame, weight=3)

        left_paned = ttk.Panedwindow(left_frame, orient=tk.VERTICAL)
        left_paned.pack(fill=tk.BOTH, expand=True)

        ip_list_frame = ttk.Frame(left_paned, padding=(2, 2, 2, 2))
        controls_frame = ttk.Frame(left_paned, padding=(2, 2, 2, 2))
        left_paned.add(ip_list_frame, weight=4)
        left_paned.add(controls_frame, weight=1)

        top_control_frame = ttk.Frame(ip_list_frame)
        top_control_frame.pack(fill=tk.X, pady=(0, 6))

        self.start_button = ttk.Button(top_control_frame, text="开始监控", command=self.start_monitoring)
        self.start_button.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))

        self.stop_button = ttk.Button(
            top_control_frame, text="停止监控", command=self.stop_monitoring, state=tk.DISABLED
        )
        self.stop_button.pack(side=tk.LEFT, fill=tk.X, expand=True)

        ip_list_container = ttk.Frame(ip_list_frame)
        ip_list_container.pack(fill=tk.BOTH, expand=True)

        self.ip_listbox = tk.Listbox(ip_list_container, width=28)
        ip_list_scrollbar = ttk.Scrollbar(ip_list_container, orient=tk.VERTICAL, command=self.ip_listbox.yview)
        self.ip_listbox.configure(yscrollcommand=ip_list_scrollbar.set)

        self.ip_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        ip_list_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        monitor_button_frame = ttk.LabelFrame(controls_frame, text="参数配置", padding=8)
        monitor_button_frame.pack(fill=tk.X)

        interval_frame = ttk.Frame(monitor_button_frame)
        interval_frame.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(interval_frame, text="间隔时长:").pack(side=tk.LEFT)
        self.interval_spinbox = ttk.Spinbox(
            interval_frame,
            from_=1,
            to=60,
            increment=1,
            width=6,
            textvariable=self.interval_var,
            justify=tk.CENTER,
        )
        self.interval_spinbox.pack(side=tk.LEFT, padx=(6, 4))
        ttk.Label(interval_frame, text="秒").pack(side=tk.LEFT)

        history_frame = ttk.Frame(monitor_button_frame)
        history_frame.pack(fill=tk.X, pady=(0, 2))
        ttk.Label(history_frame, text="采样点数:").pack(side=tk.LEFT)
        self.history_points_spinbox = ttk.Spinbox(
            history_frame,
            from_=10,
            to=600,
            increment=10,
            width=6,
            textvariable=self.history_points_var,
            justify=tk.CENTER,
        )
        self.history_points_spinbox.pack(side=tk.LEFT, padx=(6, 4))
        ttk.Label(history_frame, text="点").pack(side=tk.LEFT)

        self.csv_path_var = tk.StringVar(value="当前 CSV：未开始")
        ttk.Label(controls_frame, textvariable=self.csv_path_var, wraplength=220).pack(
            fill=tk.X, pady=(8, 0)
        )

        right_paned = ttk.Panedwindow(right_frame, orient=tk.VERTICAL)
        right_paned.pack(fill=tk.BOTH, expand=True)

        table_frame = ttk.Frame(right_paned, padding=(2, 2, 2, 4))
        chart_frame = ttk.LabelFrame(right_paned, text="延迟实时曲线图", padding=8)
        right_paned.add(table_frame, weight=2)
        right_paned.add(chart_frame, weight=3)

        columns = ("ip", "status", "latency", "loss", "sent", "recv", "last")
        tree_container = ttk.Frame(table_frame)
        tree_container.pack(fill=tk.BOTH, expand=True)
        self.tree = ttk.Treeview(tree_container, columns=columns, show="headings")

        headings = {
            "ip": "IP",
            "status": "状态",
            "latency": "延迟(ms)",
            "loss": "丢包率(%)",
            "sent": "发送",
            "recv": "接收",
            "last": "最后更新时间",
        }
        widths = {"ip": 170, "status": 90, "latency": 100, "loss": 100, "sent": 70, "recv": 70, "last": 170}
        for col in columns:
            self.tree.heading(col, text=headings[col])
            self.tree.column(col, width=widths[col], anchor=tk.CENTER)
        tree_y_scroll = ttk.Scrollbar(tree_container, orient=tk.VERTICAL, command=self.tree.yview)
        tree_x_scroll = ttk.Scrollbar(tree_container, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=tree_y_scroll.set, xscrollcommand=tree_x_scroll.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        tree_y_scroll.grid(row=0, column=1, sticky="ns")
        tree_x_scroll.grid(row=1, column=0, sticky="ew")
        tree_container.grid_rowconfigure(0, weight=1)
        tree_container.grid_columnconfigure(0, weight=1)

        self.latency_canvas = tk.Canvas(chart_frame, bg="white")
        self.latency_canvas.pack(fill=tk.BOTH, expand=True)

        self.latency_canvas.bind("<Configure>", lambda _: self.draw_latency_chart())

    def _build_menu(self) -> None:
        menubar = tk.Menu(self.root)

        ip_menu = tk.Menu(menubar, tearoff=0)
        ip_menu.add_command(label="新增 IP", command=self.add_ip)
        ip_menu.add_command(label="修改 IP", command=self.edit_ip)
        ip_menu.add_command(label="删除 IP", command=self.delete_ip)
        ip_menu.add_separator()
        ip_menu.add_command(label="导入 IP (txt/csv)", command=self.import_ips)
        ip_menu.add_command(label="导出 IP (txt/csv)", command=self.export_ips)

        monitor_menu = tk.Menu(menubar, tearoff=0)
        monitor_menu.add_command(label="开始监控", command=self.start_monitoring)
        monitor_menu.add_command(label="停止监控", command=self.stop_monitoring)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="关于", command=self.show_about)

        menubar.add_cascade(label="IP管理", menu=ip_menu)
        menubar.add_cascade(label="监控", menu=monitor_menu)
        menubar.add_cascade(label="帮助", menu=help_menu)
        menubar.add_command(label="退出", command=self.on_close)

        self.root.config(menu=menubar)

    def show_about(self) -> None:
        messagebox.showinfo(
            "关于",
            (
                "IP 延迟与丢包监控工具\n\n"
                f"版本：{APP_VERSION}\n"
                f"开发者：{APP_DEVELOPER}\n"
                f"邮箱：{APP_EMAIL}"
            ),
        )

    def _ensure_ip_file(self) -> None:
        IP_FILE.parent.mkdir(parents=True, exist_ok=True)
        if not IP_FILE.exists():
            IP_FILE.write_text("8.8.8.8\n114.114.114.114\n1.1.1.1\n", encoding="utf-8")

    def _load_ips(self) -> None:
        self._ensure_ip_file()
        try:
            lines = IP_FILE.read_text(encoding="utf-8").splitlines()
            self.ips = [line.strip() for line in lines if line.strip()]
        except Exception:
            # 读取失败时回退到默认文件，避免程序启动中断。
            IP_FILE.write_text("8.8.8.8\n114.114.114.114\n1.1.1.1\n", encoding="utf-8")
            self.ips = ["8.8.8.8", "114.114.114.114", "1.1.1.1"]

    def _save_ips(self) -> None:
        self._ensure_ip_file()
        content = "\n".join(self.ips)
        if content:
            content += "\n"
        IP_FILE.write_text(content, encoding="utf-8")

    def _normalize_ips(self, candidates: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for value in candidates:
            ip = value.strip()
            if self._is_valid_ipv4(ip) and ip not in seen:
                normalized.append(ip)
                seen.add(ip)
        return normalized

    def _refresh_ip_listbox(self) -> None:
        self.ip_listbox.delete(0, tk.END)
        for ip in self.ips:
            self.ip_listbox.insert(tk.END, ip)

    def _refresh_tree(self) -> None:
        existing_ids = set(self.tree.get_children())
        for ip in self.ips:
            if ip not in existing_ids:
                self.tree.insert("", tk.END, iid=ip, values=(ip, "-", "-", "-", 0, 0, "-"))
        for iid in existing_ids:
            if iid not in self.ips:
                self.tree.delete(iid)

    def _is_valid_ipv4(self, ip: str) -> bool:
        parts = ip.split(".")
        if len(parts) != 4:
            return False
        try:
            return all(0 <= int(part) <= 255 and str(int(part)) == part for part in parts)
        except ValueError:
            return False

    def add_ip(self) -> None:
        ip = simpledialog.askstring("新增 IP", "请输入 IP 地址：", parent=self.root)
        if ip is None:
            return
        ip = ip.strip()
        if not self._is_valid_ipv4(ip):
            messagebox.showerror("格式错误", "请输入有效的 IPv4 地址，例如：8.8.8.8")
            return
        if ip in self.ips:
            messagebox.showwarning("重复 IP", f"IP {ip} 已存在。")
            return
        self.ips.append(ip)
        with self.data_lock:
            self.latency_history.setdefault(ip, [])
        self._save_ips()
        self._refresh_ip_listbox()
        self._refresh_tree()

    def edit_ip(self) -> None:
        selected = self.ip_listbox.curselection()
        if not selected:
            messagebox.showinfo("提示", "请先在左侧列表中选择一个 IP。")
            return
        idx = selected[0]
        old_ip = self.ips[idx]
        new_ip = simpledialog.askstring("修改 IP", "请输入新的 IP 地址：", initialvalue=old_ip, parent=self.root)
        if new_ip is None:
            return
        new_ip = new_ip.strip()
        if not self._is_valid_ipv4(new_ip):
            messagebox.showerror("格式错误", "请输入有效的 IPv4 地址，例如：8.8.8.8")
            return
        if new_ip != old_ip and new_ip in self.ips:
            messagebox.showwarning("重复 IP", f"IP {new_ip} 已存在。")
            return
        self.ips[idx] = new_ip
        with self.data_lock:
            if old_ip in self.stats:
                self.stats[new_ip] = self.stats.pop(old_ip)
            if old_ip in self.latency_history:
                self.latency_history[new_ip] = self.latency_history.pop(old_ip)
        self._save_ips()
        self._refresh_ip_listbox()
        self._refresh_tree()

    def delete_ip(self) -> None:
        selected = self.ip_listbox.curselection()
        if not selected:
            messagebox.showinfo("提示", "请先在左侧列表中选择一个 IP。")
            return
        idx = selected[0]
        ip = self.ips[idx]
        confirmed = messagebox.askyesno("确认删除", f"确定删除 IP {ip} 吗？")
        if not confirmed:
            return
        self.ips.pop(idx)
        with self.data_lock:
            self.stats.pop(ip, None)
            self.latency_history.pop(ip, None)
        self._save_ips()
        self._refresh_ip_listbox()
        self._refresh_tree()
        self.draw_latency_chart()

    def import_ips(self) -> None:
        file_path = filedialog.askopenfilename(
            title="导入 IP 列表",
            filetypes=[
                ("Text/CSV Files", "*.txt *.csv"),
                ("Text Files", "*.txt"),
                ("CSV Files", "*.csv"),
                ("All Files", "*.*"),
            ],
        )
        if not file_path:
            return

        path = Path(file_path)
        try:
            if path.suffix.lower() == ".csv":
                imported = self._read_ips_from_csv(path)
            else:
                imported = self._read_ips_from_text(path)
        except Exception as exc:
            messagebox.showerror("导入失败", f"读取文件失败：{exc}")
            return

        valid_ips = self._normalize_ips(imported)
        if not valid_ips:
            messagebox.showwarning("导入结果", "文件中未找到有效 IPv4 地址。")
            return

        old_ips = set(self.ips)
        self.ips = valid_ips
        with self.data_lock:
            self.stats = {ip: self.stats.get(ip, {}) for ip in self.ips if ip in self.stats}
            self.latency_history = {ip: self.latency_history.get(ip, []) for ip in self.ips}
        self._save_ips()
        self._refresh_ip_listbox()
        self._refresh_tree()
        self.draw_latency_chart()

        added = len(set(self.ips) - old_ips)
        messagebox.showinfo("导入成功", f"共导入 {len(self.ips)} 个有效 IP（新增 {added} 个）。")

    def export_ips(self) -> None:
        if not self.ips:
            messagebox.showwarning("无法导出", "当前没有可导出的 IP。")
            return

        file_path = filedialog.asksaveasfilename(
            title="导出 IP 列表",
            defaultextension=".txt",
            filetypes=[
                ("Text Files", "*.txt"),
                ("CSV Files", "*.csv"),
                ("All Files", "*.*"),
            ],
        )
        if not file_path:
            return

        path = Path(file_path)
        try:
            if path.suffix.lower() == ".csv":
                with path.open("w", newline="", encoding="utf-8-sig") as f:
                    writer = csv.writer(f)
                    writer.writerow(["ip"])
                    for ip in self.ips:
                        writer.writerow([ip])
            else:
                content = "\n".join(self.ips) + "\n"
                path.write_text(content, encoding="utf-8")
        except Exception as exc:
            messagebox.showerror("导出失败", f"写入文件失败：{exc}")
            return

        messagebox.showinfo("导出成功", f"已导出 {len(self.ips)} 个 IP 到：\n{path}")

    def _read_ips_from_text(self, path: Path) -> list[str]:
        lines = path.read_text(encoding="utf-8").splitlines()
        return [line.strip() for line in lines if line.strip()]

    def _read_ips_from_csv(self, path: Path) -> list[str]:
        result: list[str] = []
        with path.open("r", newline="", encoding="utf-8-sig") as f:
            rows = list(csv.reader(f))
            if not rows:
                return result

            header = [cell.strip().lower() for cell in rows[0]]
            ip_col_index = header.index("ip") if "ip" in header else None
            data_rows = rows[1:] if ip_col_index is not None else rows

            for row in data_rows:
                if not row:
                    continue
                if ip_col_index is not None and ip_col_index < len(row):
                    value = row[ip_col_index].strip()
                    if value:
                        result.append(value)
                else:
                    for value in row:
                        value = value.strip()
                        if value:
                            result.append(value)
        return result

    def _get_interval_seconds(self, show_error: bool = True) -> float | None:
        raw_value = self.interval_var.get().strip()
        try:
            interval = float(raw_value)
        except ValueError:
            if show_error:
                messagebox.showerror("间隔时长错误", "间隔时长必须是数字，建议 1~60 秒。")
            return None

        if interval < 1 or interval > 60:
            if show_error:
                messagebox.showerror("间隔时长错误", "间隔时长范围应为 1~60 秒。")
            return None
        return interval

    def _get_history_points(self, show_error: bool = True) -> int | None:
        raw_value = self.history_points_var.get().strip()
        try:
            points = int(raw_value)
        except ValueError:
            if show_error:
                messagebox.showerror("采样点数错误", "采样点数必须是整数，建议 10~600。")
            return None

        if points < 10 or points > 600:
            if show_error:
                messagebox.showerror("采样点数错误", "采样点数范围应为 10~600。")
            return None
        return points

    def _trim_latency_histories(self) -> None:
        with self.data_lock:
            for ip in self.ips:
                history = self.latency_history.get(ip, [])
                if len(history) > self.current_history_points:
                    self.latency_history[ip] = history[-self.current_history_points :]

    def _open_csv(self) -> None:
        ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        CSV_DIR.mkdir(parents=True, exist_ok=True)
        csv_path = CSV_DIR / f"{CSV_PREFIX}_{ts}.csv"
        self.current_csv_path = csv_path
        self.csv_time_columns = []
        self.csv_latency_table = {ip: {} for ip in self.ips}
        self._rewrite_latency_csv()
        self.csv_path_var.set(f"当前 CSV：{csv_path.resolve()}")

    def _close_csv(self) -> None:
        self.csv_time_columns = []
        self.csv_latency_table = {}

    def _record_latency_to_csv(self, ip: str, timestamp: str, latency: float) -> None:
        if not self.current_csv_path:
            return
        time_label = timestamp[-8:]
        if time_label not in self.csv_time_columns:
            self.csv_time_columns.append(time_label)

        latency_value = f"{latency:.2f}" if latency >= 0 else ""
        self.csv_latency_table.setdefault(ip, {})[time_label] = latency_value
        self._rewrite_latency_csv()

    def _rewrite_latency_csv(self) -> None:
        if not self.current_csv_path:
            return
        with self.current_csv_path.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["ip", *self.csv_time_columns, ""])
            for ip in self.ips:
                time_to_latency = self.csv_latency_table.get(ip, {})
                row = [ip]
                for col in self.csv_time_columns:
                    row.append(time_to_latency.get(col, ""))
                # 模板中末尾有一个空列，这里保持一致。
                row.append("")
                writer.writerow(row)

    def start_monitoring(self) -> None:
        if not self.ips:
            messagebox.showwarning("无法开始", "请先新增至少一个 IP 地址。")
            return
        interval = self._get_interval_seconds(show_error=True)
        if interval is None:
            return
        points = self._get_history_points(show_error=True)
        if points is None:
            return
        self.current_interval_seconds = interval
        self.current_history_points = points
        self.stop_event.clear()
        self._open_csv()

        with self.data_lock:
            self.latency_history = {ip: [] for ip in self.ips}
            for ip in self.ips:
                self.stats[ip] = {
                    "status": "初始化",
                    "latency": -1.0,
                    "loss": 100.0,
                    "sent": 0,
                    "recv": 0,
                    "last": "-",
                }

        self.monitor_threads = []
        for ip in self.ips:
            t = threading.Thread(target=self._monitor_ip_loop, args=(ip,), daemon=True)
            t.start()
            self.monitor_threads.append(t)

        self.start_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)

    def stop_monitoring(self) -> None:
        self.stop_event.set()
        self.start_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)
        self._close_csv()

    def _monitor_ip_loop(self, ip: str) -> None:
        while not self.stop_event.is_set():
            interval = self._get_interval_seconds(show_error=False)
            if interval is not None:
                self.current_interval_seconds = interval
            points = self._get_history_points(show_error=False)
            if points is not None:
                self.current_history_points = points

            timestamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            latency, loss, ok = ping_once(ip)

            with self.data_lock:
                if ip not in self.stats:
                    break
                stat = self.stats[ip]
                stat["sent"] = int(stat["sent"]) + 1
                if ok:
                    stat["recv"] = int(stat["recv"]) + 1
                    stat["status"] = "在线"
                else:
                    stat["status"] = "超时/丢包"
                stat["latency"] = latency
                stat["loss"] = (
                    round((int(stat["sent"]) - int(stat["recv"])) * 100 / int(stat["sent"]), 2)
                    if int(stat["sent"]) > 0
                    else loss
                )
                stat["last"] = timestamp
                history = self.latency_history.setdefault(ip, [])
                history.append(latency if latency >= 0 else -1.0)
                if len(history) > self.current_history_points:
                    history.pop(0)

                self._record_latency_to_csv(ip=ip, timestamp=timestamp, latency=latency)

            sleep_steps = max(1, int(self.current_interval_seconds * 10))
            for _ in range(sleep_steps):
                if self.stop_event.is_set():
                    break
                time.sleep(0.1)

    def _schedule_ui_refresh(self) -> None:
        points = self._get_history_points(show_error=False)
        if points is not None:
            self.current_history_points = points
            self._trim_latency_histories()
        self._update_tree_rows()
        self.draw_latency_chart()
        self.root.after(1000, self._schedule_ui_refresh)

    def _update_tree_rows(self) -> None:
        with self.data_lock:
            for ip in self.ips:
                stat = self.stats.get(ip)
                if not stat:
                    continue
                latency_display = f"{stat['latency']:.2f}" if float(stat["latency"]) >= 0 else "-"
                self.tree.item(
                    ip,
                    values=(
                        ip,
                        stat["status"],
                        latency_display,
                        stat["loss"],
                        stat["sent"],
                        stat["recv"],
                        stat["last"],
                    ),
                )

    def draw_latency_chart(self) -> None:
        self.latency_canvas.delete("all")
        w = self.latency_canvas.winfo_width()
        h = self.latency_canvas.winfo_height()
        if w < 50 or h < 50:
            return

        padding_left = 56
        padding_right = 24
        padding_top = 20
        padding_bottom = 42

        chart_left = padding_left
        chart_right = w - padding_right
        chart_top = padding_top
        chart_bottom = h - padding_bottom
        chart_w = max(1, chart_right - chart_left)
        chart_h = max(1, chart_bottom - chart_top)

        if not self.ips:
            self.latency_canvas.create_text(w / 2, h / 2, text="暂无 IP", fill="#999")
            return

        with self.data_lock:
            history_map = {ip: list(self.latency_history.get(ip, [])) for ip in self.ips}

        all_valid_values = [
            val
            for history in history_map.values()
            for val in history
            if isinstance(val, (int, float)) and float(val) >= 0
        ]

        y_max = max(all_valid_values) if all_valid_values else 50.0
        y_max = max(20.0, y_max * 1.25)

        self.latency_canvas.create_rectangle(
            chart_left, chart_top, chart_right, chart_bottom, outline="#c7d0d9", width=1
        )

        grid_count = 5
        for i in range(grid_count + 1):
            y = chart_top + chart_h * i / grid_count
            value = y_max * (1 - i / grid_count)
            self.latency_canvas.create_line(chart_left, y, chart_right, y, fill="#eef2f6")
            self.latency_canvas.create_text(chart_left - 8, y, text=f"{value:.0f}", fill="#6c7a89", anchor=tk.E)

        self.latency_canvas.create_text(chart_left - 8, chart_top - 6, text="ms", fill="#6c7a89", anchor=tk.SE)
        self.latency_canvas.create_text(
            chart_right,
            chart_bottom + 22,
            text=f"最近 {self.current_history_points} 次采样",
            fill="#6c7a89",
            anchor=tk.E,
        )

        palette = ["#1f77b4", "#d62728", "#2ca02c", "#9467bd", "#ff7f0e", "#17becf", "#8c564b"]

        legend_x = chart_left + 6
        legend_y = chart_top + 6
        for idx, ip in enumerate(self.ips):
            color = palette[idx % len(palette)]
            history = history_map.get(ip, [])
            valid_points = [v for v in history if v >= 0]
            latest = valid_points[-1] if valid_points else None

            points: list[float] = []
            for point_idx, latency in enumerate(history):
                if latency < 0:
                    if len(points) >= 4:
                        self.latency_canvas.create_line(*points, fill=color, width=2, smooth=True)
                    points = []
                    continue
                x = chart_left + chart_w * (point_idx / max(1, self.current_history_points - 1))
                y = chart_bottom - (latency / y_max) * chart_h
                points.extend([x, y])

            if len(points) >= 4:
                self.latency_canvas.create_line(*points, fill=color, width=2, smooth=True)
                self.latency_canvas.create_oval(
                    points[-2] - 2.5, points[-1] - 2.5, points[-2] + 2.5, points[-1] + 2.5, fill=color, outline=""
                )

            legend_text = f"{ip} ({latest:.1f}ms)" if latest is not None else f"{ip} (超时)"
            self.latency_canvas.create_line(legend_x, legend_y + 6, legend_x + 14, legend_y + 6, fill=color, width=3)
            self.latency_canvas.create_text(legend_x + 18, legend_y + 6, text=legend_text, anchor=tk.W, fill="#2d3436")
            legend_y += 18

    def on_close(self) -> None:
        self.stop_monitoring()
        self.root.destroy()


def ping_once(ip: str) -> tuple[float, float, bool]:
    system_name = platform.system().lower()
    run_kwargs: dict[str, object] = {}
    if system_name == "windows":
        cmd = ["ping", "-n", "1", "-w", "1000", ip]
        # Windows 下打包为 GUI 程序后，隐藏 ping 子进程弹出的控制台窗口。
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        run_kwargs["startupinfo"] = startupinfo
        run_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    elif system_name == "darwin":
        cmd = ["ping", "-c", "1", "-W", "1000", ip]
    else:
        cmd = ["ping", "-c", "1", "-W", "1", ip]

    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
            **run_kwargs,
        )
        output = (completed.stdout or "") + "\n" + (completed.stderr or "")
    except Exception:
        return -1.0, 100.0, False

    latency = _parse_latency_ms(output)
    loss = _parse_loss_percent(output)
    # 在部分系统（尤其是 Windows 中文环境）中，延迟字段格式可能不同，
    # 即使成功返回也可能暂时解析不到 latency，因此以 returncode 为准判断连通性。
    ok = completed.returncode == 0
    return latency, loss, ok


def _parse_latency_ms(output: str) -> float:
    # 兼容英文/中文 ping 输出：time=12ms、time<1ms、时间=12ms、时间<1ms
    match = re.search(r"(?:time|时间)\s*[=<]\s*(\d+(?:\.\d+)?)\s*ms", output, re.IGNORECASE)
    if match:
        return float(match.group(1))
    if re.search(r"(?:time|时间)\s*<\s*1ms", output, re.IGNORECASE):
        return 0.5
    return -1.0


def _parse_loss_percent(output: str) -> float:
    unix_match = re.search(r"(\d+(?:\.\d+)?)%\s*packet loss", output, re.IGNORECASE)
    if unix_match:
        return float(unix_match.group(1))

    win_match = re.search(r"\((\d+)%\s*loss\)", output, re.IGNORECASE)
    if win_match:
        return float(win_match.group(1))

    # 兼容 Windows 中文输出：例如“(0% 丢失)”
    win_cn_match = re.search(r"\((\d+(?:\.\d+)?)%\s*丢失\)", output, re.IGNORECASE)
    if win_cn_match:
        return float(win_cn_match.group(1))

    return 100.0


def main() -> None:
    root = tk.Tk()
    app = IpMonitorApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
