"""GutenRead - a compact RSVP speed-reading app for Project Gutenberg books."""
from __future__ import annotations

import math
import queue
import sys
import threading
import tkinter as tk
from dataclasses import asdict
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont

from . import __version__, catalog, store, textproc
from .themes import THEMES

MOD = "Command" if sys.platform == "darwin" else "Control"
MOD_LABEL = "Cmd" if sys.platform == "darwin" else "Ctrl"
PREFERRED_FONTS = ["Georgia", "Palatino Linotype", "Garamond", "Times New Roman",
                   "DejaVu Serif", "Liberation Serif", "Helvetica", "Arial", "Verdana",
                   "DejaVu Sans", "Consolas", "Courier New", "DejaVu Sans Mono", "Menlo"]
MIN_SIZE, MAX_SIZE = 16, 120
MIN_WPM, MAX_WPM = 100, 1000


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("GutenRead")
        self.geometry("660x430")
        self.minsize(560, 390)

        self.data = store.load()
        cfg = self.data["settings"]
        self.fonts = self._pick_fonts()
        self.colors = THEMES["Midnight"]
        self._queue: queue.Queue = queue.Queue()
        self._loading = False
        self.view = "catalog"

        self.theme_var = tk.StringVar(value=cfg["theme"] if cfg["theme"] in THEMES else "Midnight")
        self.font_var = tk.StringVar(value=cfg["font"] if cfg["font"] in self.fonts else self.fonts[0])
        self.size_var = tk.IntVar(value=int(cfg["size"]))
        self.wpm_var = tk.DoubleVar(value=float(cfg["wpm"]))
        self.wpm_text = tk.StringVar()
        self.punct_var = tk.BooleanVar(value=bool(cfg["punct"]))
        self.orp_var = tk.BooleanVar(value=bool(cfg["orp"]))

        self.container = ttk.Frame(self, padding=14)
        self.container.pack(fill="both", expand=True)
        self.catalog_view = CatalogView(self)
        self.reader = ReaderView(self)
        self.views = {"catalog": self.catalog_view, "reader": self.reader}

        self._menus: list[tk.Menu] = []
        self._build_menu()
        self.apply_theme()
        self._wire()
        self._show("catalog")

        self.protocol("WM_DELETE_WINDOW", self.quit_app)
        self.after(100, self._poll)
        self.after(250, self.catalog_view.search)

    # ---------------------------------------------------------------- setup
    def _pick_fonts(self) -> list[str]:
        families = set(tkfont.families(self))
        found = [f for f in PREFERRED_FONTS if f in families]
        return found or [tkfont.nametofont("TkDefaultFont").actual("family")]

    def _wire(self):
        def redraw(*_):
            self.reader.render()

        def wpm_changed(*_):
            self.wpm_text.set(f"{self.reader.wpm} wpm")
            self.reader.update_info()

        self.size_var.trace_add("write", redraw)
        self.font_var.trace_add("write", redraw)
        self.orp_var.trace_add("write", redraw)
        self.wpm_var.trace_add("write", wpm_changed)
        self.theme_var.trace_add("write", lambda *_: self.apply_theme())
        wpm_changed()

        self.bind_all("<<ComboboxSelected>>", lambda e: self.focus_set())
        shortcuts = {
            "<space>": self.toggle_play,
            "<Left>": lambda: self.reader.skip(-10),
            "<Right>": lambda: self.reader.skip(10),
            "<Up>": lambda: self.adjust_wpm(25),
            "<Down>": lambda: self.adjust_wpm(-25),
            "<Escape>": self.show_catalog,
        }
        for seq, action in shortcuts.items():
            self.bind(seq, self._reader_key(action))
        self.bind(f"<{MOD}-q>", lambda e: self.quit_app())
        self.bind(f"<{MOD}-o>", lambda e: self.open_file())
        self.bind(f"<{MOD}-l>", lambda e: self.show_catalog())
        for seq in (f"<{MOD}-equal>", f"<{MOD}-plus>"):
            self.bind(seq, lambda e: self.adjust_size(4))
        self.bind(f"<{MOD}-minus>", lambda e: self.adjust_size(-4))

    def _reader_key(self, action):
        def handler(event=None):
            if self.view != "reader":
                return None
            try:
                if isinstance(self.focus_get(), ttk.Entry):   # Entry, Combobox, Spinbox
                    return None
            except KeyError:
                pass
            action()
            return "break"
        return handler

    def _build_menu(self):
        def menu(parent=None):
            m = tk.Menu(parent or self, tearoff=False)
            self._menus.append(m)
            return m

        bar = menu()
        self.configure(menu=bar)

        file_m = menu(bar)
        bar.add_cascade(label="File", menu=file_m)
        file_m.add_command(label="Library", accelerator=f"{MOD_LABEL}+L", command=self.show_catalog)
        file_m.add_command(label="Open text file…", accelerator=f"{MOD_LABEL}+O", command=self.open_file)
        file_m.add_separator()
        file_m.add_command(label="Quit", accelerator=f"{MOD_LABEL}+Q", command=self.quit_app)

        view_m = menu(bar)
        bar.add_cascade(label="View", menu=view_m)
        theme_m = menu(view_m)
        for name in THEMES:
            theme_m.add_radiobutton(label=name, variable=self.theme_var, value=name)
        view_m.add_cascade(label="Theme", menu=theme_m)
        font_m = menu(view_m)
        for name in self.fonts:
            font_m.add_radiobutton(label=name, variable=self.font_var, value=name)
        view_m.add_cascade(label="Font", menu=font_m)
        view_m.add_command(label="Larger text", accelerator=f"{MOD_LABEL}++", command=lambda: self.adjust_size(4))
        view_m.add_command(label="Smaller text", accelerator=f"{MOD_LABEL}+-", command=lambda: self.adjust_size(-4))
        view_m.add_separator()
        view_m.add_checkbutton(label="Highlight focus letter", variable=self.orp_var)
        view_m.add_checkbutton(label="Pause longer at punctuation", variable=self.punct_var)

        play_m = menu(bar)
        bar.add_cascade(label="Playback", menu=play_m)
        play_m.add_command(label="Play / Pause", accelerator="Space", command=self.toggle_play)
        play_m.add_command(label="Back 10 words", accelerator="←", command=lambda: self.reader.skip(-10))
        play_m.add_command(label="Forward 10 words", accelerator="→", command=lambda: self.reader.skip(10))
        play_m.add_command(label="Restart book", command=self.reader.restart)
        play_m.add_separator()
        play_m.add_command(label="Faster", accelerator="↑", command=lambda: self.adjust_wpm(25))
        play_m.add_command(label="Slower", accelerator="↓", command=lambda: self.adjust_wpm(-25))

        help_m = menu(bar)
        bar.add_cascade(label="Help", menu=help_m)
        help_m.add_command(label="About GutenRead", command=self.about)

    def apply_theme(self):
        c = self.colors = THEMES[self.theme_var.get()]
        s = ttk.Style(self)
        s.theme_use("clam")
        self.configure(bg=c["bg"])
        s.configure(".", background=c["bg"], foreground=c["fg"], fieldbackground=c["field"],
                    bordercolor=c["sel"], lightcolor=c["bg"], darkcolor=c["bg"],
                    troughcolor=c["panel"], focuscolor=c["bg"], arrowcolor=c["fg"])
        s.configure("TFrame", background=c["bg"])
        s.configure("TLabel", background=c["bg"], foreground=c["fg"])
        s.configure("Muted.TLabel", foreground=c["muted"])
        title_font = tkfont.nametofont("TkDefaultFont").copy()
        title_font.configure(size=17, weight="bold")
        self._title_font = title_font
        s.configure("Title.TLabel", font=title_font)
        s.configure("TButton", background=c["panel"], foreground=c["fg"], borderwidth=0,
                    padding=(12, 6))
        s.map("TButton", background=[("active", c["sel"]), ("pressed", c["sel"]), ("disabled", c["bg"])],
              foreground=[("disabled", c["muted"])])
        s.configure("Accent.TButton", background=c["accent"], foreground=c["bg"])
        s.map("Accent.TButton", background=[("active", c["accent"]), ("pressed", c["accent"]),
                                            ("disabled", c["panel"])])
        for name in ("TEntry", "TCombobox", "TSpinbox"):
            s.configure(name, fieldbackground=c["field"], foreground=c["fg"], insertcolor=c["fg"],
                        bordercolor=c["sel"], lightcolor=c["field"], darkcolor=c["field"],
                        arrowcolor=c["fg"], background=c["panel"], padding=4)
        s.map("TCombobox", fieldbackground=[("readonly", c["field"])],
              foreground=[("readonly", c["fg"])],
              selectbackground=[("readonly", c["field"])], selectforeground=[("readonly", c["fg"])])
        s.configure("Treeview", background=c["field"], fieldbackground=c["field"], foreground=c["fg"],
                    borderwidth=0, rowheight=26)
        s.map("Treeview", background=[("selected", c["sel"])], foreground=[("selected", c["fg"])])
        s.configure("Treeview.Heading", background=c["panel"], foreground=c["muted"],
                    borderwidth=0, padding=(8, 5))
        s.map("Treeview.Heading", background=[("active", c["panel"])])
        s.configure("Horizontal.TScale", background=c["accent"], troughcolor=c["panel"],
                    bordercolor=c["bg"], lightcolor=c["accent"], darkcolor=c["accent"])
        s.map("Horizontal.TScale", background=[("active", c["accent"])])
        s.configure("TScrollbar", background=c["panel"], troughcolor=c["bg"], bordercolor=c["bg"],
                    arrowcolor=c["muted"])
        s.map("TScrollbar", background=[("active", c["sel"])])
        self.option_add("*TCombobox*Listbox.background", c["field"])
        self.option_add("*TCombobox*Listbox.foreground", c["fg"])
        self.option_add("*TCombobox*Listbox.selectBackground", c["sel"])
        self.option_add("*TCombobox*Listbox.selectForeground", c["fg"])
        for m in self._menus:
            try:
                m.configure(bg=c["panel"], fg=c["fg"], activebackground=c["sel"],
                            activeforeground=c["fg"], selectcolor=c["accent"], bd=0)
            except tk.TclError:
                pass
        self.reader.render()

    # ------------------------------------------------------------ plumbing
    def run_async(self, fn, done):
        """Run fn in a thread; call done(result, error) on the Tk thread."""
        def work():
            try:
                outcome = (fn(), None)
            except Exception as exc:  # noqa: BLE001 - surfaced to the UI
                outcome = (None, exc)
            self._queue.put((done, outcome))
        threading.Thread(target=work, daemon=True).start()

    def _poll(self):
        try:
            while True:
                done, (result, error) = self._queue.get_nowait()
                done(result, error)
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _show(self, name: str):
        for v in self.views.values():
            v.pack_forget()
        self.views[name].pack(fill="both", expand=True)
        self.view = name
        if name == "reader":
            self.reader.render()
        else:
            self.catalog_view.refresh_buttons()

    # -------------------------------------------------------------- actions
    def show_catalog(self):
        if self.view == "reader":
            self.reader.pause()
            self.save()
        self._show("catalog")

    def toggle_play(self):
        if self.view == "reader":
            self.reader.toggle()

    def adjust_wpm(self, delta: int):
        self.wpm_var.set(min(MAX_WPM, max(MIN_WPM, self.reader.wpm + delta)))

    def text_size(self) -> int:
        try:
            return min(MAX_SIZE, max(MIN_SIZE, int(self.size_var.get())))
        except (tk.TclError, ValueError):
            return 44

    def adjust_size(self, delta: int):
        self.size_var.set(min(MAX_SIZE, max(MIN_SIZE, self.text_size() + delta)))

    def open_book(self, book: catalog.Book):
        if self._loading:
            return
        self._loading = True
        self.catalog_view.set_status(f"Downloading “{book.title}”…")

        def done(text, err):
            self._loading = False
            if err:
                self.catalog_view.set_status("Download failed. Check your connection and try again.")
                return
            self.catalog_view.set_status("")
            self._start_reading(f"pg:{book.id}", book.title, text, asdict(book))

        self.run_async(lambda: catalog.fetch_text(book), done)

    def open_last(self):
        last = self.data.get("last")
        if not last:
            return
        if last.get("path"):
            self._open_path(last["path"])
        else:
            self.open_book(catalog.Book(**{k: last[k] for k in
                                           ("id", "title", "author", "text_url", "downloads")}))

    def open_file(self):
        path = filedialog.askopenfilename(
            title="Open a text file",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
        if path:
            self._open_path(path)

    def _open_path(self, path: str):
        try:
            text = catalog.decode(Path(path).read_bytes())
        except OSError as exc:
            messagebox.showerror("GutenRead", f"Couldn't read that file.\n\n{exc}")
            return
        self._start_reading(f"file:{path}", Path(path).stem, text,
                            {"path": path, "title": Path(path).stem})

    def _start_reading(self, key, title, text, last):
        try:
            self.reader.load(key, title, text)
        except ValueError as exc:
            messagebox.showerror("GutenRead", str(exc))
            return
        self.data["last"] = last
        self._show("reader")

    def save(self):
        self.reader.remember()
        self.data["settings"].update(
            theme=self.theme_var.get(), font=self.font_var.get(), size=self.text_size(),
            wpm=self.reader.wpm, punct=bool(self.punct_var.get()), orp=bool(self.orp_var.get()))
        store.save(self.data)

    def about(self):
        messagebox.showinfo(
            "About GutenRead",
            f"GutenRead {__version__}\n\nA small speed-reading tool for public-domain books.\n"
            "Books: Project Gutenberg (gutenberg.org)\nCatalogue: Gutendex (gutendex.com)")

    def quit_app(self):
        self.reader.pause()
        self.save()
        self.destroy()


class CatalogView(ttk.Frame):
    def __init__(self, app: App):
        super().__init__(app.container)
        self.app = app
        self.books: dict[str, catalog.Book] = {}
        self.next_url: str | None = None
        self._token = 0
        self.query = tk.StringVar()

        head = ttk.Frame(self)
        head.pack(fill="x")
        ttk.Label(head, text="GutenRead", style="Title.TLabel").pack(side="left")
        ttk.Label(head, text="   Choose a book to read", style="Muted.TLabel").pack(side="left", pady=(5, 0))

        row = ttk.Frame(self)
        row.pack(fill="x", pady=(12, 8))
        entry = ttk.Entry(row, textvariable=self.query)
        entry.pack(side="left", fill="x", expand=True)
        entry.bind("<Return>", lambda e: self.search())
        ttk.Button(row, text="Search", command=self.search, takefocus=False).pack(side="left", padx=(8, 0))

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(body, columns=("title", "author"), show="headings", selectmode="browse")
        self.tree.heading("title", text="Title", anchor="w")
        self.tree.heading("author", text="Author", anchor="w")
        self.tree.column("title", width=360, anchor="w")
        self.tree.column("author", width=170, anchor="w")
        scroll = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="left", fill="y")
        self.tree.bind("<Double-1>", lambda e: self.open_selected())
        self.tree.bind("<Return>", lambda e: self.open_selected())

        foot = ttk.Frame(self)
        foot.pack(fill="x", pady=(10, 0))
        self.status = ttk.Label(foot, style="Muted.TLabel")
        self.status.pack(side="left", fill="x", expand=True)
        self.read_btn = ttk.Button(foot, text="Read", style="Accent.TButton",
                                   command=self.open_selected, takefocus=False)
        self.read_btn.pack(side="right")
        self.continue_btn = ttk.Button(foot, text="Continue", command=app.open_last, takefocus=False)
        self.continue_btn.pack(side="right", padx=6)
        ttk.Button(foot, text="Open file…", command=app.open_file, takefocus=False).pack(side="right")
        self.more_btn = ttk.Button(foot, text="More", command=lambda: self.search(more=True), takefocus=False)
        self.more_btn.pack(side="right", padx=6)
        self.more_btn.state(["disabled"])

    def refresh_buttons(self):
        self.continue_btn.state(["!disabled"] if self.app.data.get("last") else ["disabled"])

    def set_status(self, text: str):
        self.status.configure(text=text)

    def search(self, more: bool = False):
        if more and not self.next_url:
            return
        self._token += 1
        token = self._token
        query = self.query.get().strip()
        url = self.next_url if more else None
        self.set_status("Loading…" if more else "Searching…")

        def done(result, err):
            if token != self._token:
                return
            if err:
                self.set_status("Catalogue unreachable. Try again, or use Open file….")
                return
            books, self.next_url = result
            if not more:
                self.tree.delete(*self.tree.get_children())
                self.books.clear()
            for b in books:
                if str(b.id) not in self.books:
                    self.books[str(b.id)] = b
                    self.tree.insert("", "end", iid=str(b.id), values=(b.title, b.author))
            self.more_btn.state(["!disabled"] if self.next_url else ["disabled"])
            n = len(self.books)
            self.set_status(f"{n} book{'s' if n != 1 else ''}" if n else "No matches")
            if n and not more:
                first = self.tree.get_children()[0]
                self.tree.selection_set(first)
                self.tree.focus(first)

        self.app.run_async(lambda: catalog.search(query, url), done)

    def open_selected(self):
        sel = self.tree.selection()
        if sel:
            self.app.open_book(self.books[sel[0]])


class ReaderView(ttk.Frame):
    def __init__(self, app: App):
        super().__init__(app.container)
        self.app = app
        self.words: list[str] = []
        self.idx = 0
        self.key = ""
        self.title = ""
        self.playing = False
        self._job = None
        self._updating = False
        self._font = tkfont.Font(root=app, family=app.font_var.get(), size=app.size_var.get())

        top = ttk.Frame(self)
        top.pack(fill="x")
        ttk.Button(top, text="‹ Library", command=app.show_catalog, takefocus=False).pack(side="left")
        self.title_lbl = ttk.Label(top, style="Muted.TLabel", anchor="e")
        self.title_lbl.pack(side="right", fill="x", expand=True, padx=(12, 0))

        self.stage = tk.Canvas(self, height=150, highlightthickness=0, bd=0)
        self.stage.pack(fill="both", expand=True, pady=10)
        self.stage.bind("<Configure>", lambda e: self.render())
        self.stage.bind("<Button-1>", lambda e: (app.focus_set(), self.toggle()))

        prog = ttk.Frame(self)
        prog.pack(fill="x")
        self.seek = ttk.Scale(prog, from_=0, to=1, command=self._on_seek, takefocus=False)
        self.seek.pack(side="left", fill="x", expand=True)
        self.info = ttk.Label(prog, style="Muted.TLabel", width=20, anchor="e")
        self.info.pack(side="right", padx=(12, 0))

        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(12, 0))
        ttk.Button(bar, text="◀ 10", width=6, command=lambda: self.skip(-10), takefocus=False).pack(side="left")
        self.play_btn = ttk.Button(bar, text="▶  Play", width=10, style="Accent.TButton",
                                   command=self.toggle, takefocus=False)
        self.play_btn.pack(side="left", padx=6)
        ttk.Button(bar, text="10 ▶", width=6, command=lambda: self.skip(10), takefocus=False).pack(side="left")
        ttk.Label(bar, textvariable=app.wpm_text, width=8, anchor="e").pack(side="right")
        ttk.Scale(bar, from_=MIN_WPM, to=MAX_WPM, variable=app.wpm_var, length=170,
                  takefocus=False).pack(side="right", padx=(0, 8))

        opts = ttk.Frame(self)
        opts.pack(fill="x", pady=(12, 0))
        ttk.Label(opts, text="Theme", style="Muted.TLabel").pack(side="left")
        ttk.Combobox(opts, textvariable=app.theme_var, values=list(THEMES), state="readonly",
                     width=10).pack(side="left", padx=(6, 14))
        ttk.Label(opts, text="Font", style="Muted.TLabel").pack(side="left")
        ttk.Combobox(opts, textvariable=app.font_var, values=app.fonts, state="readonly",
                     width=17).pack(side="left", padx=(6, 14))
        ttk.Label(opts, text="Size", style="Muted.TLabel").pack(side="left")
        ttk.Spinbox(opts, from_=MIN_SIZE, to=MAX_SIZE, increment=2, textvariable=app.size_var,
                    width=4).pack(side="left", padx=6)

    @property
    def wpm(self) -> int:
        try:
            value = float(self.app.wpm_var.get())
        except tk.TclError:
            value = 300
        return max(MIN_WPM, int(round(value / 5)) * 5)

    # ------------------------------------------------------------ loading
    def load(self, key: str, title: str, raw: str):
        self.pause()
        words = textproc.prepare(raw)
        if len(words) < 50:
            raise ValueError("That file doesn't contain enough readable text.")
        self.words, self.key, self.title = words, key, title
        saved = self.app.data["progress"].get(key, {})
        self.idx = min(max(int(saved.get("idx", 0)), 0), len(words) - 1)
        self.seek.configure(to=len(words) - 1)
        self.title_lbl.configure(text=title)
        self.render()

    def remember(self):
        if self.key and self.words:
            self.app.data["progress"][self.key] = {"title": self.title, "idx": self.idx}

    # ----------------------------------------------------------- playback
    def toggle(self):
        if not self.words:
            return
        self.pause() if self.playing else self.play()

    def play(self):
        if self.idx >= len(self.words) - 1:
            self.idx = 0
        self.playing = True
        self.play_btn.configure(text="❚❚  Pause")
        self._tick()

    def pause(self):
        self.playing = False
        if self._job is not None:
            self.after_cancel(self._job)
            self._job = None
        self.play_btn.configure(text="▶  Play")
        self.remember()

    def _tick(self):
        if not self.playing:
            return
        self.render()
        word = self.words[self.idx]
        delay = textproc.word_delay_ms(word, self.wpm, bool(self.app.punct_var.get()))
        if self.idx >= len(self.words) - 1:
            self._job = self.after(delay, self.pause)
            return
        self.idx += 1
        self._job = self.after(delay, self._tick)

    def skip(self, n: int):
        if self.words:
            self.idx = min(max(self.idx + n, 0), len(self.words) - 1)
            self.render()

    def restart(self):
        if self.words:
            self.idx = 0
            self.render()

    def _on_seek(self, value):
        if self._updating or not self.words:
            return
        self.idx = int(float(value))
        self.render()

    # ---------------------------------------------------------- rendering
    def update_info(self):
        n = len(self.words)
        if not n:
            self.info.configure(text="")
            return
        pct = 100 * self.idx / max(1, n - 1)
        mins = math.ceil((n - self.idx) / self.wpm)
        left = f"{mins} min left" if mins < 60 else f"{mins // 60} h {mins % 60:02d} min left"
        self.info.configure(text=f"{pct:.0f}%  ·  {left}")
        self._updating = True
        self.seek.set(self.idx)
        self._updating = False

    def retheme(self):
        self.render()

    def render(self):
        c = self.app.colors
        cv = self.stage
        cv.delete("all")
        cv.configure(bg=c["panel"])
        w, h = cv.winfo_width(), cv.winfo_height()
        if w < 40 or not self.words:
            return
        cx, cy = w / 2, h / 2
        f = self._font
        f.configure(family=self.app.font_var.get(), size=self.app.text_size())
        left, pivot, right = textproc.split_pivot(self.words[self.idx])

        def measure():
            return f.measure(left), f.measure(pivot), f.measure(right)

        lw, pw, rw = measure()
        while f.cget("size") > 10 and (max(lw, rw) + pw / 2 > cx - 16
                                       or f.metrics("linespace") + 44 > h):
            f.configure(size=f.cget("size") - 1)
            lw, pw, rw = measure()

        accent = c["accent"] if self.app.orp_var.get() else c["fg"]
        cv.create_text(cx - pw / 2, cy, text=left, anchor="e", font=f, fill=c["fg"])
        cv.create_text(cx, cy, text=pivot, anchor="center", font=f, fill=accent)
        cv.create_text(cx + pw / 2, cy, text=right, anchor="w", font=f, fill=c["fg"])
        gap = f.metrics("linespace") / 2 + 4
        for sign in (-1, 1):
            cv.create_line(cx, cy + sign * gap, cx, cy + sign * (gap + 9), fill=c["muted"], width=2)
        self.update_info()


def main():
    try:  # crisp text on high-DPI Windows displays
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:  # noqa: BLE001 - not on Windows
        pass
    App().mainloop()


if __name__ == "__main__":
    main()
