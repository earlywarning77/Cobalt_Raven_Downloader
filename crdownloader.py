import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from yt_dlp import YoutubeDL
import os
import threading
from datetime import datetime
import time
import json
import sqlite3
import tempfile
import shutil
import queue


# ── Colour palette ────────────────────────────────────────────────────────────
BG        = "#1a1a2e"
SURFACE   = "#16213e"
ACCENT    = "#0f3460"
HIGHLIGHT = "#e94560"
TEXT      = "#eaeaea"
SUBTEXT   = "#a0a0b0"
SUCCESS   = "#4caf50"
WARNING   = "#ff9800"


class VideoDownloader:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Cobalt Raven Downloader")
        self.root.configure(bg=BG)
        self.root.minsize(820, 620)

        self.setup_variables()
        self.create_gui()

        self.available_formats = {}

        # Cookie file: prefer sqlite, fall back to json
        self.cookies_file = (
            "cookies.sqlite" if os.path.exists("cookies.sqlite")
            else "cookies.json"
        )
        self.load_cookies()

        # Download queue (list of dicts with url + format info)
        self.download_queue   = []
        self.queue_running    = False

    # ── Variables ─────────────────────────────────────────────────────────────

    def setup_variables(self):
        self.url_var        = tk.StringVar()
        self.output_dir_var = tk.StringVar(
            value=os.path.join(os.path.expanduser("~"), "Downloads")
        )
        self.status_var     = tk.StringVar(value="Ready")
        self.progress_var   = tk.DoubleVar()
        self.audio_only_var = tk.BooleanVar(value=False)

    # ── GUI ───────────────────────────────────────────────────────────────────

    def create_gui(self):
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        main = tk.Frame(self.root, bg=BG, padx=14, pady=14)
        main.grid(row=0, column=0, sticky="nsew")
        main.columnconfigure(1, weight=1)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TLabel",        background=BG,      foreground=TEXT,      font=("Segoe UI", 9))
        style.configure("TButton",       background=ACCENT,  foreground=TEXT,      font=("Segoe UI", 9, "bold"), padding=5)
        style.map("TButton",             background=[("active", HIGHLIGHT)])
        style.configure("TEntry",        fieldbackground=SURFACE, foreground=TEXT,  insertcolor=TEXT)
        style.configure("TFrame",        background=BG)
        style.configure("TCheckbutton",  background=BG,      foreground=TEXT,      font=("Segoe UI", 9))
        style.configure("Horizontal.TProgressbar",        troughcolor=SURFACE, background=HIGHLIGHT)
        style.configure("Queue.Horizontal.TProgressbar", troughcolor=SURFACE, background=SUCCESS)

        # ── Row 0: URL ────────────────────────────────────────────────────────
        ttk.Label(main, text="Video URL:").grid(row=0, column=0, sticky="w", pady=(0, 4))
        url_frame = tk.Frame(main, bg=BG)
        url_frame.grid(row=0, column=1, columnspan=2, sticky="ew", pady=(0, 4))
        url_frame.columnconfigure(0, weight=1)

        self.url_entry = tk.Entry(
            url_frame, textvariable=self.url_var,
            bg=SURFACE, fg=TEXT, insertbackground=TEXT,
            relief="flat", font=("Segoe UI", 9), bd=4
        )
        self.url_entry.grid(row=0, column=0, sticky="ew", ipady=4)
        ttk.Button(url_frame, text="Fetch Formats", command=self.fetch_formats_thread).grid(
            row=0, column=1, padx=(6, 0)
        )

        # ── Row 1: Audio-only toggle ──────────────────────────────────────────
        ttk.Checkbutton(
            main, text="Audio only (MP3)", variable=self.audio_only_var,
            command=self._on_audio_toggle
        ).grid(row=1, column=1, sticky="w", pady=(0, 4))

        # ── Row 2: Formats listbox ────────────────────────────────────────────
        ttk.Label(main, text="Formats:").grid(row=2, column=0, sticky="nw", pady=(0, 2))

        list_frame = tk.Frame(main, bg=BG)
        list_frame.grid(row=2, column=1, columnspan=2, sticky="nsew", pady=(0, 4))
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)
        main.rowconfigure(2, weight=1)

        self.formats_listbox = tk.Listbox(
            list_frame, height=12,
            bg=SURFACE, fg=TEXT, selectbackground=HIGHLIGHT,
            selectforeground=TEXT, activestyle="none",
            relief="flat", font=("Consolas", 8), bd=0
        )
        self.formats_listbox.grid(row=0, column=0, sticky="nsew")

        v_scroll = ttk.Scrollbar(list_frame, orient=tk.VERTICAL,   command=self.formats_listbox.yview)
        h_scroll = ttk.Scrollbar(list_frame, orient=tk.HORIZONTAL, command=self.formats_listbox.xview)
        v_scroll.grid(row=0, column=1, sticky="ns")
        h_scroll.grid(row=1, column=0, sticky="ew")
        self.formats_listbox.configure(yscrollcommand=v_scroll.set, xscrollcommand=h_scroll.set)

        # ── Row 3: Output dir ─────────────────────────────────────────────────
        ttk.Label(main, text="Output Dir:").grid(row=3, column=0, sticky="w", pady=(4, 4))
        ttk.Entry(main, textvariable=self.output_dir_var).grid(
            row=3, column=1, sticky="ew", padx=(0, 4), pady=(4, 4)
        )
        ttk.Button(main, text="Browse", command=self.choose_directory).grid(row=3, column=2, pady=(4, 4))

        # ── Row 4: Progress bar (current download) ────────────────────────────
        ttk.Label(main, text="Progress:").grid(row=4, column=0, sticky="w")
        self.progress_bar = ttk.Progressbar(
            main, mode="determinate", variable=self.progress_var,
            style="Horizontal.TProgressbar"
        )
        self.progress_bar.grid(row=4, column=1, columnspan=2, sticky="ew", pady=(4, 2))

        # ── Row 5: Status label ───────────────────────────────────────────────
        self.status_label = tk.Label(
            main, textvariable=self.status_var,
            bg=BG, fg=SUBTEXT, font=("Segoe UI", 8), anchor="w"
        )
        self.status_label.grid(row=5, column=0, columnspan=3, sticky="ew", pady=(0, 6))

        # ── Row 6: Queue section ──────────────────────────────────────────────
        sep = tk.Frame(main, bg=ACCENT, height=1)
        sep.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(0, 6))

        tk.Label(main, text="Download Queue", bg=BG, fg=TEXT,
                 font=("Segoe UI", 9, "bold")).grid(row=7, column=0, columnspan=3, sticky="w")

        queue_frame = tk.Frame(main, bg=BG)
        queue_frame.grid(row=8, column=0, columnspan=3, sticky="nsew", pady=(4, 4))
        queue_frame.columnconfigure(0, weight=1)
        main.rowconfigure(8, weight=1)

        self.queue_listbox = tk.Listbox(
            queue_frame, height=5,
            bg=SURFACE, fg=TEXT, selectbackground=ACCENT,
            selectforeground=TEXT, activestyle="none",
            relief="flat", font=("Segoe UI", 8), bd=0
        )
        self.queue_listbox.grid(row=0, column=0, sticky="nsew")
        q_scroll = ttk.Scrollbar(queue_frame, orient=tk.VERTICAL, command=self.queue_listbox.yview)
        q_scroll.grid(row=0, column=1, sticky="ns")
        self.queue_listbox.configure(yscrollcommand=q_scroll.set)

        # ── Row 9: Queue progress bar ─────────────────────────────────────────
        self.queue_progress_var = tk.DoubleVar()
        self.queue_progress_bar = ttk.Progressbar(
            main, mode="determinate", variable=self.queue_progress_var,
            style="Queue.Horizontal.TProgressbar"
        )
        self.queue_progress_bar.grid(row=9, column=0, columnspan=3, sticky="ew", pady=(2, 4))

        # ── Row 10: Buttons ───────────────────────────────────────────────────
        btn_frame = tk.Frame(main, bg=BG)
        btn_frame.grid(row=10, column=0, columnspan=3, pady=(4, 0))

        buttons = [
            ("Add to Queue",   self.add_to_queue),
            ("Download Now",   self.download_video_thread),
            ("Start Queue",    self.start_queue_thread),
            ("Remove from Queue", self.remove_from_queue),
            ("Load Cookies",   self.select_cookies),
            ("Exit",           self.root.quit),
        ]
        for i, (label, cmd) in enumerate(buttons):
            ttk.Button(btn_frame, text=label, command=cmd).grid(row=0, column=i, padx=4)

    # ── Audio toggle ──────────────────────────────────────────────────────────

    def _on_audio_toggle(self):
        """When audio-only is selected, clear format list and refetch if URL present."""
        self.formats_listbox.delete(0, tk.END)
        self.available_formats.clear()
        if self.url_var.get().strip():
            self.fetch_formats_thread()

    # ── Cookie handling ───────────────────────────────────────────────────────

    def load_cookies(self):
        self.cookies_loaded = False
        if not os.path.exists(self.cookies_file):
            self.cookies = None
            self.status_var.set("No cookies file found — continuing without cookies")
            return

        try:
            # Try JSON first
            try:
                with open(self.cookies_file, "r") as f:
                    self.cookies = json.load(f)
                self.cookies_loaded = True
                self.status_var.set("JSON cookies loaded")
                return
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass

            # Try SQLite (Firefox-style)
            if self.cookies_file.endswith(".sqlite"):
                temp = os.path.join(tempfile.gettempdir(), "cookies_temp.sqlite")
                shutil.copy2(self.cookies_file, temp)
                try:
                    conn   = sqlite3.connect(temp)
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT name, value, host FROM moz_cookies WHERE host LIKE '%youtube.com'"
                    )
                    rows = cursor.fetchall()
                    conn.close()

                    if rows:
                        cookie_txt = os.path.join(tempfile.gettempdir(), "cookies.txt")
                        with open(cookie_txt, "w") as f:
                            for name, value, host in rows:
                                f.write(f"{host}\tTRUE\t/\tFALSE\t2597573456\t{name}\t{value}\n")
                        self.cookies_file  = cookie_txt
                        self.cookies_loaded = True
                        self.status_var.set("SQLite cookies loaded")
                    else:
                        self.status_var.set("No YouTube cookies in SQLite file")
                finally:
                    try:
                        os.remove(temp)
                    except OSError:
                        pass

        except Exception as e:
            self.status_var.set(f"Cookie load error: {e}")
            self.cookies = None

    def select_cookies(self):
        path = filedialog.askopenfilename(filetypes=[("Cookie files", "*.json *.sqlite *.txt")])
        if path:
            self.cookies_file = path
            self.load_cookies()

    # ── URL helpers ───────────────────────────────────────────────────────────

    def clean_url(self, url: str) -> str:
        url = url.strip()
        if "youtube.com" in url or "youtu.be" in url:
            if "&list=" in url:
                url = url.split("&list=")[0]
        return url

    # ── yt-dlp options ────────────────────────────────────────────────────────

    def _base_opts(self) -> dict:
        opts = {
            "ignoreerrors":               True,
            "no_warnings":                False,
            "quiet":                      False,
            "socket_timeout":             30,
            "retries":                    5,
            "fragment_retries":           5,
            "skip_unavailable_fragments": True,
            "nocheckcertificate":         True,
            "geo_bypass":                 True,
            "concurrent_fragments":       1,
            "http_chunk_size":            10 * 1024 * 1024,
            # Use default player client; EJS + Node solves the n-challenge
            "extractor_args": {
                "youtube": {
                    "player_client": ["default"],
                }
            },
            # Auto-download EJS challenge solver scripts from GitHub
            # (equivalent to --remote-components ejs:github on CLI)
            "remote_components": ["ejs:github"],
            # Prefer Node.js as JS runtime; falls back to Deno if absent
            "js_runtimes": {"node": {}, "deno": {}},
            "http_headers": {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/126.0.0.0 Safari/537.36"
                )
            },
        }
        if self.cookies_loaded:
            opts["cookiefile"] = self.cookies_file
        return opts

    def get_info_opts(self) -> dict:
        """yt-dlp options for fetching format info (no download)."""
        opts = self._base_opts()
        opts.update({
            "skip_download": True,
            "listformats":   False,
        })
        return opts

    def get_audio_opts(self, output: str) -> dict:
        """yt-dlp options for audio-only MP3 download."""
        opts = self._base_opts()
        opts.update({
            "format":            "bestaudio/best",
            "outtmpl":           output,
            "progress_hooks":    [self.progress_hook],
            "postprocessors": [{
                "key":            "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
        })
        return opts

    def get_download_opts(self, fmt_str: str, output: str) -> dict:
        """yt-dlp options for a standard video+audio download."""
        opts = self._base_opts()
        opts.update({
            "format":         fmt_str,
            "outtmpl":        output,
            "progress_hooks": [self.progress_hook],
            "merge_output_format": "mp4",
        })
        return opts

    # ── Progress hook ─────────────────────────────────────────────────────────

    def progress_hook(self, d):
        if d["status"] == "downloading":
            try:
                total      = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
                downloaded = d.get("downloaded_bytes", 0)
                speed      = d.get("speed", 0) or 0
                eta        = d.get("eta", 0) or 0

                speed_str = (
                    f"{speed / 1_048_576:.1f} MB/s" if speed > 1_048_576
                    else f"{speed / 1024:.0f} KB/s" if speed > 0
                    else ""
                )
                eta_str = f"  ETA {eta}s" if eta else ""

                if total > 0:
                    pct = (downloaded / total) * 100
                    self.progress_var.set(pct)
                    self.status_var.set(f"Downloading: {pct:.1f}%  {speed_str}{eta_str}")
            except Exception:
                pass

        elif d["status"] == "finished":
            self.progress_var.set(100)
            self.status_var.set("Processing…")

        elif d["status"] == "error":
            self.status_var.set("Error during download")

    # ── Format helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _fmt_size(size) -> str:
        if not size:
            return "Unknown"
        if size < 1024:
            return f"{size}B"
        if size < 1024 ** 2:
            return f"{size / 1024:.1f}KB"
        if size < 1024 ** 3:
            return f"{size / 1024 ** 2:.1f}MB"
        return f"{size / 1024 ** 3:.1f}GB"

    def format_display_string(self, fmt: dict) -> str:
        return (
            f"ID: {fmt.get('format_id','?'):>4} | "
            f"{fmt.get('resolution','Unknown'):>9} | "
            f"Size: {self._fmt_size(fmt.get('filesize')):>9} | "
            f"Fmt: {fmt.get('ext','?'):>4} | "
            f"VCodec: {fmt.get('vcodec','?'):<14} | "
            f"ACodec: {fmt.get('acodec','?')}"
        )

    # ── Fetch formats ─────────────────────────────────────────────────────────

    def fetch_formats(self):
        url = self.clean_url(self.url_var.get())
        if not url:
            messagebox.showerror("Error", "Please enter a video URL")
            return

        self.url_var.set(url)
        self.formats_listbox.delete(0, tk.END)
        self.available_formats.clear()

        # Audio-only mode: no need to list formats
        if self.audio_only_var.get():
            self.formats_listbox.insert(tk.END, "  ► Audio Only (best quality → MP3 192kbps)")
            self.available_formats["  ► Audio Only (best quality → MP3 192kbps)"] = {"_audio_only": True}
            self.status_var.set("Audio-only mode — click Download Now or Add to Queue")
            return

        resolutions = ["144p", "240p", "360p", "480p", "720p", "1080p", "1440p", "2160p"]

        for attempt in range(1, 4):
            try:
                self.status_var.set(f"Fetching formats (attempt {attempt}/3)…")
                with YoutubeDL(self.get_info_opts()) as ydl:
                    info = ydl.extract_info(url, download=False)

                if not info:
                    raise ValueError("No video info returned — video may be private or unavailable")

                formats = info.get("formats") or info.get("requested_formats") or []
                if not formats:
                    raise ValueError("No formats found for this video")

                # Keep only formats with video
                video_fmts = [f for f in formats if f.get("vcodec") not in (None, "none")]
                if not video_fmts:
                    video_fmts = formats

                video_fmts.sort(
                    key=lambda x: (
                        resolutions.index(x.get("resolution", "0p"))
                        if x.get("resolution", "0p") in resolutions else -1,
                        x.get("filesize") or 0,
                    ),
                    reverse=True,
                )

                for fmt in video_fmts:
                    label = self.format_display_string(fmt)
                    self.formats_listbox.insert(tk.END, label)
                    self.available_formats[label] = fmt

                self.status_var.set(f"Found {len(video_fmts)} formats")
                return

            except Exception as e:
                self.status_var.set(f"Attempt {attempt} failed: {e}")
                if attempt < 3:
                    time.sleep(2)

        messagebox.showerror(
            "Fetch Failed",
            "Could not fetch formats after 3 attempts.\n\n"
            "• Check the URL is correct\n"
            "• Video may be private or age-restricted\n"
            "• Try: pip install --upgrade yt-dlp\n"
            "• Wait a moment and retry"
        )

    def fetch_formats_thread(self):
        threading.Thread(target=self.fetch_formats, daemon=True).start()

    # ── Output template helper ────────────────────────────────────────────────

    def _output_template(self) -> str:
        return os.path.join(self.output_dir_var.get(), "%(title)s.%(ext)s")

    # ── Single download ───────────────────────────────────────────────────────

    def _do_download(self, url: str, fmt_data: dict):
        """Core download logic — called from threads."""
        is_audio = fmt_data.get("_audio_only", False)
        output   = self._output_template()

        if is_audio:
            ydl_opts = self.get_audio_opts(output)
        else:
            fid      = fmt_data.get("format_id", "best")
            fmt_str  = f"{fid}+bestaudio/bestaudio/{fid}"
            ydl_opts = self.get_download_opts(fmt_str, output)

        with YoutubeDL(ydl_opts) as ydl:
            self.status_var.set("Starting download…")
            self.progress_var.set(0)
            ydl.download([url])

    def download_video(self):
        selected = self.formats_listbox.curselection()
        if not selected:
            messagebox.showerror("Error", "Please select a format first")
            return

        label    = self.formats_listbox.get(selected[0])
        fmt_data = self.available_formats.get(label)
        if not fmt_data:
            messagebox.showerror("Error", "Invalid format selected")
            return

        url = self.clean_url(self.url_var.get())
        if not url:
            messagebox.showerror("Error", "No URL entered")
            return

        if not self.output_dir_var.get():
            messagebox.showerror("Error", "Please select an output directory")
            return

        try:
            self._do_download(url, fmt_data)
            self.status_var.set("Download completed!")
            messagebox.showinfo("Done", "Download completed successfully!")
        except Exception as e:
            self.status_var.set(f"Download failed: {e}")
            messagebox.showerror("Error", f"Download failed:\n{e}")

    def download_video_thread(self):
        threading.Thread(target=self.download_video, daemon=True).start()

    # ── Queue management ──────────────────────────────────────────────────────

    def add_to_queue(self):
        selected = self.formats_listbox.curselection()
        if not selected:
            messagebox.showerror("Error", "Please select a format first")
            return

        label    = self.formats_listbox.get(selected[0])
        fmt_data = self.available_formats.get(label)
        url      = self.clean_url(self.url_var.get())

        if not url or not fmt_data:
            messagebox.showerror("Error", "Select a URL and format before adding to queue")
            return

        entry = {"url": url, "fmt_data": fmt_data, "label": label}
        self.download_queue.append(entry)

        short_url = url[:60] + "…" if len(url) > 60 else url
        self.queue_listbox.insert(
            tk.END,
            f"[{'AUDIO' if fmt_data.get('_audio_only') else fmt_data.get('format_id','?')}]  {short_url}"
        )
        self.status_var.set(f"Added to queue ({len(self.download_queue)} item(s))")

    def remove_from_queue(self):
        selected = self.queue_listbox.curselection()
        if not selected:
            return
        idx = selected[0]
        self.queue_listbox.delete(idx)
        if idx < len(self.download_queue):
            self.download_queue.pop(idx)
        self.status_var.set(f"{len(self.download_queue)} item(s) in queue")

    def _run_queue(self):
        if self.queue_running:
            return
        if not self.download_queue:
            messagebox.showinfo("Queue", "Queue is empty")
            return

        self.queue_running = True
        total = len(self.download_queue)

        for i, entry in enumerate(list(self.download_queue)):
            self.queue_progress_var.set((i / total) * 100)
            self.status_var.set(f"Queue: item {i + 1}/{total}")

            try:
                self._do_download(entry["url"], entry["fmt_data"])
            except Exception as e:
                self.status_var.set(f"Queue item {i + 1} failed: {e}")
                # Continue with next item rather than aborting
                continue

            # Remove completed item from listbox
            self.queue_listbox.delete(0)

        self.download_queue.clear()
        self.queue_progress_var.set(100)
        self.queue_running = False
        self.status_var.set("Queue finished!")
        messagebox.showinfo("Queue", "All queued downloads completed!")

    def start_queue_thread(self):
        threading.Thread(target=self._run_queue, daemon=True).start()

    # ── Misc ──────────────────────────────────────────────────────────────────

    def choose_directory(self):
        d = filedialog.askdirectory()
        if d:
            self.output_dir_var.set(d)

    def run(self):
        self.root.mainloop()


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    downloader = VideoDownloader()
    downloader.run()
