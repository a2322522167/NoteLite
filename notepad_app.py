"""
智能记事本 - CustomTkinter 实现
功能：添加/删除/编辑事件、日期选择、滚动提醒、完成标注、双页面、本周总结、搜索、优先级、主题切换、快捷键、桌面通知、逾期标记
新增：附件、回收站(5天)、右下角卡片提醒(2h/3次)、DeepSeek 总结建议
"""
import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox, filedialog
from datetime import datetime, date, timedelta
import json, os, shutil, subprocess, threading
import calendar as cal_mod
import pystray
from PIL import Image, ImageDraw, ImageTk

ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")

DATA_FILE = "events_data.json"
TRASH_FILE = "trash_data.json"
ATTACH_DIR = "attachments"
PRIORITY_MAP = {"高": 3, "中": 2, "低": 1}
PRIORITY_REVERSE = {3: "高", 2: "中", 1: "低"}
TRASH_RETAIN_DAYS = 5
REMIND_INTERVAL_SECONDS = 2 * 60 * 60  # 2 小时
REMIND_MAX_TIMES = 3

# DeepSeek 配置（可通过环境变量覆盖）
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_API_URL = os.environ.get("DEEPSEEK_API_URL", "https://api.deepseek.com/v1/chat/completions")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

os.makedirs(ATTACH_DIR, exist_ok=True)


class Event:
    def __init__(self, title, start_date, deadline, completed=False,
                 complete_time=None, priority=2, attachments=None,
                 remind_start_count=0, remind_deadline_count=0,
                 remind_start_last=None, remind_deadline_last=None,
                 deleted_at=None, order=0.0):
        self.title = title
        self.start_date = start_date          # 开始时间
        self.deadline = deadline              # 截止时间
        self.completed = completed
        self.complete_time = complete_time
        self.priority = priority
        self.attachments = attachments or []  # list of file paths
        self.remind_start_count = remind_start_count
        self.remind_deadline_count = remind_deadline_count
        self.remind_start_last = remind_start_last      # ISO string
        self.remind_deadline_last = remind_deadline_last
        self.deleted_at = deleted_at  # 仅回收站使用，ISO 时间字符串
        self.order = order            # 手工排序序号（升序）

    def to_dict(self):
        return {
            "title": self.title,
            "start_date": self.start_date,
            "deadline": self.deadline,
            "completed": self.completed,
            "complete_time": self.complete_time,
            "priority": self.priority,
            "attachments": self.attachments,
            "remind_start_count": self.remind_start_count,
            "remind_deadline_count": self.remind_deadline_count,
            "remind_start_last": self.remind_start_last,
            "remind_deadline_last": self.remind_deadline_last,
            "deleted_at": self.deleted_at,
            "order": self.order,
        }

    @staticmethod
    def from_dict(d):
        # 兼容旧数据：record_date -> start_date, 旧 start_date -> deadline
        start_date = d.get("start_date")
        deadline = d.get("deadline")
        if "record_date" in d and deadline is None:
            # 旧版字段
            start_date = d.get("record_date") or start_date
            deadline = d.get("start_date") or deadline
        return Event(
            d.get("title", ""),
            start_date or date.today().strftime("%Y-%m-%d"),
            deadline or date.today().strftime("%Y-%m-%d"),
            d.get("completed", False),
            d.get("complete_time"),
            d.get("priority", 2),
            d.get("attachments", []),
            d.get("remind_start_count", 0),
            d.get("remind_deadline_count", 0),
            d.get("remind_start_last"),
            d.get("remind_deadline_last"),
            d.get("deleted_at"),
            d.get("order", 0.0),
        )


class DatePickerDialog(ctk.CTkToplevel):
    def __init__(self, parent, title="选择日期", default_date=None):
        super().__init__(parent)
        self.title(title)
        self.geometry("320x300")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self.result = None
        self.selected_day = None
        now = default_date or date.today()
        self.year, self.month = now.year, now.month

        tf = ctk.CTkFrame(self, fg_color="transparent")
        tf.pack(pady=(10, 5))
        ctk.CTkButton(tf, text="<", width=30, height=28,
                       command=self.prev_month).pack(side="left", padx=5)
        self.lbl_month = ctk.CTkLabel(tf, text=f"{self.year}年{self.month}月",
                                       font=("微软雅黑", 14, "bold"))
        self.lbl_month.pack(side="left", padx=10)
        ctk.CTkButton(tf, text=">", width=30, height=28,
                       command=self.next_month).pack(side="left", padx=5)

        self.cal_frame = ctk.CTkFrame(self)
        self.cal_frame.pack(pady=5)
        df = ctk.CTkFrame(self.cal_frame, fg_color="transparent")
        df.pack()
        for d in ["一", "二", "三", "四", "五", "六", "日"]:
            ctk.CTkLabel(df, text=d, width=38).pack(side="left")
        self.dc = ctk.CTkFrame(self.cal_frame, fg_color="transparent")
        self.dc.pack()
        self.btns = []
        self._build(now.day)

        bf = ctk.CTkFrame(self, fg_color="transparent")
        bf.pack(pady=10)
        ctk.CTkButton(bf, text="今天", command=self.today,
                       width=80).pack(side="left", padx=5)
        ctk.CTkButton(bf, text="确定", command=self.confirm,
                       width=80).pack(side="left", padx=5)
        ctk.CTkButton(bf, text="取消", command=self.destroy,
                       width=80, fg_color="#95a5a6").pack(side="left", padx=5)

    def _build(self, sd=None):
        for w in self.dc.winfo_children(): w.destroy()
        self.btns.clear()
        for week in cal_mod.monthcalendar(self.year, self.month):
            rf = ctk.CTkFrame(self.dc, fg_color="transparent")
            rf.pack()
            for day in week:
                if day == 0:
                    ctk.CTkLabel(rf, text="", width=38).pack(side="left")
                    continue
                fg = "#2ecc71" if day == sd else "#3a3a3a"
                btn = ctk.CTkButton(rf, text=str(day), width=38, height=28,
                                     fg_color=fg, hover_color="#555",
                                     command=lambda d=day: self._sel(d))
                btn.pack(side="left", padx=1, pady=1)
                self.btns.append((btn, day))
        self.lbl_month.configure(text=f"{self.year}年{self.month}月")

    def _sel(self, day):
        for btn, d in self.btns:
            btn.configure(fg_color="#2ecc71" if d == day else "#3a3a3a")
        self.selected_day = day

    def prev_month(self):
        self.month -= 1
        if self.month < 1: self.month = 12; self.year -= 1
        self._build(self.selected_day)

    def next_month(self):
        self.month += 1
        if self.month > 12: self.month = 1; self.year += 1
        self._build(self.selected_day)

    def today(self):
        t = date.today()
        self.year, self.month = t.year, t.month
        self.selected_day = t.day
        self._build(t.day)

    def confirm(self):
        self.result = date(self.year, self.month, self.selected_day or 1)
        self.grab_release()
        self.destroy()


class ReminderCard(tk.Toplevel):
    """桌面右下角弹出的提醒卡片（无边框）"""
    _stack_offset = 0  # 多张卡片堆叠

    def __init__(self, parent, title_text, body_text, on_close=None):
        super().__init__(parent)
        self.on_close = on_close
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        try:
            self.attributes("-alpha", 0.96)
        except Exception:
            pass

        w, h = 320, 130
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        # 任务栏预留 60px
        ReminderCard._stack_offset = (ReminderCard._stack_offset + 1) % 5
        offset = ReminderCard._stack_offset * (h + 10)
        x = sw - w - 20
        y = sh - h - 60 - offset
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.configure(bg="#2c3e50")

        # 内容
        outer = tk.Frame(self, bg="#2c3e50", bd=0)
        outer.pack(fill="both", expand=True, padx=2, pady=2)

        bar = tk.Frame(outer, bg="#e67e22", height=4)
        bar.pack(fill="x", side="top")

        head = tk.Frame(outer, bg="#2c3e50")
        head.pack(fill="x", padx=10, pady=(8, 2))
        tk.Label(head, text="🔔 " + title_text, bg="#2c3e50", fg="white",
                 font=("微软雅黑", 11, "bold"), anchor="w").pack(side="left", fill="x", expand=True)
        tk.Button(head, text="✕", bg="#2c3e50", fg="white", bd=0,
                  activebackground="#e74c3c", activeforeground="white",
                  font=("微软雅黑", 10), command=self._close).pack(side="right")

        tk.Label(outer, text=body_text, bg="#2c3e50", fg="#ecf0f1",
                 font=("微软雅黑", 10), justify="left", anchor="w",
                 wraplength=300).pack(fill="both", expand=True, padx=12, pady=(2, 8))

        # 自动关闭 15 秒
        self.after(15000, self._close)

    def _close(self):
        try:
            if self.on_close:
                self.on_close()
        except Exception:
            pass
        try:
            ReminderCard._stack_offset = max(0, ReminderCard._stack_offset - 1)
        except Exception:
            pass
        try:
            self.destroy()
        except Exception:
            pass


class NotepadApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("NoteLite — Plan is cheap, action is the key.")
        self.geometry("900x600")
        self.minsize(800, 500)

        # 数据
        self.events = []
        self.trash = []
        self.load_data()
        self.load_trash()
        self.scroll_text = ""
        self.scroll_running = False
        self.scroll_x = 0
        self.search_text = ""
        self.pending_attachments = []  # 添加事件前选好的附件

        # ---------- 顶部滚动提醒条（美化版） ----------
        # 外层容器 + 圆角
        self.scroll_frame = ctk.CTkFrame(self, height=44, fg_color="#34495e",
                                          corner_radius=10)
        self.scroll_frame.pack(fill="x", padx=8, pady=(8, 0))
        self.scroll_frame.pack_propagate(False)

        # 左侧固定的状态徽章
        self.scroll_badge = ctk.CTkFrame(self.scroll_frame, fg_color="#1abc9c",
                                          corner_radius=8, width=110)
        self.scroll_badge.pack(side="left", fill="y", padx=(6, 0), pady=6)
        self.scroll_badge.pack_propagate(False)
        self.scroll_badge_label = ctk.CTkLabel(self.scroll_badge,
                                                text="🔔  提醒",
                                                font=("微软雅黑", 12, "bold"),
                                                text_color="white")
        self.scroll_badge_label.pack(expand=True)

        # 右侧固定的计数徽章
        self.scroll_count = ctk.CTkLabel(self.scroll_frame, text="",
                                          font=("微软雅黑", 11, "bold"),
                                          text_color="white",
                                          fg_color="#2c3e50",
                                          corner_radius=10,
                                          width=70, height=24)
        self.scroll_count.pack(side="right", padx=(0, 10), pady=10)

        # 中部 canvas 滚动区
        self.scroll_canvas = tk.Canvas(self.scroll_frame, height=44,
                                        bg="#34495e",
                                        highlightthickness=0, bd=0)
        self.scroll_canvas.pack(side="left", fill="both", expand=True,
                                 padx=(8, 6), pady=0)
        self.scroll_text_id = None

        # 主区域
        self.main_frame = ctk.CTkFrame(self)
        self.main_frame.pack(fill="both", expand=True, padx=5, pady=5)

        # 左侧面板
        self.left_frame = ctk.CTkFrame(self.main_frame, width=300)
        self.left_frame.pack(side="left", fill="y", padx=(0, 5))
        self.left_frame.pack_propagate(False)
        self._build_left()

        # 右侧
        self.right_frame = ctk.CTkFrame(self.main_frame)
        self.right_frame.pack(side="right", fill="both", expand=True)
        self._build_search()
        self.tab_view = ctk.CTkTabview(self.right_frame)
        self.tab_view.pack(fill="both", expand=True, padx=5, pady=5)
        self.tab_unfinished = self.tab_view.add("未完成")
        self.tab_finished = self.tab_view.add("已完成")
        self._build_list(self.tab_unfinished, True)
        self._build_list(self.tab_finished, False)

        # 系统托盘
        self.tray_icon = None
        self.tray_thread = None
        self._tray_running = True

        # 快捷键
        self.bind("<Control-n>", lambda e: self.entry_title.focus())
        self.bind("<Control-f>", lambda e: self.search_entry.focus())
        self.bind("<Control-s>", lambda e: self.show_summary())
        self.bind("<Control-d>", lambda e: self._qdel())

        self.protocol("WM_DELETE_WINDOW", self._hide_to_tray)

        # 笔记本动画图标
        self._icon_frames_pil = self._build_notepad_frames()
        self._icon_frames_photo = [ImageTk.PhotoImage(im) for im in self._icon_frames_pil]
        self._icon_idx = 0
        try:
            self.iconphoto(True, self._icon_frames_photo[0])
        except Exception:
            pass
        self.after(300, self._animate_icon)

        # 启动定时任务
        self.after(1000, self.check_scroll)
        self.after(2000, self._init_tray)
        self.after(3000, self.check_reminders)         # 每分钟检查一次
        self.after(5000, self.cleanup_trash_periodic)  # 周期性清理回收站
        self.cleanup_trash()  # 启动时立即清理一次
        self.refresh()

        # 首次启动 DeepSeek Key 引导（仅当未配置且用户未选择"不再提示"）
        self.after(1500, self._maybe_prompt_deepseek_setup)

    # ---------------- DeepSeek Key 首次启动引导 ----------------
    DEEPSEEK_SKIP_FILE = ".deepseek_skip"

    def _maybe_prompt_deepseek_setup(self):
        try:
            if DEEPSEEK_API_KEY:
                return
            if os.path.exists(self.DEEPSEEK_SKIP_FILE):
                return
            DeepseekSetupDialog(self)
        except Exception as e:
            print("deepseek prompt error:", e)

    # ---------------- 动画图标 ----------------
    def _build_notepad_frames(self, size=64):
        """生成笔记本风格的动画帧（一支笔在本子上写字）"""
        frames = []
        FRAME_COUNT = 8
        for i in range(FRAME_COUNT):
            img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            # 阴影
            d.rounded_rectangle([8, 12, size - 4, size - 6],
                                 radius=5, fill=(0, 0, 0, 60))
            # 本子主体（米白色）
            d.rounded_rectangle([6, 10, size - 6, size - 8],
                                 radius=5, fill="#fdf6e3",
                                 outline="#b58900", width=2)
            # 顶部装订条（蓝色）
            d.rectangle([6, 10, size - 6, 18], fill="#1f6aa5")
            # 装订孔
            for x in (14, 26, 38, 50):
                d.ellipse([x - 2, 12, x + 2, 16], fill="white")
            # 横线（笔记纸纹路）
            line_y = [24, 32, 40, 48]
            # 已经"写出"的线条数：随帧增加
            written = (i % FRAME_COUNT) // 2 + 1  # 1..4
            for k, y in enumerate(line_y):
                if k < written:
                    # 已写：深灰实线
                    d.line([10, y, size - 10, y], fill="#586e75", width=2)
                else:
                    # 未写：浅灰短线
                    d.line([10, y, size - 18, y], fill="#d6d6c5", width=1)
            # 笔（沿对角线移动 + 上下小幅抖动）
            phase = i / FRAME_COUNT
            pen_x = int(12 + phase * (size - 30))
            pen_y_top = 4 + (i % 2) * 2          # 笔尾
            pen_y_tip = 22 + (i % 2) * 2         # 笔尖
            # 笔身（蓝色斜线）
            d.line([(pen_x, pen_y_top), (pen_x + 14, pen_y_tip)],
                   fill="#2c3e50", width=4)
            # 笔尖（金色三角）
            tip_x, tip_y = pen_x + 14, pen_y_tip
            d.polygon([(tip_x - 3, tip_y - 3),
                       (tip_x + 4, tip_y + 4),
                       (tip_x - 1, tip_y + 4)], fill="#f1c40f")
            # 笔帽（红色小段）
            d.line([(pen_x - 3, pen_y_top - 2), (pen_x + 1, pen_y_top + 2)],
                   fill="#e74c3c", width=4)
            frames.append(img)
        return frames

    def _animate_icon(self):
        try:
            self._icon_idx = (self._icon_idx + 1) % len(self._icon_frames_photo)
            self.iconphoto(True, self._icon_frames_photo[self._icon_idx])
            # 同步更新托盘图标
            if self.tray_icon is not None:
                try:
                    self.tray_icon.icon = self._icon_frames_pil[self._icon_idx]
                except Exception:
                    pass
        except Exception:
            pass
        self.after(280, self._animate_icon)

    # ---------------- 左侧 UI ----------------
    def _build_left(self):
        ctk.CTkLabel(self.left_frame, text="记事本",
                      font=("微软雅黑", 18, "bold")).pack(pady=(15, 5))

        # 事件描述 + 附件按钮
        ctk.CTkLabel(self.left_frame, text="事件描述:").pack(anchor="w", padx=10)
        title_row = ctk.CTkFrame(self.left_frame, fg_color="transparent")
        title_row.pack(fill="x", padx=10, pady=(0, 5))
        self.entry_title = ctk.CTkEntry(title_row,
                                         placeholder_text="输入事件描述...",
                                         border_width=0)
        self.entry_title.pack(side="left", fill="x", expand=True)
        self.btn_attach = ctk.CTkButton(title_row, text="+", width=32, height=28,
                                         command=self._pick_attachments,
                                         font=("微软雅黑", 18, "bold"),
                                         fg_color="#7f8c8d")
        self.btn_attach.pack(side="right", padx=(3, 0))

        # 附件状态显示
        self.attach_label = ctk.CTkLabel(self.left_frame, text="附件: 无",
                                          font=("微软雅黑", 9), text_color="gray",
                                          anchor="w")
        self.attach_label.pack(fill="x", padx=10, pady=(0, 5))

        # 开始时间（原“记录日期”）
        ctk.CTkLabel(self.left_frame, text="开始时间:").pack(anchor="w", padx=10)
        df1 = ctk.CTkFrame(self.left_frame, fg_color="transparent")
        df1.pack(fill="x", padx=10, pady=(0, 5))
        self.entry_sd = ctk.CTkEntry(df1, border_width=0)
        self.entry_sd.pack(side="left", fill="x", expand=True)
        self.entry_sd.insert(0, date.today().strftime("%Y-%m-%d"))
        ctk.CTkButton(df1, text="📅", width=32, height=28,
                       command=lambda: self._pick(self.entry_sd)).pack(side="right", padx=(3, 0))

        # 截止时间（原“开始日期”）
        ctk.CTkLabel(self.left_frame, text="截止时间:").pack(anchor="w", padx=10)
        df2 = ctk.CTkFrame(self.left_frame, fg_color="transparent")
        df2.pack(fill="x", padx=10, pady=(0, 5))
        self.entry_dl = ctk.CTkEntry(df2, border_width=0)
        self.entry_dl.pack(side="left", fill="x", expand=True)
        self.entry_dl.insert(0, date.today().strftime("%Y-%m-%d"))
        ctk.CTkButton(df2, text="📅", width=32, height=28,
                       command=lambda: self._pick(self.entry_dl)).pack(side="right", padx=(3, 0))

        ctk.CTkLabel(self.left_frame, text="优先级:").pack(anchor="w", padx=10)
        self.pv = ctk.StringVar(value="中")
        prio_frame = ctk.CTkFrame(self.left_frame, fg_color="transparent",
                                   border_width=1, border_color="#aaaaaa")
        prio_frame.pack(fill="x", padx=10, pady=(0, 5))
        self.prio_menu = ctk.CTkOptionMenu(prio_frame, values=["高", "中", "低"],
                                            variable=self.pv,
                                            fg_color="white",
                                            button_color="white",
                                            button_hover_color="#e0e0e0",
                                            text_color="black")
        self.prio_menu.pack(fill="x", padx=0, pady=0)
        self._fix_prio_colors()

        ctk.CTkButton(self.left_frame, text="添加事件",
                       command=self.add_event, height=36,
                       font=("微软雅黑", 13, "bold")).pack(fill="x", padx=10, pady=(5, 3))

        # 总结按钮 + DeepSeek 复选框
        sum_row = ctk.CTkFrame(self.left_frame, fg_color="transparent")
        sum_row.pack(fill="x", padx=10, pady=(3, 3))
        ctk.CTkButton(sum_row, text="本周总结",
                       command=self.show_summary, height=36,
                       font=("微软雅黑", 13, "bold")).pack(side="left", fill="x", expand=True)
        self.use_deepseek = ctk.BooleanVar(value=False)
        self.chk_deepseek = ctk.CTkCheckBox(sum_row, text="DeepSeek",
                                             variable=self.use_deepseek,
                                             width=20)
        self.chk_deepseek.pack(side="right", padx=(6, 0))

        # 回收站按钮
        ctk.CTkButton(self.left_frame, text="🗑 回收站",
                       command=self.open_trash, height=32,
                       fg_color="#8e44ad").pack(fill="x", padx=10, pady=(3, 3))

        tf = ctk.CTkFrame(self.left_frame, fg_color="transparent")
        tf.pack(fill="x", padx=10, pady=(3, 3))
        ctk.CTkButton(tf, text="暗色",
                       command=lambda: self._switch_theme("Dark"),
                       height=30, fg_color="#555").pack(side="left", padx=(0, 3), fill="x", expand=True)
        ctk.CTkButton(tf, text="亮色",
                       command=lambda: self._switch_theme("Light"),
                       height=30, fg_color="#f0ad4e").pack(side="left", padx=(3, 0), fill="x", expand=True)

        ctk.CTkFrame(self.left_frame, height=2,
                      fg_color="gray").pack(fill="x", padx=10, pady=(5, 5))
        self.stats = ctk.CTkLabel(self.left_frame, text="", justify="left")
        self.stats.pack(padx=10, pady=5, anchor="w")
        self.upd_stats()

    def _fix_prio_colors(self):
        try:
            menu = self.prio_menu._dropdown_menu
            if menu:
                menu.configure(fg="black", bg="white",
                               activeforeground="black", activebackground="#e0e0e0")
        except: pass

    def _switch_theme(self, mode):
        self.configure(cursor="watch")
        try:
            for child in self.winfo_children():
                try: child.configure(state="disabled")
                except: pass
            self.update_idletasks()
            ctk.set_appearance_mode(mode)
            self.update_idletasks()
        finally:
            for child in self.winfo_children():
                try: child.configure(state="normal")
                except: pass
            self.configure(cursor="")

    def _pick(self, entry):
        d = None
        try: d = datetime.strptime(entry.get().strip(), "%Y-%m-%d").date()
        except: d = date.today()
        dl = DatePickerDialog(self, "选择日期", d)
        self.wait_window(dl)
        if dl.result:
            entry.delete(0, "end")
            entry.insert(0, dl.result.strftime("%Y-%m-%d"))

    def _pick_attachments(self):
        files = filedialog.askopenfilenames(
            title="选择附件",
            filetypes=[("所有文件", "*.*"),
                       ("图片", "*.png *.jpg *.jpeg *.gif *.bmp"),
                       ("Excel", "*.xls *.xlsx"),
                       ("文档", "*.pdf *.doc *.docx *.txt")])
        if not files:
            return
        # 复制到 attachments 目录
        copied = []
        ts = datetime.now().strftime("%Y%m%d%H%M%S")
        for i, f in enumerate(files):
            base = os.path.basename(f)
            target = os.path.join(ATTACH_DIR, f"{ts}_{i}_{base}")
            try:
                shutil.copy2(f, target)
                copied.append(target)
            except Exception as e:
                messagebox.showerror("附件错误", f"复制失败 {base}: {e}")
        self.pending_attachments.extend(copied)
        self._refresh_attach_label()

    def _refresh_attach_label(self):
        if not self.pending_attachments:
            self.attach_label.configure(text="附件: 无")
        else:
            names = ", ".join(os.path.basename(p) for p in self.pending_attachments)
            if len(names) > 40: names = names[:40] + "..."
            self.attach_label.configure(text=f"附件({len(self.pending_attachments)}): {names}")

    def _build_search(self):
        sf = ctk.CTkFrame(self.right_frame, height=40, fg_color="transparent")
        sf.pack(fill="x", padx=5, pady=(5, 0))
        ctk.CTkLabel(sf, text="搜索:", font=("微软雅黑", 12)).pack(side="left", padx=(5, 2))
        self.search_entry = ctk.CTkEntry(sf, placeholder_text="搜索事件...", width=200, border_width=0)
        self.search_entry.pack(side="left", padx=(0, 10))
        self.search_entry.bind("<KeyRelease>", lambda e: self._srch())
        ctk.CTkLabel(sf, text="Ctrl+N新建 Ctrl+F搜索 Ctrl+S总结 Ctrl+D删除",
                      font=("微软雅黑", 9), text_color="gray").pack(side="right", padx=5)

    def _srch(self):
        self.search_text = self.search_entry.get().strip().lower()
        self.refresh()

    def _qdel(self):
        u = [e for e in self.events if not e.completed]
        if u: self.delete_event(u[0])

    def _build_list(self, parent, unfinished=True):
        sf = ctk.CTkScrollableFrame(parent)
        sf.pack(fill="both", expand=True, padx=5, pady=5)
        if unfinished: self.uc = sf
        else: self.fc = sf

    def refresh(self):
        self._pop(self.uc, True)
        self._pop(self.fc, False)
        self.upd_stats()

    def _filter(self, events):
        r = events
        if self.search_text: r = [e for e in r if self.search_text in e.title.lower()]
        return r

    def _pop(self, container, unfinished=True):
        for w in container.winfo_children(): w.destroy()
        flt = [e for e in self.events if e.completed != unfinished]
        flt = self._filter(flt)
        # 为缺少 order 的事件赋值（保持原优先级倒序），保证拖拽前已有稳定顺序
        if any(getattr(e, "order", 0) == 0 for e in flt):
            tmp = sorted(flt, key=lambda e: (-e.priority,))
            for i, e in enumerate(tmp):
                if e.order == 0:
                    e.order = float(i + 1)
        flt.sort(key=lambda e: e.order)
        # 记录当前列表顺序，用于拖拽后重新写回 order
        container._event_order = flt
        container._is_unfinished = unfinished
        if not flt:
            msg = "没有未完成事件！" if unfinished else "还没有已完成事件。"
            ctk.CTkLabel(container, text=msg, text_color="gray").pack(pady=30)
            return
        # card 与 event 对应表，便于拖拽时查询
        container._cards = []
        for ev in flt:
            card = self._card(container, ev)
            container._cards.append((card, ev))

    def _card(self, container, ev):
        pc = {3: "#e74c3c", 2: "#f39c12", 1: "#2ecc71"}
        bc = pc.get(ev.priority, "#4a4a4a")
        card = ctk.CTkFrame(container, corner_radius=8, border_width=2, border_color=bc)
        card.pack(fill="x", padx=5, pady=4)
        # 记录原始 border 颜色，拖拽时高亮使用
        card._orig_border = bc

        tf = ctk.CTkFrame(card, fg_color="transparent")
        tf.pack(fill="x", padx=10, pady=(8, 2))
        # 拖拽手柄 ≡（鼠标按住可上下拖动）
        handle = ctk.CTkLabel(tf, text="≡", font=("微软雅黑", 16, "bold"),
                               text_color="#888", width=20, cursor="fleur")
        handle.pack(side="left", padx=(0, 4))
        self._bind_drag(handle, card, ev, container)

        icon = "✅" if ev.completed else "📌"
        title_lbl = ctk.CTkLabel(tf, text=f"{icon} {ev.title}",
                      font=("微软雅黑", 13, "bold"), anchor="w")
        title_lbl.pack(side="left", fill="x", expand=True)
        # 标题区域也支持拖拽
        self._bind_drag(title_lbl, card, ev, container)

        tg = ctk.CTkFrame(tf, fg_color="transparent")
        tg.pack(side="right")
        ctk.CTkLabel(tg, text=PRIORITY_REVERSE.get(ev.priority, "中"),
                      font=("微软雅黑", 10), text_color=bc).pack(side="left", padx=(0, 5))

        inf = ctk.CTkFrame(card, fg_color="transparent")
        inf.pack(fill="x", padx=10, pady=(0, 2))
        di = f"开始: {ev.start_date} | 截止: {ev.deadline}"
        if ev.attachments: di += f" | 📎{len(ev.attachments)}"
        if ev.completed and ev.complete_time: di += f" | 完成: {ev.complete_time}"
        if not ev.completed and ev.deadline < date.today().strftime("%Y-%m-%d"): di += " 逾期!"
        ctk.CTkLabel(inf, text=di, font=("微软雅黑", 10),
                      text_color="gray", anchor="w").pack(side="left", fill="x", expand=True)

        bf = ctk.CTkFrame(card, fg_color="transparent")
        bf.pack(fill="x", padx=10, pady=(2, 8))
        if not ev.completed:
            ctk.CTkButton(bf, text="完成",
                           command=lambda e=ev: self.mark_done(e),
                           width=60, height=26, fg_color="#2ecc71").pack(side="left", padx=(0, 3))
        else:
            ctk.CTkButton(bf, text="撤回",
                           command=lambda e=ev: self.mark_undo(e),
                           width=60, height=26, fg_color="#f39c12").pack(side="left", padx=(0, 3))
        ctk.CTkButton(bf, text="编辑",
                       command=lambda e=ev: self.edit_event(e),
                       width=60, height=26, fg_color="#3498db").pack(side="left", padx=(0, 3))
        if ev.attachments:
            ctk.CTkButton(bf, text="附件",
                           command=lambda e=ev: self.view_attachments(e),
                           width=60, height=26, fg_color="#16a085").pack(side="left", padx=(0, 3))
        ctk.CTkButton(bf, text="删除",
                       command=lambda e=ev: self.delete_event(e),
                       width=60, height=26, fg_color="#e74c3c").pack(side="left", padx=(0, 3))
        return card

    # ---------------- 拖拽排序 ----------------
    def _bind_drag(self, widget, card, ev, container):
        def on_press(e):
            self._drag_state = {
                "ev": ev, "card": card, "container": container,
                "start_y": e.y_root, "moved": False
            }
            try: card.configure(border_color="#3498db")
            except Exception: pass
        def on_motion(e):
            ds = getattr(self, "_drag_state", None)
            if not ds: return
            if abs(e.y_root - ds["start_y"]) > 3:
                ds["moved"] = True
        def on_release(e):
            ds = getattr(self, "_drag_state", None)
            self._drag_state = None
            if not ds: return
            try: card.configure(border_color=card._orig_border)
            except Exception: pass
            if not ds["moved"]:
                return
            self._handle_drop(ds["container"], ds["ev"], e.y_root)
        widget.bind("<ButtonPress-1>", on_press)
        widget.bind("<B1-Motion>", on_motion)
        widget.bind("<ButtonRelease-1>", on_release)

    def _handle_drop(self, container, ev, y_root):
        cards = getattr(container, "_cards", None)
        if not cards: return
        # 找到鼠标位置对应的目标插入索引
        target_idx = len(cards)
        for i, (c, _) in enumerate(cards):
            try:
                cy = c.winfo_rooty()
                ch = c.winfo_height()
            except Exception:
                continue
            if y_root < cy + ch / 2:
                target_idx = i
                break
        # 当前顺序（仅本 tab 的事件）
        order_list = [e for (_, e) in cards]
        if ev not in order_list: return
        cur_idx = order_list.index(ev)
        # 调整后的目标索引
        if target_idx > cur_idx:
            target_idx -= 1
        if target_idx == cur_idx:
            return
        order_list.pop(cur_idx)
        order_list.insert(target_idx, ev)
        # 重新分配 order 值（步长 10，便于以后插入）
        for i, e in enumerate(order_list):
            e.order = float((i + 1) * 10)
        self.save()
        self.refresh()

    def view_attachments(self, ev):
        if not ev.attachments:
            messagebox.showinfo("提示", "无附件"); return
        win = ctk.CTkToplevel(self)
        win.title(f"附件 - {ev.title}")
        win.geometry("560x380")
        win.transient(self); win.grab_set(); win.focus_force()

        # 顶部标题栏
        hdr = ctk.CTkFrame(win, fg_color="#1f6aa5", corner_radius=0, height=46)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        ctk.CTkLabel(hdr, text=f"📎 附件列表  ({len(ev.attachments)})",
                      font=("微软雅黑", 14, "bold"),
                      text_color="white").pack(side="left", padx=15)
        ctk.CTkLabel(hdr, text=ev.title,
                      font=("微软雅黑", 11),
                      text_color="#d6e9f7").pack(side="right", padx=15)

        sf = ctk.CTkScrollableFrame(win, fg_color="#f5f7fa")
        sf.pack(fill="both", expand=True, padx=10, pady=10)

        # 文件类型 → 图标
        type_icon = {
            "png": "🖼", "jpg": "🖼", "jpeg": "🖼", "gif": "🖼", "bmp": "🖼", "webp": "🖼",
            "xls": "📊", "xlsx": "📊", "csv": "📊",
            "doc": "📝", "docx": "📝", "txt": "📝", "md": "📝",
            "pdf": "📕",
            "zip": "🗜", "rar": "🗜", "7z": "🗜",
            "mp3": "🎵", "wav": "🎵",
            "mp4": "🎬", "mov": "🎬", "avi": "🎬",
            "py": "🐍", "json": "🔧", "xml": "🔧",
        }

        def fmt_size(b):
            for u in ["B", "KB", "MB", "GB"]:
                if b < 1024: return f"{b:.1f} {u}"
                b /= 1024
            return f"{b:.1f} TB"

        for idx, p in enumerate(ev.attachments):
            name = os.path.basename(p)
            exists = os.path.exists(p)
            ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
            icon = type_icon.get(ext, "📄") if exists else "❌"

            # 紧凑单行卡片
            row = ctk.CTkFrame(sf, fg_color="white", corner_radius=6,
                               border_width=1, height=34,
                               border_color="#d0d7de" if exists else "#e57373")
            row.pack(fill="x", padx=2, pady=2)
            row.pack_propagate(False)

            # 左侧色条（细）
            bar_color = "#1f6aa5" if exists else "#c0392b"
            bar = ctk.CTkFrame(row, width=3, fg_color=bar_color, corner_radius=1)
            bar.pack(side="left", fill="y", padx=(4, 0), pady=4)

            # 图标
            ctk.CTkLabel(row, text=icon,
                          font=("Segoe UI Emoji", 14),
                          text_color="#1f6aa5" if exists else "#c0392b",
                          width=22).pack(side="left", padx=(4, 2))

            # 文件名 + 元信息（同一行）
            if exists:
                try:
                    sz = fmt_size(os.path.getsize(p))
                    meta = f"  ·  {sz}"
                except Exception:
                    meta = ""
            else:
                meta = "  ·  缺失"
            ctk.CTkLabel(row, text=name, anchor="w",
                          font=("微软雅黑", 11, "bold"),
                          text_color="#1a1a1a" if exists else "#7a7a7a"
                          ).pack(side="left", padx=(2, 0))
            ctk.CTkLabel(row, text=meta, anchor="w",
                          font=("微软雅黑", 9),
                          text_color="#5a6a7a" if exists else "#c0392b"
                          ).pack(side="left", padx=(0, 4))

            # 占位伸展
            ctk.CTkLabel(row, text="", fg_color="transparent"
                          ).pack(side="left", fill="x", expand=True)

            # 操作按钮（紧凑）
            if exists:
                ctk.CTkButton(row, text="打开", width=48, height=22,
                               font=("微软雅黑", 10),
                               fg_color="#1f6aa5", hover_color="#155380",
                               command=lambda fp=p: self._open_file(fp)
                               ).pack(side="left", padx=(0, 2), pady=4)
                ctk.CTkButton(row, text="目录", width=48, height=22,
                               font=("微软雅黑", 10),
                               fg_color="#16a085", hover_color="#0e6655",
                               command=lambda fp=p: self._open_in_explorer(fp)
                               ).pack(side="left", padx=(0, 4), pady=4)

        # 底部关闭按钮
        bottom = ctk.CTkFrame(win, fg_color="transparent")
        bottom.pack(fill="x", padx=10, pady=(0, 10))
        ctk.CTkButton(bottom, text="关闭", width=90, height=32,
                       fg_color="#95a5a6", hover_color="#7f8c8d",
                       command=win.destroy).pack(side="right")

    def _open_in_explorer(self, path):
        try:
            # Windows: /select 高亮文件
            os.system(f'explorer /select,"{os.path.abspath(path)}"')
        except Exception as e:
            messagebox.showerror("打开失败", str(e))

    def _open_file(self, path):
        try:
            os.startfile(path)
        except Exception as e:
            messagebox.showerror("打开失败", str(e))

    def add_event(self):
        t = self.entry_title.get().strip()
        if not t: messagebox.showwarning("提示", "请输入事件标题！"); return
        sds, dls = self.entry_sd.get().strip(), self.entry_dl.get().strip()
        try:
            if sds: datetime.strptime(sds, "%Y-%m-%d")
            else: sds = date.today().strftime("%Y-%m-%d")
            if dls: datetime.strptime(dls, "%Y-%m-%d")
            else: dls = date.today().strftime("%Y-%m-%d")
        except: messagebox.showerror("错误", "日期格式错误！"); return
        if dls < sds:
            messagebox.showwarning("提示", "截止时间不能早于开始时间！"); return
        p = PRIORITY_MAP.get(self.pv.get(), 2)
        ev = Event(t, sds, dls, priority=p, attachments=list(self.pending_attachments))
        self.events.append(ev)
        self.save(); self.refresh()
        self.entry_title.delete(0, "end")
        self.entry_sd.delete(0, "end"); self.entry_sd.insert(0, date.today().strftime("%Y-%m-%d"))
        self.entry_dl.delete(0, "end"); self.entry_dl.insert(0, date.today().strftime("%Y-%m-%d"))
        self.pending_attachments = []
        self._refresh_attach_label()
        messagebox.showinfo("成功", f"事件「{t}」已添加！")

    def edit_event(self, ev):
        EditDialog(self, ev)

    def delete_event(self, ev):
        if messagebox.askyesno("确认删除", f"确定要删除「{ev.title}」吗？\n（将放入回收站，{TRASH_RETAIN_DAYS}天后自动清除）"):
            ev.deleted_at = datetime.now().isoformat(timespec="seconds")
            self.trash.append(ev)
            self.events.remove(ev)
            self.save(); self.save_trash(); self.refresh()

    def mark_done(self, ev):
        ev.completed = True
        ev.complete_time = datetime.now().strftime("%Y-%m-%d %H:%M")
        self.save(); self.refresh()
        try:
            from plyer import notification
            notification.notify(title="完成", message=f"「{ev.title}」已完成！", timeout=3)
        except: pass

    def mark_undo(self, ev):
        ev.completed = False; ev.complete_time = None
        self.save(); self.refresh()

    # ---------------- 滚动栏（美化版） ----------------
    def check_scroll(self):
        """事件开始（start_date <= 今天）后即在顶部滚动栏滚动提醒；
        超过截止时间的事件单独标注 [逾期]。"""
        t = date.today().strftime("%Y-%m-%d")
        started = [e for e in self.events
                   if not e.completed and e.start_date <= t]
        if started:
            # 按截止时间升序排列，紧迫的在前
            started.sort(key=lambda e: (e.deadline, e.start_date))
            parts = []
            overdue_n = today_n = ongoing_n = 0
            for e in started:
                if e.deadline < t:
                    parts.append(f"⚠ 逾期 · {e.title}（截止 {e.deadline}）")
                    overdue_n += 1
                elif e.deadline == t:
                    parts.append(f"⏰ 今日截止 · {e.title}")
                    today_n += 1
                else:
                    parts.append(f"▶ 进行中 · {e.title}（{e.start_date} → {e.deadline}）")
                    ongoing_n += 1
            # 用细分隔点连接
            self.scroll_text = "        ●        ".join(parts) + "        ●        "

            # 根据状态选配色（深色背景 + 高对比文字）
            if overdue_n > 0:
                bar_bg, badge_bg, badge_text = "#7b241c", "#e74c3c", "⚠  逾期"
            elif today_n > 0:
                bar_bg, badge_bg, badge_text = "#7e5109", "#f39c12", "⏰  今日"
            else:
                bar_bg, badge_bg, badge_text = "#1e6b5c", "#1abc9c", "▶  进行中"

            try:
                self.scroll_frame.configure(fg_color=bar_bg)
                self.scroll_canvas.configure(bg=bar_bg)
                self.scroll_badge.configure(fg_color=badge_bg)
                self.scroll_badge_label.configure(text=badge_text)
                self.scroll_count.configure(
                    text=f"共 {len(started)} 条",
                    fg_color="#000000")
            except Exception:
                pass

            if not self.scroll_running:
                self.scroll_running = True
                self._init_scroll()
            else:
                if self.scroll_text_id is not None:
                    try:
                        self.scroll_canvas.itemconfigure(self.scroll_text_id,
                                                         text=self.scroll_text)
                    except Exception:
                        pass
        else:
            self.scroll_text = ""; self.scroll_running = False
            self.scroll_canvas.delete("all")
            try:
                self.scroll_frame.configure(fg_color="#2c3e50")
                self.scroll_canvas.configure(bg="#2c3e50")
                self.scroll_badge.configure(fg_color="#27ae60")
                self.scroll_badge_label.configure(text="✓  全清")
                self.scroll_count.configure(text="无待办", fg_color="#16a085")
                # 居中提示
                self.scroll_canvas.update_idletasks()
                cw = self.scroll_canvas.winfo_width() or 600
                self.scroll_canvas.create_text(cw // 2, 22,
                    text="今天没有进行中的事件，开始享受高效的一天吧 ✨",
                    fill="#ecf0f1", font=("微软雅黑", 12, "bold"),
                    anchor="center")
            except Exception:
                pass
        self.after(30000, self.check_scroll)

    def _init_scroll(self):
        self.scroll_canvas.delete("all")
        self.scroll_canvas.update_idletasks()
        cw = self.scroll_canvas.winfo_width()
        if cw < 10: cw = 880
        # 从画布右侧之外开始，整段文字 anchor="w"（左对齐），
        # 这样左侧（最前面的事件）会先进入视野并依次滚出
        self.scroll_x = cw
        # 文字阴影 + 主文字（伪粗体描边效果）
        self.scroll_shadow_id = self.scroll_canvas.create_text(
            self.scroll_x + 1, 23, text=self.scroll_text,
            fill="#000000", font=("微软雅黑", 13, "bold"), anchor="w")
        self.scroll_text_id = self.scroll_canvas.create_text(
            self.scroll_x, 22, text=self.scroll_text,
            fill="#ffffff", font=("微软雅黑", 13, "bold"), anchor="w")
        self._anim()

    def _anim(self):
        if not self.scroll_running or not self.scroll_text:
            self.scroll_running = False; return
        # 平滑速度
        self.scroll_x -= 1
        bb = self.scroll_canvas.bbox(self.scroll_text_id)
        # 当整段文字的右边界滑过画布左侧（即整段都已离开屏幕），
        # 重新从画布右侧之外进入，循环滚动
        if bb and bb[2] < 0:
            cw = self.scroll_canvas.winfo_width()
            if cw < 10: cw = 880
            self.scroll_x = cw
        try:
            self.scroll_canvas.coords(self.scroll_text_id, self.scroll_x, 22)
            if hasattr(self, "scroll_shadow_id"):
                self.scroll_canvas.coords(self.scroll_shadow_id,
                                          self.scroll_x + 1, 23)
        except Exception:
            pass
        self.after(25, self._anim)

    # ---------------- 桌面卡片提醒 ----------------
    def check_reminders(self):
        """每分钟扫描事件，触发开始/截止提醒"""
        try:
            now = datetime.now()
            today_str = now.strftime("%Y-%m-%d")
            changed = False
            for ev in self.events:
                if ev.completed: continue
                # 开始时间提醒
                if ev.start_date <= today_str and ev.remind_start_count < REMIND_MAX_TIMES:
                    if self._should_remind(ev.remind_start_last, now):
                        self._popup_card(f"事件已到开始时间", f"{ev.title}\n开始: {ev.start_date}",
                                          ev.priority)
                        ev.remind_start_count += 1
                        ev.remind_start_last = now.isoformat(timespec="seconds")
                        changed = True
                # 截止时间提醒
                if ev.deadline <= today_str and ev.remind_deadline_count < REMIND_MAX_TIMES:
                    if self._should_remind(ev.remind_deadline_last, now):
                        self._popup_card(f"事件已到截止时间", f"{ev.title}\n截止: {ev.deadline}",
                                          ev.priority)
                        ev.remind_deadline_count += 1
                        ev.remind_deadline_last = now.isoformat(timespec="seconds")
                        changed = True
            if changed: self.save()
        except Exception as e:
            print("check_reminders error:", e)
        # 每 60 秒检查一次
        self.after(60 * 1000, self.check_reminders)

    def _should_remind(self, last_iso, now):
        if not last_iso:
            return True
        try:
            last = datetime.fromisoformat(last_iso)
            return (now - last).total_seconds() >= REMIND_INTERVAL_SECONDS
        except Exception:
            return True

    def _popup_card(self, title_text, body_text, priority=2):
        try:
            ReminderCard(self, title_text, body_text)
        except Exception as e:
            print("popup_card error:", e)

    # ---------------- 总结 ----------------
    def show_summary(self):
        t = date.today()
        m = t - timedelta(days=t.weekday())
        s = m + timedelta(days=6)
        ms, ss = m.strftime("%Y-%m-%d"), s.strftime("%Y-%m-%d")
        done, und = [], []
        for ev in self.events:
            try:
                ed = datetime.strptime(ev.start_date, "%Y-%m-%d").date()
            except Exception:
                continue
            if m <= ed <= s:
                if ev.completed: done.append(ev)
                else: und.append(ev)
        SummaryWin(self, ms, ss, done, und, use_deepseek=self.use_deepseek.get())

    def upd_stats(self):
        t = len(self.events)
        c = len([e for e in self.events if e.completed])
        u = t - c
        o = len([e for e in self.events if not e.completed and
                 e.deadline < date.today().strftime("%Y-%m-%d")])
        r = (c / t * 100) if t > 0 else 0
        self.stats.configure(text=f"统计\n总计: {t}\n已完成: {c}\n未完成: {u}\n已逾期: {o}\n完成率: {r:.1f}%")

    # ---------------- 数据持久化 ----------------
    def save(self):
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump([e.to_dict() for e in self.events], f, ensure_ascii=False, indent=2)

    def load_data(self):
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, "r", encoding="utf-8") as f:
                    self.events = [Event.from_dict(d) for d in json.load(f)]
            except: self.events = []
        else: self.events = []

    def save_trash(self):
        with open(TRASH_FILE, "w", encoding="utf-8") as f:
            json.dump([e.to_dict() for e in self.trash], f, ensure_ascii=False, indent=2)

    def load_trash(self):
        if os.path.exists(TRASH_FILE):
            try:
                with open(TRASH_FILE, "r", encoding="utf-8") as f:
                    self.trash = [Event.from_dict(d) for d in json.load(f)]
            except: self.trash = []
        else: self.trash = []

    # ---------------- 回收站 ----------------
    def cleanup_trash(self):
        """删除超过 TRASH_RETAIN_DAYS 天的事件"""
        now = datetime.now()
        keep = []
        removed = 0
        for ev in self.trash:
            try:
                dt = datetime.fromisoformat(ev.deleted_at) if ev.deleted_at else now
            except Exception:
                dt = now
            if (now - dt).total_seconds() >= TRASH_RETAIN_DAYS * 86400:
                # 真删除：附件文件也删掉
                for p in ev.attachments or []:
                    try:
                        if os.path.exists(p): os.remove(p)
                    except Exception: pass
                removed += 1
            else:
                keep.append(ev)
        if removed:
            self.trash = keep
            self.save_trash()

    def cleanup_trash_periodic(self):
        self.cleanup_trash()
        # 每 1 小时清理一次
        self.after(60 * 60 * 1000, self.cleanup_trash_periodic)

    def open_trash(self):
        TrashWindow(self)

    def restore_from_trash(self, ev):
        ev.deleted_at = None
        # 重置提醒计数，避免立即弹窗
        ev.remind_start_count = REMIND_MAX_TIMES
        ev.remind_deadline_count = REMIND_MAX_TIMES
        self.events.append(ev)
        self.trash.remove(ev)
        self.save(); self.save_trash(); self.refresh()

    def purge_from_trash(self, ev):
        for p in ev.attachments or []:
            try:
                if os.path.exists(p): os.remove(p)
            except Exception: pass
        self.trash.remove(ev)
        self.save_trash()

    # ---------------- 系统托盘 ----------------
    def _create_tray_image(self):
        # 复用笔记本风格首帧作为托盘图标
        try:
            return self._icon_frames_pil[0]
        except Exception:
            size = 32
            img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            draw.rectangle([2, 4, 29, 29], fill="#1a73e8", outline=None)
            draw.text((10, 8), "T", fill="white")
            return img

    def _init_tray(self):
        if self.tray_icon: return
        img = self._create_tray_image()
        menu = pystray.Menu(
            pystray.MenuItem("显示窗口", self._show_window, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", self._quit_app)
        )
        self.tray_icon = pystray.Icon("NoteLite", img, "NoteLite", menu)
        self.tray_thread = threading.Thread(target=self.tray_icon.run, daemon=True)
        self.tray_thread.start()

    def _hide_to_tray(self): self.withdraw()
    def _show_window(self, icon=None, item=None): self.after(0, self._restore_window)
    def _restore_window(self):
        self.deiconify(); self.lift(); self.focus_force()
    def _quit_app(self, icon=None, item=None):
        self._tray_running = False
        if self.tray_icon: self.tray_icon.stop()
        self.after(100, self.destroy)


class DeepseekSetupDialog(ctk.CTkToplevel):
    """首次启动时引导用户配置 DEEPSEEK_API_KEY 环境变量"""
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.title("配置 DeepSeek API Key")
        self.geometry("520x380")
        self.resizable(False, False)
        self.transient(parent); self.grab_set(); self.focus_force()

        # 标题栏
        hdr = ctk.CTkFrame(self, fg_color="#9b59b6", corner_radius=0, height=50)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        ctk.CTkLabel(hdr, text="🤖  启用 DeepSeek 智能总结",
                      font=("微软雅黑", 14, "bold"),
                      text_color="white").pack(side="left", padx=15)

        # 正文
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=20, pady=15)

        info = (
            "未检测到环境变量 DEEPSEEK_API_KEY。\n\n"
            "该 Key 用于启用「本周总结 + AI 可行性建议」功能。\n"
            "您可以从 DeepSeek 官方控制台免费创建：\n"
            "https://platform.deepseek.com/api_keys\n\n"
            "若不需要 AI 功能可直接跳过，应用其他功能不受影响。"
        )
        ctk.CTkLabel(body, text=info, justify="left", anchor="w",
                      font=("微软雅黑", 11), wraplength=470
                      ).pack(fill="x", pady=(0, 8))

        ctk.CTkLabel(body, text="DeepSeek API Key:",
                      font=("微软雅黑", 11, "bold"),
                      anchor="w").pack(fill="x", pady=(8, 2))
        self.entry = ctk.CTkEntry(body, placeholder_text="sk-...", show="*")
        self.entry.pack(fill="x", pady=(0, 8))

        # 按钮区
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", padx=20, pady=(0, 15))
        ctk.CTkButton(btn_row, text="🌐 打开 DeepSeek 官网",
                       fg_color="#3498db", height=32,
                       command=self._open_site
                       ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(btn_row, text="保存并启用",
                       fg_color="#27ae60", height=32,
                       command=self._save).pack(side="right", padx=(6, 0))
        ctk.CTkButton(btn_row, text="不再提示",
                       fg_color="#7f8c8d", height=32,
                       command=self._skip_forever).pack(side="right", padx=(6, 0))
        ctk.CTkButton(btn_row, text="稍后",
                       fg_color="#95a5a6", height=32,
                       command=self.destroy).pack(side="right")

    def _open_site(self):
        try:
            import webbrowser
            webbrowser.open("https://platform.deepseek.com/api_keys")
        except Exception as e:
            messagebox.showerror("错误", str(e), parent=self)

    def _save(self):
        key = self.entry.get().strip()
        if not key:
            messagebox.showwarning("提示", "请输入 API Key 或选择其他选项。", parent=self)
            return
        # 写入用户级环境变量（持久化，重启生效）
        try:
            subprocess.run(["setx", "DEEPSEEK_API_KEY", key],
                           shell=False, check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            messagebox.showerror("错误", f"setx 调用失败: {e}", parent=self)
            return
        # 当前进程立即生效
        os.environ["DEEPSEEK_API_KEY"] = key
        global DEEPSEEK_API_KEY
        DEEPSEEK_API_KEY = key
        messagebox.showinfo("成功",
            "DeepSeek API Key 已保存到用户环境变量。\n"
            "当前会话已立即启用，重启后依旧有效。", parent=self)
        self.destroy()

    def _skip_forever(self):
        try:
            with open(NotepadApp.DEEPSEEK_SKIP_FILE, "w", encoding="utf-8") as f:
                f.write("skip")
        except Exception:
            pass
        self.destroy()

class TrashWindow(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.title("🗑 回收站")
        self.geometry("680x480")
        self.transient(parent); self.grab_set(); self.focus_force()

        ctk.CTkLabel(self, text=f"回收站（{TRASH_RETAIN_DAYS} 天后自动彻底删除）",
                      font=("微软雅黑", 14, "bold")).pack(pady=(12, 6))

        self.list_frame = ctk.CTkScrollableFrame(self)
        self.list_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        bf = ctk.CTkFrame(self, fg_color="transparent")
        bf.pack(fill="x", padx=10, pady=(0, 10))
        ctk.CTkButton(bf, text="清空回收站", fg_color="#c0392b",
                       command=self.empty_all).pack(side="left")
        ctk.CTkButton(bf, text="关闭", fg_color="#95a5a6",
                       command=self.destroy).pack(side="right")

        self._render()

    def _render(self):
        for w in self.list_frame.winfo_children(): w.destroy()
        if not self.parent.trash:
            ctk.CTkLabel(self.list_frame, text="回收站为空",
                          text_color="gray").pack(pady=30)
            return
        now = datetime.now()
        for ev in list(self.parent.trash):
            try:
                dt = datetime.fromisoformat(ev.deleted_at) if ev.deleted_at else now
            except Exception:
                dt = now
            remain_sec = TRASH_RETAIN_DAYS * 86400 - (now - dt).total_seconds()
            remain_days = max(0, remain_sec / 86400)
            card = ctk.CTkFrame(self.list_frame, corner_radius=6,
                                 border_width=1, border_color="#7f8c8d")
            card.pack(fill="x", padx=4, pady=4)
            top = ctk.CTkFrame(card, fg_color="transparent")
            top.pack(fill="x", padx=10, pady=(6, 2))
            ctk.CTkLabel(top, text=f"📌 {ev.title}",
                          font=("微软雅黑", 12, "bold"),
                          anchor="w").pack(side="left", fill="x", expand=True)
            ctk.CTkLabel(top, text=f"剩余 {remain_days:.1f} 天",
                          text_color="#e67e22",
                          font=("微软雅黑", 10)).pack(side="right")
            info = (f"开始: {ev.start_date} | 截止: {ev.deadline} | "
                    f"删除于: {ev.deleted_at or '-'}")
            ctk.CTkLabel(card, text=info, anchor="w",
                          text_color="gray",
                          font=("微软雅黑", 10)).pack(fill="x", padx=10, pady=(0, 4))
            br = ctk.CTkFrame(card, fg_color="transparent")
            br.pack(fill="x", padx=10, pady=(0, 6))
            ctk.CTkButton(br, text="恢复", width=70, fg_color="#27ae60",
                           command=lambda e=ev: self._restore(e)).pack(side="left", padx=2)
            ctk.CTkButton(br, text="彻底删除", width=80, fg_color="#c0392b",
                           command=lambda e=ev: self._purge(e)).pack(side="left", padx=2)

    def _restore(self, ev):
        self.parent.restore_from_trash(ev)
        self._render()

    def _purge(self, ev):
        if messagebox.askyesno("确认", f"彻底删除「{ev.title}」？此操作不可恢复！", parent=self):
            self.parent.purge_from_trash(ev)
            self._render()

    def empty_all(self):
        if not self.parent.trash: return
        if messagebox.askyesno("确认", "确定清空回收站？此操作不可恢复！", parent=self):
            for ev in list(self.parent.trash):
                self.parent.purge_from_trash(ev)
            self._render()


class EditDialog(ctk.CTkToplevel):
    def __init__(self, parent, event):
        super().__init__(parent)
        self.parent = parent; self.event = event
        self.title("编辑事件")
        self.geometry("400x500")
        self.resizable(False, False)
        self.transient(parent); self.grab_set(); self.focus_force()

        ctk.CTkLabel(self, text="编辑事件",
                      font=("微软雅黑", 16, "bold")).pack(pady=(15, 10))
        ctk.CTkLabel(self, text="标题:").pack(anchor="w", padx=20)
        self.et = ctk.CTkEntry(self); self.et.pack(fill="x", padx=20, pady=(0, 8))
        self.et.insert(0, event.title)

        ctk.CTkLabel(self, text="开始时间:").pack(anchor="w", padx=20)
        self.es = ctk.CTkEntry(self); self.es.pack(fill="x", padx=20, pady=(0, 8))
        self.es.insert(0, event.start_date)

        ctk.CTkLabel(self, text="截止时间:").pack(anchor="w", padx=20)
        self.ed = ctk.CTkEntry(self); self.ed.pack(fill="x", padx=20, pady=(0, 8))
        self.ed.insert(0, event.deadline)

        ctk.CTkLabel(self, text="优先级:").pack(anchor="w", padx=20)
        self.pv = ctk.StringVar(value=PRIORITY_REVERSE.get(event.priority, "中"))
        ctk.CTkOptionMenu(self, values=["高", "中", "低"],
                           variable=self.pv).pack(fill="x", padx=20, pady=(0, 10))

        # 附件管理
        ctk.CTkLabel(self, text=f"附件 ({len(event.attachments)} 个):").pack(anchor="w", padx=20)
        af = ctk.CTkFrame(self, fg_color="transparent")
        af.pack(fill="x", padx=20, pady=(0, 8))
        ctk.CTkButton(af, text="➕添加附件", width=110,
                       command=self._add_attach).pack(side="left", padx=(0, 5))
        ctk.CTkButton(af, text="清空附件", width=80, fg_color="#95a5a6",
                       command=self._clear_attach).pack(side="left")
        self.attach_lbl = ctk.CTkLabel(self, text="", anchor="w",
                                        text_color="gray", font=("微软雅黑", 9))
        self.attach_lbl.pack(fill="x", padx=20)
        self._upd_attach_lbl()

        bf = ctk.CTkFrame(self, fg_color="transparent")
        bf.pack(pady=10)
        ctk.CTkButton(bf, text="保存", command=self.save,
                       width=80, fg_color="#2ecc71").pack(side="left", padx=5)
        ctk.CTkButton(bf, text="取消", command=self.destroy,
                       width=80, fg_color="#95a5a6").pack(side="left", padx=5)

    def _upd_attach_lbl(self):
        if not self.event.attachments:
            self.attach_lbl.configure(text="（无附件）")
        else:
            names = ", ".join(os.path.basename(p) for p in self.event.attachments)
            if len(names) > 60: names = names[:60] + "..."
            self.attach_lbl.configure(text=names)

    def _add_attach(self):
        files = filedialog.askopenfilenames(title="选择附件", parent=self)
        if not files: return
        ts = datetime.now().strftime("%Y%m%d%H%M%S")
        for i, f in enumerate(files):
            base = os.path.basename(f)
            target = os.path.join(ATTACH_DIR, f"{ts}_{i}_{base}")
            try:
                shutil.copy2(f, target)
                self.event.attachments.append(target)
            except Exception as e:
                messagebox.showerror("附件错误", str(e), parent=self)
        self._upd_attach_lbl()

    def _clear_attach(self):
        self.event.attachments = []
        self._upd_attach_lbl()

    def save(self):
        t = self.et.get().strip()
        if not t: messagebox.showwarning("提示", "标题不能为空！"); return
        try:
            datetime.strptime(self.es.get().strip(), "%Y-%m-%d")
            datetime.strptime(self.ed.get().strip(), "%Y-%m-%d")
        except: messagebox.showerror("错误", "日期格式错误！"); return
        if self.ed.get().strip() < self.es.get().strip():
            messagebox.showwarning("提示", "截止时间不能早于开始时间！"); return
        self.event.title = t
        self.event.start_date = self.es.get().strip()
        self.event.deadline = self.ed.get().strip()
        self.event.priority = PRIORITY_MAP.get(self.pv.get(), 2)
        self.parent.save(); self.parent.refresh()
        self.destroy()


class SummaryWin(ctk.CTkToplevel):
    def __init__(self, parent, ms, ss, done, und, use_deepseek=False):
        super().__init__(parent)
        self.parent = parent
        self.done = done
        self.und = und
        self.ms, self.ss = ms, ss
        self.use_deepseek = use_deepseek

        self.title(f"本周总结 ({ms} ~ {ss})")
        self.geometry("760x600")
        self.minsize(640, 440)
        self.transient(parent); self.grab_set(); self.focus_force(); self.lift()

        ctk.CTkLabel(self, text=f"本周总结 ({ms} ~ {ss})",
                      font=("微软雅黑", 16, "bold")).pack(pady=(15, 10))
        self.tb = ctk.CTkTextbox(self, wrap="word", font=("微软雅黑", 12))
        self.tb.pack(fill="both", expand=True, padx=15, pady=(0, 10))

        self._fill_basic_summary()

        bf = ctk.CTkFrame(self, fg_color="transparent")
        bf.pack(fill="x", padx=15, pady=(0, 15))
        ctk.CTkButton(bf, text="一键复制", command=self.copy,
                       height=35, fg_color="#3498db").pack(side="left", padx=(0, 10))
        if use_deepseek:
            self.btn_ai = ctk.CTkButton(bf, text="🤖 DeepSeek分析中...", state="disabled",
                                         height=35, fg_color="#9b59b6")
            self.btn_ai.pack(side="left")
        ctk.CTkButton(bf, text="关闭", command=self.destroy,
                       height=35, fg_color="#95a5a6").pack(side="right")
        self.protocol("WM_DELETE_WINDOW", self._close)

        if use_deepseek:
            threading.Thread(target=self._call_deepseek, daemon=True).start()

    def _fill_basic_summary(self):
        lines = []
        lines.append("=" * 50)
        lines.append("本周工作总结")
        lines.append("=" * 50 + "\n")
        lines.append("已完成事件：")
        if self.done:
            for i, ev in enumerate(self.done, 1):
                ct = ev.complete_time or "未知"
                lines.append(f"  {i}. {ev.title}")
                lines.append(f"     开始: {ev.start_date} | 截止: {ev.deadline} | 完成: {ct}")
        else: lines.append("  (本周暂无已完成事件)")
        lines.append("")
        lines.append("未完成事件：")
        if self.und:
            for i, ev in enumerate(self.und, 1):
                lines.append(f"  {i}. {ev.title}")
                lines.append(f"     开始: {ev.start_date} | 截止: {ev.deadline}")
        else: lines.append("  (本周所有事件均已完成！)")
        lines.append("")
        lines.append("=" * 50)
        self.tb.insert("1.0", "\n".join(lines))

    def _build_prompt(self):
        parts = [f"以下是用户本周（{self.ms} ~ {self.ss}）的工作事件，请用中文输出："
                 "1) 简洁的工作总结； 2) 进展评估； 3) 针对未完成事项的可行性建议与优先级排序； "
                 "4) 下周计划建议。\n\n已完成事件:"]
        if self.done:
            for ev in self.done:
                parts.append(f"- {ev.title} (开始 {ev.start_date}, 截止 {ev.deadline}, 优先级 {PRIORITY_REVERSE.get(ev.priority,'中')}, 完成 {ev.complete_time})")
        else:
            parts.append("- 无")
        parts.append("\n未完成事件:")
        if self.und:
            for ev in self.und:
                parts.append(f"- {ev.title} (开始 {ev.start_date}, 截止 {ev.deadline}, 优先级 {PRIORITY_REVERSE.get(ev.priority,'中')})")
        else:
            parts.append("- 无")
        return "\n".join(parts)

    def _call_deepseek(self):
        try:
            import requests
        except ImportError:
            self._append_ai_result("\n\n[DeepSeek] 缺少 requests 库，请先 pip install requests")
            return
        if not DEEPSEEK_API_KEY:
            self._append_ai_result("\n\n[DeepSeek] 未检测到 API Key。\n请设置环境变量 DEEPSEEK_API_KEY 后重试。")
            return
        prompt = self._build_prompt()
        try:
            resp = requests.post(
                DEEPSEEK_API_URL,
                headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                         "Content-Type": "application/json"},
                json={
                    "model": DEEPSEEK_MODEL,
                    "messages": [
                        {"role": "system", "content": "你是一个专业的工作助理，擅长任务总结与建议。"},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.5,
                    "stream": False
                },
                timeout=60
            )
            if resp.status_code != 200:
                self._append_ai_result(f"\n\n[DeepSeek] 请求失败 {resp.status_code}: {resp.text[:300]}")
                return
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            self._append_ai_result("\n\n" + "=" * 50 +
                                    "\n🤖 DeepSeek 智能总结与建议\n" +
                                    "=" * 50 + "\n" + content)
        except Exception as e:
            self._append_ai_result(f"\n\n[DeepSeek] 调用异常: {e}")

    def _append_ai_result(self, text):
        def do():
            try:
                self.tb.insert("end", text)
                if hasattr(self, "btn_ai"):
                    self.btn_ai.configure(text="🤖 DeepSeek 完成", state="disabled")
            except Exception: pass
        try:
            self.after(0, do)
        except Exception:
            pass

    def _close(self):
        self.grab_release(); self.destroy()

    def copy(self):
        c = self.tb.get("1.0", "end-1c")
        self.clipboard_clear(); self.clipboard_append(c)
        messagebox.showinfo("成功", "已复制到剪贴板！")


if __name__ == "__main__":
    app = NotepadApp()
    app.mainloop()