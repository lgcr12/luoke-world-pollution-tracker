import collections
import difflib
import json
import re
import subprocess
import threading
import time
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

import cv2
import numpy as np

import tracker


class ModernTrackerUI:
    UNKNOWN_PET_NAMES = {"未知精灵", "unknown", "Unknown", ""}
    NAME_BLACKLIST = {
        "单次扫描",
        "开始截图监听",
        "开始实时识别",
        "截图监听",
        "实时识别",
        "设置",
        "打开报表",
        "重置",
        "停止",
        "日志输出",
        "精灵计数池",
        "名称",
        "计数",
        "污染",
        "实时状态",
    }

    def __init__(self):
        tracker.init_files()
        self.cfg = tracker.merge_defaults(
            tracker.load_json(tracker.CONFIG_PATH, tracker.default_config()),
            tracker.default_config(),
        )
        self.state = tracker.load_json(
            tracker.STATE_PATH,
            {"total_pollution": 0, "processed_hashes": {}, "records": [], "pet_pool": {}},
        )
        self.state.setdefault("pet_pool", {})

        self.engine = None
        self.name_engine = None
        self.species_names = []
        self.species_alias = {}
        self.species_templates = []
        self.running = False
        self.mode = "idle"  # idle | screenshot | realtime
        self.stop_event = threading.Event()
        self.worker = None

        self._load_species_db()
        self._load_species_templates()

        self.root = tk.Tk()
        self.root.title("洛克污染统计器")
        self.root.geometry("1024x600+36+88")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.95)
        self.root.resizable(False, False)

        self.palette = {
            "bg": "#6A9FDB",
            "bg2": "#8DC4F8",
            "card": "#6C9FD0",
            "card2": "#7FAFDE",
            "card3": "#A7C7E8",
            "text": "#F8FBFF",
            "muted": "#D3E6FA",
            "accent": "#9EE6FF",
            "ok": "#7ECAFF",
            "danger": "#AF9AF4",
            "warn": "#E4CA68",
            "ink": "#314765",
            "glass": "#6D9DCD",
            "glass2": "#7BAEE0",
            "line": "#CFE7FF",
            "panel": "#304762",
            "shadow": "#587EA8",
        }

        self._init_style()
        self._build_ui()
        self._refresh_stats()

    def _init_style(self):
        self.root.configure(bg=self.palette["bg"])
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TFrame", background=self.palette["bg"])
        style.configure("TLabel", background=self.palette["bg"], foreground=self.palette["text"])
        style.configure("Card.TFrame", background=self.palette["card"])
        style.configure("CardTitle.TLabel", background=self.palette["card"], foreground="#E7F4FF", font=("Microsoft YaHei", 10))
        style.configure("CardValue.TLabel", background=self.palette["card"], foreground=self.palette["text"], font=("Segoe UI", 18, "bold"))
        style.configure("TEntry", fieldbackground=self.palette["panel"], foreground=self.palette["text"], insertcolor=self.palette["text"])
        style.configure(
            "Treeview",
            background=self.palette["panel"],
            foreground=self.palette["text"],
            fieldbackground=self.palette["panel"],
            rowheight=28,
            borderwidth=0,
        )
        style.configure("Treeview.Heading", background="#6D89B0", foreground="#F6FBFF")
        style.map("Treeview", background=[("selected", "#89BAEC")], foreground=[("selected", "#102746")])
        style.configure(
            "Vertical.TScrollbar",
            background="#A7C7E8",
            troughcolor="#5A7FA9",
            bordercolor="#5A7FA9",
            arrowcolor="#F2FAFF",
            lightcolor="#A7C7E8",
            darkcolor="#A7C7E8",
        )

    def _build_ui(self):
        self.total_var = tk.StringVar(value="0")
        self.species_var = tk.StringVar(value="0")
        self.latest_pet_var = tk.StringVar(value="-")
        self.records_var = tk.StringVar(value="0")
        self.status_text = tk.StringVar(value="待机")
        self.last_log_var = tk.StringVar(value="待机")
        self.topmost_var = tk.BooleanVar(value=True)
        self._log_lines = []
        self._drag_start = None

        shell = tk.Frame(
            self.root,
            bg=self.palette["bg"],
            bd=1,
            highlightthickness=1,
            highlightbackground=self.palette["line"],
            highlightcolor=self.palette["line"],
        )
        shell.pack(fill="both", expand=True)
        self.bg_canvas = tk.Canvas(shell, bg=self.palette["bg"], highlightthickness=0, bd=0)
        self.bg_canvas.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.root.after(80, self._draw_background)

        header = tk.Frame(shell, bg=self.palette["glass2"], height=52)
        header.pack(fill="x", padx=10, pady=(10, 8))
        header.pack_propagate(False)
        tk.Label(
            header,
            text="洛克污染统计器",
            bg=self.palette["glass2"],
            fg=self.palette["text"],
            font=("Microsoft YaHei", 20, "bold"),
        ).pack(side="left", padx=14)
        self.clock_date = tk.StringVar(value="")
        self.clock_time = tk.StringVar(value="")
        clock_box = tk.Frame(header, bg=self.palette["glass2"])
        clock_box.pack(side="right", padx=(0, 18))
        tk.Label(
            clock_box,
            textvariable=self.clock_time,
            bg=self.palette["glass2"],
            fg="#F8FDFF",
            font=("Segoe UI Light", 28),
        ).pack(anchor="e")
        tk.Label(
            clock_box,
            textvariable=self.clock_date,
            bg=self.palette["glass2"],
            fg="#D9EDFF",
            font=("Segoe UI", 10),
        ).pack(anchor="e")
        tk.Label(
            header,
            textvariable=self.status_text,
            bg=self.palette["glass2"],
            fg="#EEF7FF",
            font=("Microsoft YaHei", 10),
        ).pack(side="right", padx=(0, 8))
        self.status_light = tk.Canvas(header, width=16, height=16, bg=self.palette["glass2"], highlightthickness=0, bd=0)
        self.status_light.pack(side="right", padx=(0, 10))
        self.ball_status_dot = self.status_light.create_oval(3, 3, 13, 13, fill="#6B7280", outline="")
        close_btn = tk.Button(
            header,
            text="×",
            command=self.on_close,
            bg=self.palette["glass2"],
            fg=self.palette["text"],
            relief="flat",
            activebackground=self.palette["card2"],
            activeforeground=self.palette["text"],
            font=("Segoe UI", 17),
            width=2,
        )
        close_btn.pack(side="right", padx=8)

        for widget in (shell, header):
            widget.bind("<ButtonPress-1>", self._ball_press)
            widget.bind("<B1-Motion>", self._ball_drag)

        top = tk.Frame(shell, bg=self.palette["bg"])
        top.pack(fill="x", padx=14, pady=(0, 10))

        orb_card = tk.Frame(top, bg=self.palette["glass"], width=235, height=226, highlightthickness=1, highlightbackground=self.palette["line"])
        orb_card.pack(side="left", fill="y")
        orb_card.pack_propagate(False)
        self.ball_canvas = tk.Canvas(orb_card, width=214, height=180, bg=self.palette["glass"], highlightthickness=0, bd=0)
        self.ball_canvas.pack(pady=(10, 0))
        self._draw_orb()
        tk.Label(orb_card, text="累计统计", bg=self.palette["glass"], fg="#F2FAFF", font=("Microsoft YaHei", 11)).pack(pady=(2, 0))

        right = tk.Frame(top, bg=self.palette["glass"], highlightthickness=1, highlightbackground=self.palette["line"])
        right.pack(side="left", fill="both", expand=True, padx=(12, 0))

        stats = tk.Frame(right, bg=self.palette["glass"])
        stats.pack(fill="x", pady=(12, 14), padx=10)
        self._mini_stat(stats, "总污染", self.total_var, 0).pack(side="left", fill="x", expand=True)
        self._mini_stat(stats, "种类", self.species_var, 1).pack(side="left", fill="x", expand=True)
        self._mini_stat(stats, "最新", self.latest_pet_var, 2, accent=True).pack(side="left", fill="x", expand=True)

        actions1 = tk.Frame(right, bg=self.palette["glass"])
        actions1.pack(fill="x", pady=(0, 8), padx=10)
        self._btn(actions1, "开始", self.start_realtime, "#6FB3F2", fg="#EFFAFF", edge="#BFE8FF").pack(side="left")
        self._btn(actions1, "停止", self.stop_watch, "#9B87F3", fg="#FAF7FF", edge="#D9CCFF").pack(side="left", padx=8)
        self._btn(actions1, "模板截图", self.capture_species_template, "#B8C5D6", fg="#18314D", edge="#EEF7FF").pack(side="left")
        self._btn(actions1, "目录", self.open_species_template_dir, "#D1D8E2", fg="#18314D", edge="#FAFCFF").pack(side="left", padx=8)

        actions2 = tk.Frame(right, bg=self.palette["glass"])
        actions2.pack(fill="x", padx=10)
        self._btn(actions2, "重置", self.reset_stats, "#E5CC73", fg="#45320B", edge="#FFF3B4").pack(side="left")
        self._btn(actions2, "报表", self.open_report, "#BFCBDD", fg="#18314D", edge="#F1F8FF").pack(side="left", padx=8)
        tk.Checkbutton(
            actions2,
            text="置顶",
            variable=self.topmost_var,
            command=self.toggle_topmost,
            bg=self.palette["glass"],
            fg=self.palette["text"],
            activebackground=self.palette["glass"],
            activeforeground=self.palette["text"],
            selectcolor="#7294BD",
        ).pack(side="right", padx=6)

        bottom = tk.Frame(shell, bg=self.palette["bg"])
        bottom.pack(fill="both", expand=True, padx=14, pady=(0, 14))

        left_bottom = tk.Frame(bottom, bg=self.palette["glass"], highlightthickness=1, highlightbackground=self.palette["line"])
        left_bottom.pack(side="left", fill="both", expand=True)
        tk.Label(left_bottom, text="日志输出", bg=self.palette["glass"], fg="#F3FAFF", font=("Microsoft YaHei", 11, "bold")).pack(anchor="w", padx=12, pady=(10, 6))
        log_box = tk.Frame(left_bottom, bg=self.palette["panel"], highlightthickness=1, highlightbackground="#B6D7F5")
        log_box.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.log_text = tk.Text(
            log_box,
            bg=self.palette["panel"],
            fg=self.palette["text"],
            insertbackground=self.palette["text"],
            relief="flat",
            bd=0,
            highlightthickness=0,
            font=("Consolas", 10),
            wrap="word",
            padx=10,
            pady=10,
        )
        self.log_scroll = ttk.Scrollbar(log_box, orient="vertical", command=self.log_text.yview, style="Vertical.TScrollbar")
        self.log_text.configure(yscrollcommand=self.log_scroll.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        self.log_scroll.pack(side="right", fill="y")
        self.log_text.insert("1.0", "待机")
        self.log_text.configure(state="disabled")

        right_bottom = tk.Frame(bottom, bg=self.palette["glass"], width=360, highlightthickness=1, highlightbackground=self.palette["line"])
        right_bottom.pack(side="left", fill="both", padx=(12, 0))
        right_bottom.pack_propagate(False)
        tk.Label(right_bottom, text="计数库", bg=self.palette["glass"], fg="#F3FAFF", font=("Microsoft YaHei", 11, "bold")).pack(anchor="w", padx=12, pady=(10, 6))
        tree_box = tk.Frame(right_bottom, bg=self.palette["panel"], highlightthickness=1, highlightbackground="#B6D7F5")
        tree_box.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.pool_tree = ttk.Treeview(tree_box, columns=("pet", "count", "pollution"), show="headings", height=14)
        self.pool_tree.heading("pet", text="名称")
        self.pool_tree.heading("count", text="计数")
        self.pool_tree.heading("pollution", text="污染")
        self.pool_tree.column("pet", width=170, anchor="w")
        self.pool_tree.column("count", width=72, anchor="center")
        self.pool_tree.column("pollution", width=78, anchor="center")
        self.pool_scroll = ttk.Scrollbar(tree_box, orient="vertical", command=self.pool_tree.yview, style="Vertical.TScrollbar")
        self.pool_tree.configure(yscrollcommand=self.pool_scroll.set)
        self.pool_tree.pack(side="left", fill="both", expand=True)
        self.pool_scroll.pack(side="right", fill="y")

        self.dir_var = tk.StringVar(value=self.cfg.get("watch_dir", "E:/code/screenshots"))
        self.interval_var = tk.StringVar(value=str(self.cfg.get("poll_interval_sec", 2)))
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._update_clock()

    def _build_settings_panel(self):
        return None

    def _card(self, parent, title, var):
        c = tk.Frame(parent, bg=self.palette["card"], padx=10, pady=10)
        tk.Label(c, text=title, bg=self.palette["card"], fg="#89DCEB", font=("Microsoft YaHei", 10)).pack(anchor="w")
        tk.Label(c, textvariable=var, bg=self.palette["card"], fg=self.palette["text"], font=("Segoe UI", 18, "bold")).pack(
            anchor="w", pady=(6, 0)
        )
        return c

    def _mini_stat(self, parent, title, var, idx, accent=False):
        frame = tk.Frame(parent, bg=self.palette["glass"], padx=8, pady=4)
        if idx:
            tk.Frame(frame, bg="#BDE0FF", width=1).pack(side="left", fill="y", padx=(0, 10))
        inner = tk.Frame(frame, bg=self.palette["glass"])
        inner.pack(side="left", fill="both", expand=True)
        tk.Label(inner, text=title, bg=self.palette["glass"], fg=self.palette["muted"], font=("Microsoft YaHei", 10)).pack(anchor="w")
        tk.Label(
            inner,
            textvariable=var,
            bg=self.palette["glass"],
            fg="#F7FCFF" if accent else self.palette["text"],
            font=("Microsoft YaHei", 18, "bold"),
            wraplength=150 if accent else 120,
        ).pack(anchor="w", pady=(4, 0))
        return frame

    def _draw_background(self):
        if not self.bg_canvas.winfo_exists():
            return
        c = self.bg_canvas
        c.delete("all")
        w = max(c.winfo_width(), 1024)
        h = max(c.winfo_height(), 600)
        steps = 18
        for i in range(steps):
            ratio = i / max(steps - 1, 1)
            r = int(116 + (164 - 116) * ratio)
            g = int(168 + (214 - 168) * ratio)
            b = int(221 + (247 - 221) * ratio)
            color = f"#{r:02x}{g:02x}{b:02x}"
            y1 = int(h * i / steps)
            y2 = int(h * (i + 1) / steps)
            c.create_rectangle(0, y1, w, y2, fill=color, outline="")
        c.create_oval(-120, h - 130, w * 0.55, h + 180, fill="#7CB17D", outline="", stipple="gray50")
        c.create_oval(w * 0.18, h - 115, w * 0.9, h + 160, fill="#6A9C73", outline="", stipple="gray50")
        c.create_oval(w * 0.72, 84, w * 1.04, 220, fill="#DDF4FF", outline="", stipple="gray50")
        c.create_oval(w * 0.58, 112, w * 0.9, 238, fill="#F2FBFF", outline="", stipple="gray50")
        c.create_oval(w * 0.2, 72, w * 0.44, 156, fill="#E7F7FF", outline="", stipple="gray50")
        c.lower()

    def _draw_orb(self):
        c = self.ball_canvas
        c.delete("all")
        cx, cy = 104, 92
        for spread, color in ((78, "#B7F2FF"), (72, "#93CBFF"), (66, "#6DA7F1"), (60, "#5B78E9")):
            c.create_oval(cx - spread, cy - spread, cx + spread, cy + spread, fill=color, outline="")
        c.create_oval(32, 20, 176, 164, outline="#DAF4FF", width=2)
        c.create_oval(38, 26, 170, 158, outline="#F9FFFF", width=1)
        c.create_arc(14, 54, 194, 100, start=0, extent=359, style="arc", outline="#E7D9FF", width=2)
        c.create_arc(46, 16, 196, 122, start=22, extent=142, style="arc", outline="#C5EEFF", width=2)
        c.create_arc(18, 42, 160, 164, start=192, extent=108, style="arc", outline="#C5D6FF", width=2)
        c.create_oval(54, 34, 116, 76, fill="#FFFFFF", outline="", stipple="gray25")
        c.create_oval(64, 42, 102, 64, fill="#FFFFFF", outline="", stipple="gray50")
        c.create_polygon(120, 30, 148, 46, 140, 72, 112, 58, fill="#FFFFFF", outline="", stipple="gray50")
        c.create_text(cx, 88, text="污染", fill="#F5FCFF", font=("Microsoft YaHei", 11, "bold"))
        self.ball_count_text = c.create_text(cx, 126, text="0", fill="#FFFFFF", font=("Segoe UI Light", 42, "bold"))

    def _btn(self, parent, text, cmd, bg, fg="#FFFFFF", edge="#FFFFFF"):
        outer = tk.Frame(parent, bg=self.palette["shadow"], bd=0, highlightthickness=0)
        inner = tk.Frame(outer, bg=bg, bd=0, highlightthickness=0)
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        shine = tk.Frame(inner, bg=edge, height=1)
        shine.pack(fill="x", side="top")
        top_glow = tk.Frame(inner, bg="#F8FDFF", height=2)
        top_glow.pack(fill="x", side="top", padx=8)
        lower_shadow = tk.Frame(inner, bg=self.palette["shadow"], height=3)
        lower_shadow.pack(fill="x", side="bottom", padx=6)
        btn = tk.Button(
            inner,
            text=text,
            bg=bg,
            fg=fg,
            activebackground=bg,
            activeforeground=fg,
            relief="flat",
            bd=0,
            highlightthickness=0,
            padx=18,
            pady=9,
            cursor="hand2",
            font=("Microsoft YaHei", 11, "bold"),
        )
        btn.pack(fill="both", expand=True, padx=8, pady=(3, 6))

        def press(_event=None):
            btn.pack_configure(pady=(7, 2))
            inner.pack_configure(padx=1, pady=(2, 0))
            outer.configure(bg="#4D7096")
            top_glow.configure(bg="#D8F1FF")
            lower_shadow.configure(bg=bg)

        def release(_event=None):
            btn.pack_configure(pady=(3, 6))
            inner.pack_configure(padx=1, pady=1)
            outer.configure(bg=self.palette["shadow"])
            top_glow.configure(bg="#F8FDFF")
            lower_shadow.configure(bg=self.palette["shadow"])

        def hover(_event=None):
            btn.configure(bg=self._tint(bg, 10), activebackground=self._tint(bg, 10))

        def leave(_event=None):
            release()
            btn.configure(bg=bg, activebackground=bg)

        def click(_event=None):
            press()
            outer.after(90, release)
            cmd()

        btn.configure(command=click)
        btn.bind("<ButtonPress-1>", press)
        btn.bind("<ButtonRelease-1>", release)
        btn.bind("<Enter>", hover)
        btn.bind("<Leave>", leave)
        return outer

    @staticmethod
    def _tint(color: str, amount: int) -> str:
        color = color.lstrip("#")
        r = min(255, int(color[0:2], 16) + amount)
        g = min(255, int(color[2:4], 16) + amount)
        b = min(255, int(color[4:6], 16) + amount)
        return f"#{r:02X}{g:02X}{b:02X}"

    def _update_clock(self):
        now = time.localtime()
        self.clock_time.set(time.strftime("%H:%M", now))
        self.clock_date.set(time.strftime("%d %B", now))
        if self.root.winfo_exists():
            self.root.after(1000, self._update_clock)

    def toggle_settings(self):
        return None

    def _ball_press(self, event):
        self._drag_start = (event.x_root, event.y_root, self.root.winfo_x(), self.root.winfo_y())
        self._drag_moved = False

    def _ball_drag(self, event):
        if not hasattr(self, "_drag_start"):
            return
        sx, sy, ox, oy = self._drag_start
        dx = event.x_root - sx
        dy = event.y_root - sy
        if abs(dx) > 2 or abs(dy) > 2:
            self._drag_moved = True
        nx = ox + dx
        ny = oy + dy
        self.root.geometry(f"+{nx}+{ny}")

    def _ball_release(self, _event):
        self._drag_start = None

    def toggle_topmost(self):
        self.root.attributes("-topmost", bool(self.topmost_var.get()))
        self._write_log(f"置顶 {'开启' if self.topmost_var.get() else '关闭'}", "INFO")

    def _set_status(self, text: str, color: str):
        self.status_text.set(text)
        self.status_light.itemconfig(self.ball_status_dot, fill=color)

    def _write_log(self, text: str, level="INFO"):
        ts = time.strftime("%H:%M:%S")
        line = f"[{ts}] {text}"
        self._log_lines.append(line)
        self._log_lines = self._log_lines[-500:]
        self.last_log_var.set(line)
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.insert("end", "\n".join(self._log_lines))
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _refresh_stats(self):
        self._sanitize_pet_pool()
        self.total_var.set(str(self.state.get("total_pollution", 0)))
        self.records_var.set(str(len(self.state.get("records", []))))
        pet_pool = self.state.get("pet_pool", {})
        self.species_var.set(str(len(pet_pool)))
        latest = "-"
        recs = self.state.get("records", [])
        if recs:
            latest = recs[-1].get("pet_name") or "-"
        self.latest_pet_var.set(latest)
        self.ball_canvas.itemconfig(self.ball_count_text, text=self.total_var.get())
        for item in self.pool_tree.get_children():
            self.pool_tree.delete(item)
        rows = []
        for name, info in pet_pool.items():
            if isinstance(info, dict):
                cnt = int(info.get("count", 0))
                pol = int(info.get("pollution", 0))
            else:
                cnt = int(info) if str(info).isdigit() else 0
                pol = cnt
            rows.append((name, cnt, pol))
        rows.sort(key=lambda x: (x[2], x[1]), reverse=True)
        for name, cnt, pol in rows:
            self.pool_tree.insert("", "end", values=(name, cnt, pol))

    def save_settings(self):
        try:
            interval = float(self.interval_var.get().strip())
            if interval <= 0:
                raise ValueError
        except Exception:
            messagebox.showerror("错误", "轮询秒数必须大于 0")
            return False

        watch_dir = self.dir_var.get().strip()
        if not watch_dir:
            messagebox.showerror("错误", "截图目录不能为空")
            return False

        self.cfg["watch_dir"] = watch_dir
        self.cfg["poll_interval_sec"] = interval
        tracker.save_json(tracker.CONFIG_PATH, self.cfg)
        self._load_species_db()
        self._load_species_templates()
        self._write_log(f"设置已保存：dir={watch_dir}, interval={interval}s", "INFO")
        return True

    def _get_engine(self):
        if self.engine is None:
            self.engine = tracker.require_ocr_engine(self.cfg)
        return self.engine

    def _get_name_engine(self):
        if self.name_engine is not None:
            return self.name_engine
        if tracker.RapidOCR is None:
            self.name_engine = None
            return None
        try:
            self.name_engine = tracker.RapidOCR()
        except Exception:
            self.name_engine = None
        return self.name_engine

    def _scan_batch(self):
        watch_dir = Path(self.cfg.get("watch_dir", "."))
        if not watch_dir.exists():
            self.root.after(0, lambda: self._write_log(f"截图目录不存在：{watch_dir}", "ERR"))
            return 0
        c = tracker.process_batch(self._get_engine(), self.cfg, self.state, watch_dir)
        if c:
            tracker.save_json(tracker.STATE_PATH, self.state)
        self.root.after(0, self._refresh_stats)
        return c

    def scan_once(self):
        if not self.save_settings():
            return
        try:
            c = self._scan_batch()
            self._write_log(f"单次扫描完成，处理 {c} 张", "OK" if c else "INFO")
        except Exception as exc:
            self._write_log(f"扫描失败: {exc}", "ERR")
            messagebox.showerror("扫描失败", str(exc))

    def _watch_loop(self):
        try:
            interval = float(self.cfg.get("poll_interval_sec", 2))
            while not self.stop_event.is_set():
                c = self._scan_batch()
                if c:
                    self.root.after(0, lambda x=c: self._write_log(f"截图监听处理 {x} 张", "OK"))
                time.sleep(interval)
        except Exception as exc:
            self.root.after(0, lambda: self._write_log(f"截图监听异常: {exc}", "ERR"))
            self.root.after(0, lambda: messagebox.showerror("截图监听异常", str(exc)))
        finally:
            self.running = False
            self.mode = "idle"
            self.root.after(0, lambda: self._set_status("待机", "#6B7280"))

    def _load_species_db(self):
        nm = self.cfg.get("name_mode", {}) or {}
        db_path = Path(nm.get("species_db_path", str(tracker.ROOT / "species_names.json")))
        self.species_names = []
        self.species_alias = {}
        if not db_path.exists():
            return
        try:
            data = json.loads(db_path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                self.species_names = [self._fix_text(x).strip() for x in data if str(x).strip()]
            elif isinstance(data, dict):
                names = data.get("names", [])
                aliases = data.get("aliases", {})
                self.species_names = [self._fix_text(x).strip() for x in names if str(x).strip()]
                self.species_alias = {
                    self._fix_text(k).strip(): self._fix_text(v).strip()
                    for k, v in aliases.items()
                    if str(k).strip() and str(v).strip()
                }
        except Exception:
            self.species_names = []
            self.species_alias = {}

    @staticmethod
    def _fix_text(s: str) -> str:
        s = str(s)
        if any("\u4e00" <= ch <= "\u9fff" for ch in s):
            return s
        try:
            fixed = s.encode("gbk", errors="ignore").decode("utf-8", errors="ignore")
            if fixed and fixed != s:
                return fixed
        except Exception:
            pass
        return s

    def _load_species_templates(self):
        self.species_templates = []
        mode_cfg = self.cfg.get("species_template_mode", {}) or {}
        template_dir = Path(mode_cfg.get("template_dir", str(tracker.SPECIES_TEMPLATE_DIR)))
        template_dir.mkdir(parents=True, exist_ok=True)
        for p in sorted(template_dir.glob("*")):
            if not p.is_file() or p.suffix.lower() not in {".png", ".jpg", ".jpeg", ".bmp", ".webp"}:
                continue
            img = tracker.read_image(p)
            if img is None or img.size == 0:
                continue
            cropped = tracker.crop_template_to_icon(img, self.cfg.get("icon_mode", {}))
            self.species_templates.append({"name": p.stem, "image": cropped, "path": str(p)})

    def _match_species_template(self, frame_bgr: np.ndarray):
        if frame_bgr is None or frame_bgr.size == 0:
            return None
        best = None
        best_score = -1.0
        base_cfg = dict(self.cfg.get("icon_mode", {}))
        base_cfg["use_template"] = True
        for item in self.species_templates:
            hit, score, ratio, reason, bbox = tracker.detect_purple_icon_in_frame_with_bbox(
                frame_bgr, base_cfg, item["image"]
            )
            if not hit:
                continue
            if score > best_score:
                best_score = score
                best = {
                    "name": item["name"],
                    "score": score,
                    "ratio": ratio,
                    "reason": reason,
                    "bbox": bbox,
                }
        return best

    def _best_species_match(self, text: str):
        if not text or (not self.species_names and not self.species_alias):
            return None, 0.0
        threshold = float((self.cfg.get("name_mode", {}) or {}).get("fuzzy_threshold", 0.62))
        for wrong, right in self.species_alias.items():
            if wrong and wrong in text:
                return right, 1.0
        best_name = None
        best_score = 0.0
        for name in self.species_names:
            if name in text:
                return name, 1.0
            score = difflib.SequenceMatcher(None, text, name).ratio()
            if score > best_score:
                best_score = score
                best_name = name
        if best_name and best_score >= threshold:
            return best_name, best_score
        return None, best_score

    def _sanitize_pet_pool(self):
        pool = self.state.get("pet_pool", {}) or {}
        valid_names = (
            set(self.species_names)
            | {v for v in self.species_alias.values() if v}
            | {item["name"] for item in self.species_templates}
        )
        cleaned = {}
        for name, info in pool.items():
            n = (name or "").strip()
            if valid_names and n not in valid_names:
                continue
            if not self._pet_name_valid(n) and n not in valid_names:
                continue
            cleaned[n] = info
        if cleaned != pool:
            self.state["pet_pool"] = cleaned

    @staticmethod
    def _extract_pet_candidates(raw_text: str):
        text = (raw_text or "").replace("\n", " ")
        text = re.sub(r"[^\u4e00-\u9fa5A-Za-z0-9路]", " ", text)
        tokens = [t.strip() for t in text.split() if t.strip()]
        out = []
        for t in tokens:
            t = t.replace("♀", "").replace("♂", "").strip()
            if not t:
                continue
            if t.endswith("级"):
                t = t[:-1].strip()
            if not t or re.fullmatch(r"\d+", t):
                continue
            if re.fullmatch(r"[\u4e00-\u9fa5路]{2,8}", t):
                out.append(t)
            elif re.fullmatch(r"[A-Za-z][A-Za-z0-9路]{1,15}", t):
                out.append(t)
        return out

    def _ocr_name_from_roi(self, roi_bgr: np.ndarray):
        engine = self._get_name_engine()
        if engine is None or roi_bgr is None or roi_bgr.size == 0:
            return "未知精灵", ""
        texts = []
        up = cv2.resize(roi_bgr, None, fx=2.2, fy=2.2, interpolation=cv2.INTER_CUBIC)
        texts.append(tracker.run_ocr_on_bgr(engine, up))
        gray = cv2.cvtColor(up, cv2.COLOR_BGR2GRAY)
        _, th = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        texts.append(tracker.run_ocr_on_bgr(engine, cv2.cvtColor(th, cv2.COLOR_GRAY2BGR)))
        ad = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 7)
        texts.append(tracker.run_ocr_on_bgr(engine, cv2.cvtColor(ad, cv2.COLOR_GRAY2BGR)))
        candidates = []
        for t in texts:
            candidates.extend(self._extract_pet_candidates(t))
        merged = " ".join([x for x in texts if x] + candidates)
        m, _ = self._best_species_match(merged)
        if m:
            return m, merged[:200]
        chinese_candidates = [
            x for x in candidates
            if re.fullmatch(r"[\u4e00-\u9fa5路]{2,8}", x) and x not in self.NAME_BLACKLIST
        ]
        if chinese_candidates:
            return collections.Counter(chinese_candidates).most_common(1)[0][0], merged[:200]
        return "未知精灵", merged[:200]

    @staticmethod
    def _crop_search_region(frame_bgr: np.ndarray, screen_cfg: dict):
        h, w = frame_bgr.shape[:2]
        region_cfg = screen_cfg.get("search_region", {}) or {}
        x_ratio = float(region_cfg.get("x_ratio", 0.0))
        y_ratio = float(region_cfg.get("y_ratio", 0.0))
        w_ratio = float(region_cfg.get("w_ratio", 0.48))
        h_ratio = float(region_cfg.get("h_ratio", 0.36))

        x1 = max(0, min(int(w * x_ratio), w - 1))
        y1 = max(0, min(int(h * y_ratio), h - 1))
        x2 = max(x1 + 1, min(int(w * (x_ratio + w_ratio)), w))
        y2 = max(y1 + 1, min(int(h * (y_ratio + h_ratio)), h))
        return frame_bgr[y1:y2, x1:x2], (x1, y1)

    def _recognize_pet_name(self, frame_bgr: np.ndarray, bbox):
        x, y, w, h = bbox
        if w <= 0 or h <= 0:
            return "未知精灵", "bad-bbox"
        ih, iw = frame_bgr.shape[:2]
        rx1 = min(max(x + w + 2, 0), iw - 1)
        rx2 = min(max(rx1 + int(w * 2.4), 0), iw)
        ry1 = min(max(y - int(h * 0.08), 0), ih - 1)
        ry2 = min(max(y + int(h * 0.58), 0), ih)
        if rx2 <= rx1 or ry2 <= ry1:
            return "未知精灵", "roi-empty"
        roi = frame_bgr[ry1:ry2, rx1:rx2]
        name, raw = self._ocr_name_from_roi(roi)
        if name == "未知精灵":
            rx2b = min(max(rx1 + int(w * 3.1), 0), iw)
            ry2b = min(max(y + int(h * 0.72), 0), ih)
            if rx2b > rx1 and ry2b > ry1:
                roi2 = frame_bgr[ry1:ry2b, rx1:rx2b]
                n2, r2 = self._ocr_name_from_roi(roi2)
                if n2 != "未知精灵":
                    return n2, r2[:120]
        return name, raw[:120]

    def _record_pet_pool(self, pet_name: str, pollution: int):
        pool = self.state.setdefault("pet_pool", {})
        item = pool.setdefault(pet_name, {"count": 0, "pollution": 0})
        item["count"] = int(item.get("count", 0)) + 1
        item["pollution"] = int(item.get("pollution", 0)) + int(pollution)

    def _pet_name_valid(self, name: str) -> bool:
        n = (name or "").strip()
        if n in {item["name"] for item in self.species_templates}:
            return True
        if n in self.UNKNOWN_PET_NAMES or n in self.NAME_BLACKLIST:
            return False
        return re.fullmatch(r"[\u4e00-\u9fa5路]{2,8}", n) is not None

    @staticmethod
    def _event_signature(frame_bgr: np.ndarray, bbox):
        x, y, w, h = bbox
        ih, iw = frame_bgr.shape[:2]
        if w <= 0 or h <= 0:
            return ""
        x1 = min(max(x - 2, 0), iw - 1)
        y1 = min(max(y - 2, 0), ih - 1)
        x2 = min(max(x + int(w * 4.2), 0), iw)
        y2 = min(max(y + int(h * 1.1), 0), ih)
        if x2 <= x1 or y2 <= y1:
            return ""
        roi = frame_bgr[y1:y2, x1:x2]
        g = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        tiny = cv2.resize(g, (24, 12), interpolation=cv2.INTER_AREA)
        m = tiny.mean()
        bits = (tiny > m).astype(np.uint8).flatten()
        return "".join("1" if b else "0" for b in bits)

    def _realtime_loop(self):
        try:
            tracker.require_screen_tools()
            screen_cfg = self.cfg.get("screen_mode", {})
            icon_cfg = dict(self.cfg.get("icon_mode", {}))
            icon_cfg["use_template"] = True
            self._load_species_templates()
            if not self.species_templates:
                raise RuntimeError("未找到精灵模板。请先把每种精灵的污染头像截图放到 assets/species_templates")
            self.root.after(
                0,
                lambda n=len(self.species_templates): self._write_log(f"实时识别模式：模板库匹配，共加载 {n} 个模板", "INFO"),
            )

            interval = max(float(screen_cfg.get("capture_interval_sec", 0.35)), 0.45)
            min_gap = float(screen_cfg.get("min_trigger_gap_sec", 1.2))
            rearm_absent_sec = float(screen_cfg.get("rearm_absent_sec", 4.0))
            icon_value = int(icon_cfg.get("icon_pollution_value", 1))
            window_hint = str(screen_cfg.get("window_title_contains", "") or "")

            last_trigger_ts = 0.0
            last_info_ts = 0.0
            last_counted_pet = ""
            absent_since_ts = None

            with tracker.mss.mss() as sct:
                warned_no_window = False
                while not self.stop_event.is_set():
                    region = tracker._find_window_rect(window_hint)
                    if not region:
                        if not warned_no_window:
                            self.root.after(0, lambda: self._write_log("未找到游戏窗口，实时识别已暂停。请把游戏窗口标题匹配改正确。", "WARN"))
                            warned_no_window = True
                        time.sleep(interval)
                        continue
                    warned_no_window = False
                    monitor = region
                    frame = np.array(sct.grab(monitor))
                    frame_bgr = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
                    search_bgr, _ = self._crop_search_region(frame_bgr, screen_cfg)
                    match = self._match_species_template(search_bgr)
                    now = time.time()

                    if match and (now - last_trigger_ts >= min_gap):
                        absent_since_ts = None
                        pet_name = match["name"]
                        if pet_name != last_counted_pet:
                            last_trigger_ts = now
                            last_counted_pet = pet_name

                            self.state["total_pollution"] = int(self.state.get("total_pollution", 0)) + icon_value
                            self._record_pet_pool(pet_name, icon_value)
                            rec = {
                                "time": int(now),
                                "file": "<SCREEN>",
                                "pollution": icon_value,
                                "reason": f"screen-hit:{match['reason']}|pet:{pet_name}",
                                "icon_score": match["score"],
                                "purple_ratio": match["ratio"],
                                "ocr_text": "",
                                "pet_name": pet_name,
                            }
                            self.state.setdefault("records", []).append(rec)
                            tracker.append_report(
                                tracker.ParseResult(
                                    pollution=icon_value,
                                    reason=f"screen-hit:{match['reason']}|pet:{pet_name}",
                                    ocr_text="",
                                    matched_file="<SCREEN>",
                                    icon_score=match["score"],
                                    purple_ratio=match["ratio"],
                                )
                            )
                            tracker.save_json(tracker.STATE_PATH, self.state)
                            self.root.after(
                                0,
                                lambda p=pet_name, s=match["score"], r=match["ratio"]: self._write_log(
                                    f"实时触发 +{icon_value} | 精灵={p} | score={s:.3f} purple={r:.3f}", "OK"
                                ),
                            )
                            self.root.after(0, self._refresh_stats)
                    elif not match:
                        if absent_since_ts is None:
                            absent_since_ts = now
                        elif last_counted_pet and (now - absent_since_ts >= rearm_absent_sec):
                            last_counted_pet = ""
                    if now - last_info_ts >= 2.0:
                        self.root.after(
                            0,
                            lambda m=match: self._write_log(
                                f"实时状态 hit=True pet={m['name']} score={m['score']:.3f} purple={m['ratio']:.3f}" if m else "实时状态 hit=False",
                                "INFO",
                            ),
                        )
                        last_info_ts = now
                    time.sleep(interval)
        except Exception as exc:
            self.root.after(0, lambda: self._write_log(f"实时识别异常: {exc}", "ERR"))
            self.root.after(0, lambda: messagebox.showerror("实时识别异常", str(exc)))
        finally:
            self.running = False
            self.mode = "idle"
            self.root.after(0, lambda: self._set_status("待机", "#6B7280"))
    def _start_worker(self, mode: str, target):
        if self.running:
            self._write_log("已有模式在运行，请先停止", "WARN")
            return
        if not self.save_settings():
            return
        self.stop_event.clear()
        self.running = True
        self.mode = mode
        if mode == "screenshot":
            self._set_status("截图监听中", self.palette["accent"])
        else:
            self._set_status("实时识别中", self.palette["ok"])
        self.worker = threading.Thread(target=target, daemon=True)
        self.worker.start()
        self._write_log(f"开始{self.status_text.get()}", "INFO")

    def start_watch(self):
        self._start_worker("screenshot", self._watch_loop)

    def start_realtime(self):
        self._start_worker("realtime", self._realtime_loop)

    def stop_watch(self):
        if not self.running:
            self._write_log("当前未运行", "WARN")
            return
        self.stop_event.set()
        self.running = False
        mode_text = "截图监听" if self.mode == "screenshot" else "实时识别"
        self.mode = "idle"
        self._set_status("待机", "#6B7280")
        tracker.save_json(tracker.STATE_PATH, self.state)
        self._write_log(f"已停止{mode_text}", "INFO")

    def reset_stats(self):
        if not messagebox.askyesno("确认", "确定要重置统计吗？"):
            return
        tracker.command_reset()
        self.state = tracker.load_json(
            tracker.STATE_PATH,
            {"total_pollution": 0, "processed_hashes": {}, "records": [], "pet_pool": {}},
        )
        self.state.setdefault("pet_pool", {})
        self._refresh_stats()
        self._write_log("已重置统计", "INFO")

    def open_watch_dir(self):
        p = Path(self.dir_var.get().strip())
        p.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["explorer", str(p)])

    def open_report(self):
        subprocess.Popen(["explorer", str(tracker.REPORT_PATH)])

    def open_species_template_dir(self):
        p = Path((self.cfg.get("species_template_mode", {}) or {}).get("template_dir", str(tracker.SPECIES_TEMPLATE_DIR)))
        p.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["explorer", str(p)])

    def capture_species_template(self):
        if tracker.mss is None:
            messagebox.showerror("缺少依赖", "需要 mss 才能截取模板。请先安装 requirements.txt")
            return

        selection = {"start": None, "end": None, "cancelled": False}
        was_topmost = bool(self.topmost_var.get())
        try:
            self.root.attributes("-topmost", False)
            self.root.withdraw()
            self.root.update()
            time.sleep(0.15)

            overlay = tk.Toplevel(self.root)
            overlay.attributes("-fullscreen", True)
            overlay.attributes("-topmost", True)
            overlay.attributes("-alpha", 0.25)
            overlay.configure(bg="black")
            overlay.config(cursor="crosshair")

            canvas = tk.Canvas(overlay, bg="black", highlightthickness=0)
            canvas.pack(fill="both", expand=True)
            rect_id = None

            def on_press(event):
                nonlocal rect_id
                selection["start"] = (event.x_root, event.y_root)
                selection["end"] = (event.x_root, event.y_root)
                if rect_id is not None:
                    canvas.delete(rect_id)
                rect_id = canvas.create_rectangle(event.x, event.y, event.x, event.y, outline="#00C853", width=2)

            def on_drag(event):
                if selection["start"] is None or rect_id is None:
                    return
                selection["end"] = (event.x_root, event.y_root)
                x0, y0 = canvas.canvasx(event.x), canvas.canvasy(event.y)
                x1, y1 = selection["start"]
                root_x = overlay.winfo_rootx()
                root_y = overlay.winfo_rooty()
                canvas.coords(rect_id, x1 - root_x, y1 - root_y, x0, y0)

            def finish():
                overlay.destroy()
                self.root.deiconify()
                self.root.attributes("-topmost", was_topmost)
                self.root.lift()
                self.root.focus_force()

            def on_release(event):
                selection["end"] = (event.x_root, event.y_root)
                finish()

            def on_escape(_event=None):
                selection["cancelled"] = True
                finish()

            overlay.bind("<ButtonPress-1>", on_press)
            overlay.bind("<B1-Motion>", on_drag)
            overlay.bind("<ButtonRelease-1>", on_release)
            overlay.bind("<Escape>", on_escape)
            overlay.focus_force()
            self.root.wait_window(overlay)
        except Exception as exc:
            self.root.deiconify()
            self.root.attributes("-topmost", was_topmost)
            self._write_log(f"截取模板失败: {exc}", "ERR")
            messagebox.showerror("截取模板失败", str(exc))
            return

        if selection["cancelled"] or not selection["start"] or not selection["end"]:
            self._write_log("已取消模板截取", "INFO")
            return

        x0, y0 = selection["start"]
        x1, y1 = selection["end"]
        left = min(x0, x1)
        top = min(y0, y1)
        width = abs(x1 - x0)
        height = abs(y1 - y0)
        if width < 8 or height < 8:
            self._write_log("模板截取区域过小，已取消", "WARN")
            return

        name = simpledialog.askstring("模板命名", "输入精灵名：", parent=self.root)
        if not name:
            self._write_log("未输入精灵名，模板未保存", "WARN")
            return
        safe_name = re.sub(r'[\\\\/:*?\"<>|]+', "_", name.strip())
        if not safe_name:
            self._write_log("精灵名无效，模板未保存", "WARN")
            return

        template_dir = Path((self.cfg.get("species_template_mode", {}) or {}).get("template_dir", str(tracker.SPECIES_TEMPLATE_DIR)))
        template_dir.mkdir(parents=True, exist_ok=True)
        out_path = template_dir / f"{safe_name}.png"

        try:
            with tracker.mss.mss() as sct:
                shot = np.array(sct.grab({"left": left, "top": top, "width": width, "height": height}))
            img = cv2.cvtColor(shot, cv2.COLOR_BGRA2BGR)
            if not tracker.write_image(out_path, img):
                raise RuntimeError("图片写入失败")
            self._load_species_templates()
            self._write_log(f"模板已保存: {safe_name} -> {out_path.name}", "OK")
            self._refresh_stats()
        except Exception as exc:
            self._write_log(f"保存模板失败: {exc}", "ERR")
            messagebox.showerror("保存模板失败", str(exc))

    def on_close(self):
        self.stop_event.set()
        tracker.save_json(tracker.STATE_PATH, self.state)
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    ModernTrackerUI().run()

