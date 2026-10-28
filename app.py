"""Tkinter desktop interface for AUTOCLIP AI."""
from __future__ import annotations

import json
import os
import queue
import shutil
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from pipeline import PipelineError, process, validate_youtube_url

BASE = Path(__file__).resolve().parent
OUTPUT = BASE / "output"
BG = "#101827"
PANEL = "#1b283b"
ACCENT = "#69e5bb"
TEXT = "#f5f8ff"
MUTED = "#a8b7cc"


class AutoClipApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("AUTOCLIP AI")
        self.geometry("1040x790")
        self.minsize(760, 570)
        self.configure(bg=BG)
        self.source = tk.StringVar()
        self.status = tk.StringVar(value="Ready. Paste a YouTube link or import a local video.")
        self.progress = tk.DoubleVar(value=0)
        self.events: queue.Queue[tuple] = queue.Queue()
        self.current_job: Path | None = None
        self.images: list[tk.PhotoImage] = []
        self.busy = False
        self._style()
        self._build()
        self.after(100, self._poll)

    def _style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TProgressbar", troughcolor=PANEL, background=ACCENT, bordercolor=PANEL)
        style.configure("Primary.TButton", font=("Segoe UI", 11, "bold"), padding=(17, 11),
                        background=ACCENT, foreground=BG, borderwidth=0)
        style.map("Primary.TButton", background=[("active", "#8ff5d2"), ("disabled", "#596e75")])
        style.configure("Secondary.TButton", font=("Segoe UI", 10), padding=(10, 7),
                        background="#31425a", foreground=TEXT, borderwidth=0)
        style.map("Secondary.TButton", background=[("active", "#405674")])
        style.configure("TEntry", padding=9, fieldbackground="#f6f9ff", foreground="#172132")

    def _build(self) -> None:
        outer = tk.Frame(self, bg=BG, padx=28, pady=22)
        outer.pack(fill="both", expand=True)
        tk.Label(outer, text="AUTOCLIP AI", font=("Segoe UI", 27, "bold"), fg=TEXT, bg=BG).pack(anchor="w")
        tk.Label(outer, text="One video in. The strongest moments out.", font=("Segoe UI", 11),
                 fg=MUTED, bg=BG).pack(anchor="w", pady=(0, 18))
        form = tk.Frame(outer, bg=PANEL, padx=18, pady=18)
        form.pack(fill="x")
        tk.Label(form, text="YOUTUBE VIDEO URL", font=("Segoe UI", 9, "bold"),
                 fg=ACCENT, bg=PANEL).pack(anchor="w", pady=(0, 6))
        self.entry = ttk.Entry(form, textvariable=self.source, font=("Segoe UI", 11))
        self.entry.pack(fill="x")
        self.entry.bind("<Return>", lambda _event: self._start())
        actions = tk.Frame(form, bg=PANEL)
        actions.pack(fill="x", pady=(14, 0))
        self.generate = ttk.Button(actions, text="Generate Clips", style="Primary.TButton", command=self._start)
        self.generate.pack(side="left")
        ttk.Button(actions, text="Import Local Video", style="Secondary.TButton",
                   command=self._import).pack(side="left", padx=9)
        ttk.Button(actions, text="Open Output Folder", style="Secondary.TButton",
                   command=self._open_output).pack(side="right")
        ttk.Button(actions, text="Export All", style="Secondary.TButton",
                   command=self._export_all).pack(side="right", padx=8)
        tk.Label(outer, textvariable=self.status, font=("Segoe UI", 10),
                 fg=MUTED, bg=BG, wraplength=900, justify="left").pack(anchor="w", pady=(17, 7))
        ttk.Progressbar(outer, maximum=1, variable=self.progress).pack(fill="x", pady=(0, 18))
        tk.Label(outer, text="YOUR CLIPS", font=("Segoe UI", 15, "bold"), fg=TEXT, bg=BG).pack(anchor="w")
        self.canvas = tk.Canvas(outer, bg=BG, highlightthickness=0)
        scroll = ttk.Scrollbar(outer, orient="vertical", command=self.canvas.yview)
        self.list_frame = tk.Frame(self.canvas, bg=BG)
        self.list_frame.bind("<Configure>", lambda _event: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas_window = self.canvas.create_window((0, 0), window=self.list_frame, anchor="nw")
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self.canvas_window, width=e.width))
        self.canvas.configure(yscrollcommand=scroll.set)
        self.canvas.pack(side="left", fill="both", expand=True, pady=(8, 0))
        scroll.pack(side="right", fill="y")
        self._empty()

    def _empty(self) -> None:
        tk.Label(self.list_frame, text="Finished clips will appear here with thumbnails, scores, and suggested captions.",
                 font=("Segoe UI", 11), fg=MUTED, bg=BG, pady=30).pack(anchor="w")

    def _import(self) -> None:
        path = filedialog.askopenfilename(title="Import a local video",
                                          filetypes=[("Video files", "*.mp4 *.mov *.mkv *.webm *.m4v")])
        if path:
            self.source.set(path)
            self.status.set("Local video selected. Click Generate Clips.")

    def _start(self) -> None:
        if self.busy:
            return
        raw = self.source.get().strip()
        if not raw:
            messagebox.showerror("Video needed", "Paste a YouTube URL or import a local video.")
            return
        try:
            if raw.lower().startswith(("http://", "https://")):
                validate_youtube_url(raw)
            elif not Path(raw).is_file():
                raise ValueError("Choose an existing local video file")
        except (ValueError, OSError) as exc:
            messagebox.showerror("Invalid input", str(exc))
            return
        self.busy = True
        self.generate.configure(state="disabled")
        self.progress.set(0)
        self.status.set("Starting...")
        for child in self.list_frame.winfo_children():
            child.destroy()
        self.images.clear()

        def worker() -> None:
            try:
                result = process(raw, OUTPUT, lambda label, value: self.events.put(("progress", label, value)))
                self.events.put(("done", str(result)))
            except Exception as exc:
                self.events.put(("error", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _poll(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == "progress":
                    self.status.set(event[1])
                    self.progress.set(max(0, min(1, float(event[2]))))
                elif event[0] == "done":
                    self.busy = False
                    self.generate.configure(state="normal")
                    self.current_job = Path(event[1])
                    self._display(self.current_job)
                elif event[0] == "error":
                    self.busy = False
                    self.generate.configure(state="normal")
                    self.status.set("Processing stopped. " + event[1])
                    messagebox.showerror("AUTOCLIP AI", event[1] + "\n\nYou can import a local video if YouTube retrieval is unavailable.")
                    self._empty()
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _display(self, folder: Path) -> None:
        try:
            payload = json.loads((folder / "clips.json").read_text(encoding="utf-8"))
            clips = payload["clips"]
            if not isinstance(clips, list):
                raise ValueError("Invalid clip manifest")
        except (OSError, ValueError, KeyError) as exc:
            messagebox.showerror("Results error", f"Could not read clip results: {exc}")
            return
        self.status.set(f"Finished {len(clips)} clips. Selection: {payload.get('selection_mode', 'unknown')}.")
        for row in clips:
            card = tk.Frame(self.list_frame, bg=PANEL, padx=14, pady=12)
            card.pack(fill="x", pady=(0, 10))
            thumb = Path(str(row.get("thumbnail", "")))
            try:
                image = tk.PhotoImage(file=str(thumb))
                image = image.subsample(max(1, image.width() // 128), max(1, image.height() // 225))
                self.images.append(image)
                tk.Label(card, image=image, bg=PANEL).pack(side="left", padx=(0, 16))
            except tk.TclError:
                pass
            details = tk.Frame(card, bg=PANEL)
            details.pack(side="left", fill="both", expand=True)
            tk.Label(details, text=f"#{row['rank']}  {row['title']}", font=("Segoe UI", 12, "bold"),
                     fg=TEXT, bg=PANEL, anchor="w").pack(fill="x")
            tk.Label(details, text=f"{row['duration']} sec  •  Score {row['score']}/100  •  {row.get('framing', 'center')} framing",
                     font=("Segoe UI", 9), fg=ACCENT, bg=PANEL, anchor="w").pack(fill="x", pady=(4, 6))
            tk.Label(details, text=row["social_caption"].split("\n")[0], font=("Segoe UI", 9),
                     fg=MUTED, bg=PANEL, anchor="w", wraplength=500).pack(fill="x")
            buttons = tk.Frame(details, bg=PANEL)
            buttons.pack(anchor="w", pady=(9, 0))
            video = Path(row["file"])
            ttk.Button(buttons, text="Play Preview", style="Secondary.TButton",
                       command=lambda p=video: os.startfile(p)).pack(side="left")
            ttk.Button(buttons, text="Save Clip", style="Secondary.TButton",
                       command=lambda p=video: self._save_clip(p)).pack(side="left", padx=7)
            ttk.Button(buttons, text="Copy Caption", style="Secondary.TButton",
                       command=lambda c=row["social_caption"]: self._copy(c)).pack(side="left")

    def _copy(self, value: str) -> None:
        self.clipboard_clear()
        self.clipboard_append(value)
        self.status.set("Suggested caption copied.")

    def _save_clip(self, source: Path) -> None:
        if not source.is_file():
            messagebox.showerror("Missing clip", "This clip is no longer available.")
            return
        destination = filedialog.asksaveasfilename(initialfile=source.name, defaultextension=".mp4",
                                                   filetypes=[("MP4 video", "*.mp4")])
        if destination:
            shutil.copy2(source, destination)
            self.status.set(f"Saved {Path(destination).name}")

    def _export_all(self) -> None:
        if self.current_job is None or not (self.current_job / "clips.json").is_file():
            messagebox.showinfo("No clips yet", "Generate clips before exporting.")
            return
        destination = filedialog.askdirectory(title="Export all finished clips")
        if not destination:
            return
        target = Path(destination).resolve()
        if target == self.current_job.resolve():
            messagebox.showinfo("Already here", "The clips are already in this folder.")
            return
        payload = json.loads((self.current_job / "clips.json").read_text(encoding="utf-8"))
        for row in payload["clips"]:
            source = Path(row["file"])
            if source.is_file():
                shutil.copy2(source, target / source.name)
        shutil.copy2(self.current_job / "social_captions.txt", target / "social_captions.txt")
        self.status.set(f"Exported clips to {target}")

    def _open_output(self) -> None:
        folder = self.current_job or OUTPUT
        folder.mkdir(parents=True, exist_ok=True)
        os.startfile(folder)


if __name__ == "__main__":
    AutoClipApp().mainloop()
