"""ATS Scout desktop app (customtkinter). Everything runs locally: no accounts, no API keys, no network."""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import traceback
from pathlib import Path
from tkinter import TclError, filedialog, messagebox

import customtkinter as ctk

from . import __version__
from .analyzer import Analysis, analyze, suggestions
from .extract import extract
from .pdf_builder import build_cv, build_report
from .tailor import TailorRequest, suggestable_keywords

ctk.set_appearance_mode("dark")

ASSETS = Path(__file__).resolve().parent.parent / "assets"


def set_app_icon(win) -> None:
    """Show the ATS Scout logo in the window / Dock / taskbar. Never fails the app if the file is missing."""
    try:
        import tkinter as tk
        png = ASSETS / "logo_256.png"
        if png.exists():
            win._logo_img = tk.PhotoImage(file=str(png))  # keep a reference
            win.iconphoto(True, win._logo_img)
        ico = ASSETS / "logo.ico"
        if sys.platform.startswith("win") and ico.exists():
            win.iconbitmap(str(ico))
    except Exception:
        pass

# --- palette: navy base, orange + red accents -------------------------------------------------
BG, SIDEBAR, PANEL = "#0A1226", "#0F1A36", "#121E3F"
CARD, LINE = "#1A2850", "#2B3C6B"
ORANGE, ORANGE_HOVER = "#FF7A1A", "#E96A0C"
RED, RED_HOVER = "#EF4B4B", "#D63C3C"
GREEN, AMBER, BLUE = "#2DBE8D", "#FFB020", "#5B8DEF"
TEXT, SOFT, MUTED = "#F4F6FB", "#C5CDE3", "#8592B5"
SEV_COLOR = {"critical": RED, "warning": ORANGE, "info": BLUE}
LOCKED_BG, LOCKED_LINE, LOCKED_TEXT = "#23262D", "#30343D", "#6B7180"
TAB_NAMES = ("Overview", "Sections", "Warnings", "Keywords")

FAMILY = "Helvetica"


def F(size: int, bold: bool = False) -> tuple:
    return (FAMILY, size, "bold") if bold else (FAMILY, size)


def pick_family(root) -> str:
    """Best readable UI font that exists on this computer (no font files to install)."""
    from tkinter import font as tkfont
    have = set(tkfont.families(root))
    for name in ("Avenir Next", "Segoe UI Variable Display", "Segoe UI", "Inter", "Helvetica Neue",
                 "Noto Sans", "DejaVu Sans", "Helvetica"):
        if name in have:
            return name
    return "Helvetica"


def score_color(v: int) -> str:
    return GREEN if v >= 80 else AMBER if v >= 60 else RED


def open_path(path: str) -> None:
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception:
        pass


class Gauge(ctk.CTkCanvas):
    def __init__(self, master, title: str, size: int = 176):
        super().__init__(master, width=size, height=size + 30, highlightthickness=0, bg=PANEL)
        self.size, self.title = size, title
        self.draw(None)

    def draw(self, value: int | None):
        self.delete("all")
        s, pad, w = self.size, 14, 14
        box = (pad, pad, s - pad, s - pad)
        self.create_arc(*box, start=0, extent=359.9, style="arc", width=w, outline=LINE)
        if value is not None:
            self.create_arc(*box, start=90, extent=-3.6 * max(1, value), style="arc", width=w,
                            outline=score_color(value))
        text = "-" if value is None else str(value)
        self.create_text(s / 2, s / 2 - 4, text=text, fill=TEXT, font=F(38, True))
        self.create_text(s / 2, s / 2 + 30, text="/ 100", fill=MUTED, font=F(11))
        self.create_text(s / 2, s + 16, text=self.title, fill=SOFT, font=F(13, True))


class ScrollPage(ctk.CTkScrollableFrame):
    """Scrollable page with its own mouse-wheel / trackpad handling.

    customtkinter's built-in wheel binding misses some Tk versions. In particular Tk 9 on macOS
    (Homebrew Python 3.14) reports trackpad gestures as <TouchpadScroll>, which customtkinter does
    not know, so only the scrollbar worked. This class handles wheel, trackpad and Linux buttons.
    """

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._last_serial = -1
        self._parent_canvas.configure(yscrollincrement=1)  # one "unit" = one pixel: smooth scrolling
        self.bind_all("<MouseWheel>", self._on_wheel, add="+")
        for seq, fn in (("<TouchpadScroll>", self._on_touchpad),
                        ("<Button-4>", self._on_button), ("<Button-5>", self._on_button)):
            try:
                self.bind_all(seq, fn, add="+")
            except TclError:  # this Tk does not know the event (e.g. TouchpadScroll on Tk 8.6)
                pass

    def _pointer_inside(self) -> bool:
        """True when the mouse pointer is over this page (plain screen-coordinate check)."""
        try:
            x, y = self.winfo_pointerxy()
            f = getattr(self, "_parent_frame", self)
            left, top = f.winfo_rootx(), f.winfo_rooty()
            return left <= x < left + f.winfo_width() and top <= y < top + f.winfo_height()
        except Exception:
            return False

    def _scroll_px(self, px: float):
        if px and self.winfo_ismapped() and self._pointer_inside():
            self._parent_canvas.yview_scroll(int(round(px)), "units")

    def _on_wheel(self, event):
        if event.serial == self._last_serial:  # customtkinter calls this too; handle each event once
            return
        self._last_serial = event.serial
        d = event.delta
        if not d:
            return
        # Windows: multiples of 120 per notch. macOS: small numbers that grow with speed.
        self._scroll_px(-d / 120 * 70 if abs(d) >= 120 else -d * 7)

    _mouse_wheel_all = _on_wheel  # replaces customtkinter's handler (it is bound by name at init)

    def _on_touchpad(self, event):
        if event.serial == self._last_serial:
            return
        self._last_serial = event.serial
        try:
            vals = self.tk.splitlist(self.tk.call("tk::PreciseScrollDeltas", event.delta))
            dy = float(vals[1])
        except Exception:
            return
        self._scroll_px(-dy)

    def _on_button(self, event):
        self._scroll_px(-60 if event.num == 4 else 60)


class KeywordPicker(ctk.CTkToplevel):
    """Asks which of the job's missing keywords the user genuinely has. Nothing is added without a tick."""

    def __init__(self, master, items: list[tuple[str, str]]):
        super().__init__(master)
        self.title("Add skills you really have")
        self.configure(fg_color=PANEL)
        self.geometry("540x660")
        self.minsize(460, 520)
        self.result: list[str] | None = None
        self.transient(master)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        ctk.CTkLabel(self, text="Which of these do you really have?", font=F(20, True), text_color=TEXT,
                     anchor="w").grid(row=0, column=0, padx=24, pady=(22, 4), sticky="w")
        ctk.CTkLabel(self, font=F(13), text_color=SOFT, justify="left", anchor="w", wraplength=480,
                     text="The job posting asks for these, but your CV does not mention them. Tick only the ones that are "
                          "true for you. They are added to your Skills section and mentioned once in your Summary. "
                          "Anything you leave unticked is not added."
                     ).grid(row=1, column=0, padx=24, pady=(0, 10), sticky="w")
        box = ScrollPage(self, fg_color=CARD, corner_radius=14, scrollbar_button_color=LINE,
                         scrollbar_button_hover_color=MUTED)
        box.grid(row=2, column=0, padx=24, sticky="nsew")
        self._vars: list[tuple[str, ctk.BooleanVar]] = []
        for display, _term in items:
            var = ctk.BooleanVar(value=False)
            ctk.CTkCheckBox(box, text=display, variable=var, font=F(14), text_color=TEXT, fg_color=ORANGE,
                            hover_color=ORANGE_HOVER, border_color=MUTED, checkmark_color="#1A0D00"
                            ).pack(anchor="w", padx=14, pady=7)
            self._vars.append((display, var))
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.grid(row=3, column=0, padx=24, pady=18, sticky="ew")
        row.grid_columnconfigure((0, 1), weight=1)
        ctk.CTkButton(row, text="Cancel", height=44, corner_radius=12, font=F(14, True), fg_color="transparent",
                      border_width=1, border_color=LINE, text_color=SOFT, hover_color=CARD,
                      command=self.destroy).grid(row=0, column=0, padx=(0, 8), sticky="ew")
        ctk.CTkButton(row, text="Create tailored CV", height=44, corner_radius=12, font=F(14, True),
                      fg_color=ORANGE, hover_color=ORANGE_HOVER, text_color="#1A0D00",
                      command=self._ok).grid(row=0, column=1, padx=(8, 0), sticky="ew")
        self.after(150, self._focus)

    def _focus(self):
        try:
            self.grab_set()
            self.lift()
        except Exception:
            pass

    def _ok(self):
        self.result = [d for d, v in self._vars if v.get()]
        self.destroy()


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        global FAMILY
        FAMILY = pick_family(self)
        self.title(f"ATS Scout {__version__} - free offline resume checker")
        self.configure(fg_color=BG)
        self.geometry("1240x800")
        self.minsize(1040, 680)
        self.after(250, lambda: set_app_icon(self))  # after customtkinter sets its own default icon
        self.cv_path: str | None = None
        self.analysis: Analysis | None = None
        self.analysis_jd = ""
        self._q: queue.Queue = queue.Queue()

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_sidebar()
        self._build_results()
        self.after(120, self._poll)

    # ------------------------------------------------------------------ layout
    def _build_sidebar(self):
        sb = ctk.CTkFrame(self, width=360, corner_radius=0, fg_color=SIDEBAR)
        sb.grid(row=0, column=0, sticky="nsew")
        sb.grid_propagate(False)
        sb.grid_columnconfigure(0, weight=1)
        sb.grid_rowconfigure(5, weight=1)

        title = ctk.CTkFrame(sb, fg_color="transparent")
        title.grid(row=0, column=0, padx=24, pady=(26, 0), sticky="w")
        ctk.CTkLabel(title, text="ATS ", font=F(30, True), text_color=TEXT).pack(side="left")
        ctk.CTkLabel(title, text="Scout", font=F(30, True), text_color=ORANGE).pack(side="left")
        ctk.CTkLabel(sb, text="Free and offline. Your CV never leaves this computer.", text_color=MUTED,
                     font=F(13), wraplength=300, justify="left").grid(row=1, column=0, padx=24, pady=(2, 20), sticky="w")

        self.btn_open = ctk.CTkButton(sb, text="Choose your CV  (PDF, DOCX, TXT)", height=46, corner_radius=12,
                                      font=F(14, True), fg_color="transparent", border_width=2,
                                      border_color=ORANGE, text_color=ORANGE, hover_color=CARD,
                                      command=self.choose_cv)
        self.btn_open.grid(row=2, column=0, padx=24, sticky="ew")
        self.lbl_file = ctk.CTkLabel(sb, text="No file selected", text_color=MUTED, font=F(13),
                                     wraplength=300, justify="left")
        self.lbl_file.grid(row=3, column=0, padx=24, pady=(8, 18), sticky="w")

        # job description explainer
        card = ctk.CTkFrame(sb, fg_color=CARD, corner_radius=14)
        card.grid(row=4, column=0, padx=24, sticky="ew")
        ctk.CTkLabel(card, text="Applying to a specific job?", font=F(14, True), text_color=ORANGE,
                     anchor="w").pack(anchor="w", padx=16, pady=(14, 2))
        ctk.CTkLabel(card, font=F(12), text_color=SOFT, wraplength=286, justify="left", anchor="w",
                     text="Paste the job posting below. ATS Scout compares your CV with what that company "
                          "asks for, lists the keywords you are missing and estimates your chances.\n\n"
                          "Do it for every application: add the missing skills you truly have, run it again, "
                          "then export a clean, ATS-ready PDF made for that job."
                     ).pack(anchor="w", padx=16, pady=(0, 14))

        box = ctk.CTkFrame(sb, fg_color="transparent")
        box.grid(row=5, column=0, padx=24, pady=(12, 0), sticky="nsew")
        box.grid_columnconfigure(0, weight=1)
        box.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(box, text="Job posting  (optional)", font=F(13, True), text_color=SOFT,
                     anchor="w").grid(row=0, column=0, sticky="ew")
        self.txt_jd = ctk.CTkTextbox(box, wrap="word", font=F(13), fg_color=BG, text_color=TEXT,
                                     border_width=1, border_color=LINE, corner_radius=12, height=90)
        self.txt_jd.grid(row=1, column=0, sticky="nsew", pady=(6, 0))

        self.btn_run = ctk.CTkButton(sb, text="Analyze", height=50, corner_radius=12, font=F(16, True),
                                     fg_color=ORANGE, hover_color=ORANGE_HOVER, text_color="#1A0D00",
                                     command=self.run)
        self.btn_run.grid(row=6, column=0, padx=24, pady=(16, 10), sticky="ew")

        tl = ctk.CTkFrame(sb, fg_color="transparent")
        tl.grid(row=7, column=0, padx=24, sticky="ew")
        self.sw_tailor = ctk.CTkSwitch(tl, text="Write my CV for this job", font=F(13, True), text_color=TEXT,
                                       progress_color=ORANGE, button_color=TEXT, button_hover_color=SOFT,
                                       fg_color=LINE, state="disabled")
        self.sw_tailor.pack(anchor="w")
        self.lbl_tailor = ctk.CTkLabel(tl, text="", font=F(12), text_color=MUTED, wraplength=300, justify="left",
                                       anchor="w")
        self.lbl_tailor.pack(anchor="w", pady=(4, 0))

        self.btn_fix = ctk.CTkButton(sb, text="Export fixed CV (PDF)", state="disabled", height=40,
                                     corner_radius=12, font=F(13, True), fg_color=RED, hover_color=RED_HOVER,
                                     text_color=TEXT, text_color_disabled=MUTED, command=self.export_fixed)
        self.btn_fix.grid(row=8, column=0, padx=24, pady=(12, 4), sticky="ew")
        self.btn_rep = ctk.CTkButton(sb, text="Export score report (PDF)", state="disabled", height=40,
                                     corner_radius=12, font=F(13, True), fg_color="transparent", border_width=1,
                                     border_color=LINE, text_color=SOFT, text_color_disabled=MUTED,
                                     hover_color=CARD, command=self.export_report)
        self.btn_rep.grid(row=9, column=0, padx=24, pady=(4, 22), sticky="ew")
        self._sync_tailor()
        self._sync_export_buttons(False)

    def _sync_export_buttons(self, on: bool):
        self.btn_fix.configure(state="normal" if on else "disabled", fg_color=RED if on else CARD)
        self.btn_rep.configure(state="normal" if on else "disabled", border_color=LINE)

    def _sync_tailor(self):
        has = bool(self.analysis and self.analysis.match) if hasattr(self, "analysis") else False
        if has:
            self.sw_tailor.configure(state="normal")
            self.lbl_tailor.configure(text="Rewords your CV for this posting (matching wording, skills first, overused "
                                           "terms varied). You decide which missing skills get added.")
        else:
            self.sw_tailor.deselect()
            self.sw_tailor.configure(state="disabled")
            self.lbl_tailor.configure(text="Paste a job posting and press Analyze to unlock this.")

    def _build_results(self):
        panel = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=22)
        panel.grid(row=0, column=1, sticky="nsew", padx=(18, 18), pady=18)
        panel.grid_columnconfigure(0, weight=1)
        panel.grid_rowconfigure(1, weight=1)

        bar = ctk.CTkFrame(panel, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="w", padx=24, pady=(22, 12))
        self.tab_btns: dict[str, ctk.CTkButton] = {}
        for i, name in enumerate(TAB_NAMES):
            b = ctk.CTkButton(bar, text=name, width=148, height=42, corner_radius=21, font=F(14, True),
                              command=lambda n=name: self.show_tab(n))
            b.grid(row=0, column=i, padx=(0, 12))
            self.tab_btns[name] = b

        self.pages: dict[str, ScrollPage] = {}
        for name in TAB_NAMES:
            f = ScrollPage(panel, fg_color="transparent", scrollbar_button_color=LINE,
                                       scrollbar_button_hover_color=MUTED)
            f.grid_columnconfigure(0, weight=1)
            self.pages[name] = f
        self.current_tab = "Overview"
        self.tabs_ready = False
        self._welcome()
        self.show_tab("Overview")

    def show_tab(self, name: str):
        if name != "Overview" and not self.tabs_ready:
            return
        self.current_tab = name
        for n, page in self.pages.items():
            if n == name:
                page.grid(row=1, column=0, sticky="nsew", padx=(14, 10), pady=(0, 16))
            else:
                page.grid_remove()
        self._style_tabs()

    def _style_tabs(self):
        for n, b in self.tab_btns.items():
            locked = n != "Overview" and not self.tabs_ready
            if locked:  # flat neutral grey + lock, clearly different from the navy "not selected" pills
                b.configure(text=f"\U0001F512  {n}", state="disabled", fg_color=LOCKED_BG, hover=False,
                            border_width=1, border_color=LOCKED_LINE, text_color_disabled=LOCKED_TEXT)
            elif n == self.current_tab:
                b.configure(text=n, state="normal", fg_color=ORANGE, hover_color=ORANGE_HOVER, hover=True,
                            border_width=0, text_color="#1A0D00")
            else:
                b.configure(text=n, state="normal", fg_color=CARD, hover_color=LINE, hover=True,
                            border_width=0, text_color=SOFT)

    def _clear(self, name: str):
        for w in self.pages[name].winfo_children():
            w.destroy()

    def _welcome(self):
        self._clear("Overview")
        page = self.pages["Overview"]
        ctk.CTkLabel(page, text="Is your CV ready for the robots?", font=F(26, True), text_color=TEXT,
                     anchor="w").pack(anchor="w", padx=24, pady=(36, 6))
        ctk.CTkLabel(page, text="Choose your CV on the left and press Analyze. In a few seconds you get:",
                     font=F(15), text_color=SOFT, anchor="w", wraplength=640, justify="left").pack(anchor="w", padx=24)
        for head, body in (("An ATS score", "plus a score and checklist for every section"),
                           ("Warnings", "photos, tables, columns, stars, skill bars, icons"),
                           ("Job match", "missing keywords and your estimated chances"),
                           ("A fixed PDF", "clean, single column, ready to send")):
            row = ctk.CTkFrame(page, fg_color=CARD, corner_radius=14)
            row.pack(fill="x", padx=24, pady=(12, 0))
            ctk.CTkLabel(row, text=head, font=F(15, True), text_color=ORANGE, anchor="w").pack(side="left", padx=(18, 10), pady=14)
            ctk.CTkLabel(row, text=body, font=F(14), text_color=SOFT, anchor="w").pack(side="left", pady=14)

    # ------------------------------------------------------------------ actions
    def choose_cv(self):
        p = filedialog.askopenfilename(title="Choose your CV",
                                       filetypes=[("Resumes", "*.pdf *.docx *.txt"), ("All files", "*.*")])
        if p:
            self.cv_path = p
            self.lbl_file.configure(text=Path(p).name, text_color=TEXT)

    def run(self):
        if not self.cv_path:
            messagebox.showinfo("ATS Scout", "Please choose your CV file first.")
            return
        jd = self.txt_jd.get("1.0", "end").strip()
        self.btn_run.configure(state="disabled", text="Analyzing...")
        threading.Thread(target=self._work, args=(self.cv_path, jd), daemon=True).start()

    def _work(self, path: str, jd: str):
        try:
            self._q.put(("ok", (analyze(extract(path), jd), jd)))
        except Exception as e:  # show a readable error instead of crashing
            traceback.print_exc()
            self._q.put(("err", f"{type(e).__name__}: {e}"))

    def _poll(self):
        try:
            kind, payload = self._q.get_nowait()
        except queue.Empty:
            self.after(120, self._poll)
            return
        self.btn_run.configure(state="normal", text="Analyze")
        if kind == "err":
            messagebox.showerror("Could not read the file", payload)
        else:
            self.analysis, self.analysis_jd = payload
            self._sync_export_buttons(True)
            self._sync_tailor()
            self.render(self.analysis)
        self.after(120, self._poll)

    def _default_out(self, suffix: str) -> str:
        stem = Path(self.cv_path or "cv").stem
        return f"{stem}_{suffix}.pdf"

    def export_fixed(self):
        if not self.analysis:
            return
        a = self.analysis
        tailor = None
        if self.sw_tailor.get() and a.match:
            items = suggestable_keywords(a.match, self.analysis_jd)
            confirmed: list[str] = []
            if items:
                dlg = KeywordPicker(self, items)
                self.wait_window(dlg)
                if dlg.result is None:      # cancelled
                    return
                confirmed = dlg.result
            tailor = TailorRequest(self.analysis_jd, a.match, confirmed)
        out = filedialog.asksaveasfilename(defaultextension=".pdf", filetypes=[("PDF", "*.pdf")],
                                           initialfile=self._default_out("ats_tailored" if tailor else "ats_fixed"))
        if not out:
            return
        try:
            res = build_cv(a, out, tailor)
        except Exception as e:
            traceback.print_exc()
            messagebox.showerror("Export failed", f"{type(e).__name__}: {e}")
            return
        lines = [f"Saved to:\n{out}"]
        if res.reflowed:
            lines.append("Your multi-column design was rebuilt as one clean column in reading order, "
                         "because ATS software mixes columns up. Photo and decorative shapes were left out.")
        elif res.faithful:
            lines.append("Your own layout was kept: fonts, bold, alignment, spacing and bullets.")
        if tailor:
            try:
                b = analyze(extract(out), self.analysis_jd)
                lines.append(f"ATS score: {a.ats_score} -> {b.ats_score}    Job match: {a.match.score} -> {b.match.score}")
            except Exception:
                pass
        if res.notes:
            lines.append("What changed:\n" + "\n".join(f"  - {n}" for n in res.notes[:10]))
        if a.extracted.multi_column and not res.faithful and not res.reflowed:
            lines.append("Your original CV has several columns, so the text order may be mixed up. "
                         "Please read the new PDF once.")
        lines.append("Only your own content was used. Nothing was added unless you ticked it.")
        messagebox.showinfo("Saved", "\n\n".join(lines))
        open_path(out)

    def export_report(self):
        if not self.analysis:
            return
        out = filedialog.asksaveasfilename(defaultextension=".pdf", initialfile=self._default_out("ats_report"),
                                           filetypes=[("PDF", "*.pdf")])
        if out:
            try:
                build_report(self.analysis, out)
                open_path(out)
            except Exception as e:
                messagebox.showerror("Export failed", str(e))

    # ------------------------------------------------------------------ rendering
    def render(self, a: Analysis):
        self._render_overview(a)
        self._render_sections(a)
        self._render_warnings(a)
        self._render_keywords(a)
        self.tabs_ready = True
        self.show_tab("Overview")

    def _render_overview(self, a: Analysis):
        self._clear("Overview")
        page = self.pages["Overview"]
        row = ctk.CTkFrame(page, fg_color="transparent")
        row.pack(fill="x", pady=(10, 4))
        g1 = Gauge(row, "ATS score")
        g1.pack(side="left", padx=16)
        g1.draw(a.ats_score)
        if a.match:
            g2 = Gauge(row, "Job match")
            g2.pack(side="left", padx=16)
            g2.draw(a.match.score)
            if a.combined_score is not None:
                g3 = Gauge(row, "Overall fit")
                g3.pack(side="left", padx=16)
                g3.draw(a.combined_score)
        ctk.CTkLabel(page, text=a.verdict, font=F(17, True), text_color=TEXT, wraplength=700,
                     justify="left").pack(anchor="w", padx=20, pady=(10, 0))
        if a.match:
            ctk.CTkLabel(page, text=a.match.verdict, font=F(14), wraplength=700, justify="left",
                         text_color=SOFT).pack(anchor="w", padx=20, pady=(2, 0))
        ctk.CTkLabel(page, text=f"{a.word_count} words  |  {a.extracted.pages} page(s)  |  "
                                f"sections found: {', '.join(t for _, t in a.detected_sections) or 'none'}",
                     font=F(12), text_color=MUTED, wraplength=700, justify="left").pack(anchor="w", padx=20, pady=(4, 12))

        ctk.CTkLabel(page, text="Top things to fix", font=F(18, True), text_color=ORANGE).pack(anchor="w", padx=20, pady=(8, 6))
        fixes = suggestions(a, 8)
        if not fixes:
            ctk.CTkLabel(page, text="Nothing important. Nice CV!", font=F(14), text_color=GREEN).pack(anchor="w", padx=24)
        for t in fixes:
            item = ctk.CTkFrame(page, fg_color=CARD, corner_radius=12)
            item.pack(fill="x", padx=16, pady=4)
            ctk.CTkFrame(item, width=4, height=1, fg_color=ORANGE, corner_radius=2).pack(side="left", fill="y", padx=(10, 0), pady=10)
            ctk.CTkLabel(item, text=t, font=F(13), text_color=TEXT, wraplength=640, justify="left",
                         anchor="w").pack(side="left", padx=12, pady=10)
        ctk.CTkLabel(page, text="Scores are estimates from open rules. Real ATS software differs; use this as guidance.",
                     font=F(12), text_color=MUTED, wraplength=700, justify="left").pack(anchor="w", padx=20, pady=(18, 6))

    def _render_sections(self, a: Analysis):
        self._clear("Sections")
        page = self.pages["Sections"]
        for s in a.sections:
            card = ctk.CTkFrame(page, fg_color=CARD, corner_radius=14)
            card.pack(fill="x", padx=12, pady=7)
            card.grid_columnconfigure(1, weight=1)
            title = s.name + ("" if s.found else "  (not found)")
            ctk.CTkLabel(card, text=title, font=F(15, True), text_color=TEXT).grid(row=0, column=0, padx=16, pady=(14, 4), sticky="w")
            bar = ctk.CTkProgressBar(card, progress_color=score_color(s.score), fg_color=LINE, height=10)
            bar.set(s.score / 100)
            bar.grid(row=0, column=1, padx=12, pady=(14, 4), sticky="ew")
            ctk.CTkLabel(card, text=f"{s.score}", font=F(18, True), text_color=score_color(s.score),
                         width=44).grid(row=0, column=2, padx=(0, 16), pady=(14, 4))
            r = 1
            for c in s.checks:
                if not c.label:
                    continue
                mark, col = ("✓", GREEN) if c.ok else ("✗", RED)
                txt = c.label if c.ok else f"{c.label}  -  {c.advice}" if c.advice else c.label
                ctk.CTkLabel(card, text=f"{mark}  {txt}", font=F(13), text_color=SOFT if c.ok else "#FF9C8F",
                             wraplength=620, justify="left", anchor="w").grid(row=r, column=0, columnspan=3, padx=20, pady=2, sticky="w")
                r += 1
            ctk.CTkLabel(card, text="", height=4).grid(row=r, column=0, pady=2)

    def _render_warnings(self, a: Analysis):
        self._clear("Warnings")
        page = self.pages["Warnings"]
        if not a.issues:
            ctk.CTkLabel(page, text="No ATS blockers detected: single column, real text, no images or tables.",
                         text_color=GREEN, font=F(15, True)).pack(pady=40, padx=20, anchor="w")
            return
        for i in a.issues:
            col = SEV_COLOR[i.severity]
            card = ctk.CTkFrame(page, fg_color=CARD, corner_radius=14, border_width=2, border_color=col)
            card.pack(fill="x", padx=12, pady=7)
            ctk.CTkLabel(card, text=f"{i.severity.upper()}  |  {i.title}", font=F(15, True),
                         text_color=col).pack(anchor="w", padx=16, pady=(12, 2))
            ctk.CTkLabel(card, text=i.detail, font=F(13), text_color=TEXT, wraplength=640,
                         justify="left").pack(anchor="w", padx=16)
            ctk.CTkLabel(card, text=f"Fix: {i.fix}", font=F(13), wraplength=640, justify="left",
                         text_color="#FFC48A").pack(anchor="w", padx=16, pady=(4, 12))

    def _render_keywords(self, a: Analysis):
        self._clear("Keywords")
        page = self.pages["Keywords"]
        if not a.match:
            ctk.CTkLabel(page, text="No job posting yet", font=F(20, True), text_color=TEXT).pack(pady=(40, 6), padx=24, anchor="w")
            ctk.CTkLabel(page, text="Paste the job posting in the box on the left and press Analyze again.\n"
                                    "You will see which keywords your CV covers and which ones are missing.",
                         text_color=SOFT, font=F(14), justify="left").pack(padx=24, anchor="w")
            return
        m = a.match
        ctk.CTkLabel(page, text=f"Keyword coverage: {m.score}%", font=F(22, True),
                     text_color=score_color(m.score)).pack(anchor="w", padx=20, pady=(10, 2))
        if m.title_line:
            ok = "matches" if m.title_overlap else "is not visible near the top of"
            ctk.CTkLabel(page, text=f"Job title '{m.title_line}' {ok} your CV header.", font=F(13),
                         text_color=GREEN if m.title_overlap else AMBER, wraplength=700, justify="left").pack(anchor="w", padx=20)
        self._chips(page, "In your CV", [f"{k.keyword}  x{k.count}" for k in m.matched], GREEN)
        self._chips(page, "Missing (add only if you truly have them)", [k.keyword for k in m.missing], RED)
        if m.stuffed:
            self._chips(page, "Possibly overused (looks like keyword stuffing)", [f"{k.keyword}  x{k.count}" for k in m.stuffed], ORANGE)

    def _chips(self, page, title: str, items: list[str], color: str):
        ctk.CTkLabel(page, text=title, font=F(15, True), text_color=TEXT).pack(anchor="w", padx=20, pady=(18, 6))
        if not items:
            ctk.CTkLabel(page, text="none", font=F(13), text_color=MUTED).pack(anchor="w", padx=24)
            return
        wrap = ctk.CTkFrame(page, fg_color="transparent")
        wrap.pack(fill="x", padx=16)
        max_w = 680
        rows: list[list] = [[]]
        cur = 0
        for it in items:
            w = 28 + 8 * len(it)
            if cur + w > max_w and rows[-1]:
                rows.append([])
                cur = 0
            rows[-1].append(it)
            cur += w + 8
        for r in rows:
            line = ctk.CTkFrame(wrap, fg_color="transparent")
            line.pack(anchor="w", pady=3)
            for it in r:
                chip = ctk.CTkFrame(line, fg_color=color, corner_radius=14)
                chip.pack(side="left", padx=4)
                ctk.CTkLabel(chip, text=it, font=F(12, True), text_color="#0A1226" if color != RED else "white").pack(padx=12, pady=4)


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
