"""Build an ATS-friendly single-column PDF from the analysed CV, plus a short score report PDF.

The fixed CV only *cleans and restructures* what is already in your resume. It never invents
content: no keywords are added for you.
"""
from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import registerFontFamily
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import HRFlowable, KeepTogether, Paragraph, SimpleDocTemplate, Spacer

from . import lexicon as L
from .layout import Block, Layout, Run, is_turkish, nice_case, read_layout
from .tailor import apply_tailoring
from .analyzer import (DATE_RANGE_RE, EMAIL_RE, EMOJI_RE, PHONE_RE, RESULT_RE, URL_RE, Analysis,
                       _is_bullet, _strip_bullet, split_sections, suggestions)

# --------------------------------------------------------------------------- fonts

_FONT_CANDIDATES = [
    # (regular, bold)
    ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
    ("C:/Windows/Fonts/calibri.ttf", "C:/Windows/Fonts/calibrib.ttf"),
    ("/Library/Fonts/Arial.ttf", "/Library/Fonts/Arial Bold.ttf"),
    ("/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ("/usr/share/fonts/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"),
    ("/usr/share/fonts/TTF/DejaVuSans.ttf", "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf"),
    ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
     "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
]
_FONT_CACHE: tuple[str, str, bool] | None = None


def _fonts() -> tuple[str, str, bool]:
    """Return (regular, bold, unicode_ok). Falls back to Helvetica with transliteration."""
    global _FONT_CACHE
    if _FONT_CACHE:
        return _FONT_CACHE
    for reg, bold in _FONT_CANDIDATES:
        if os.path.exists(reg) and os.path.exists(bold):
            try:
                pdfmetrics.registerFont(TTFont("ATS-Regular", reg))
                pdfmetrics.registerFont(TTFont("ATS-Bold", bold))
                _FONT_CACHE = ("ATS-Regular", "ATS-Bold", True)
                return _FONT_CACHE
            except Exception:
                continue
    _FONT_CACHE = ("Helvetica", "Helvetica-Bold", False)
    return _FONT_CACHE


_TRANSLIT = str.maketrans({"ı": "i", "İ": "I", "ş": "s", "Ş": "S", "ğ": "g", "Ğ": "G", "ç": "c", "Ç": "C",
                           "ö": "o", "Ö": "O", "ü": "u", "Ü": "U", "’": "'", "‘": "'", "“": '"', "”": '"',
                           "–": "-", "—": "-", "…": "..."})


def _prep(text: str, unicode_ok: bool) -> str:
    text = escape(text)
    return text if unicode_ok else text.translate(_TRANSLIT).encode("latin-1", "ignore").decode("latin-1")


# --------------------------------------------------------------------------- cleaning

_DECOR = set(L.SYMBOL_CHARS) - set("•·-")
_BAR_TAIL = re.compile(rf"\s*[{re.escape(''.join(_DECOR))}*]{{2,}}\s*$")
_PCT_TAIL = re.compile(r"\s*[-:–]?\s*\b\d{2,3}\s*%\s*$|\s*\(\s*\d\s*/\s*\d{1,2}\s*\)\s*$")
_PUA = re.compile("[\ue000-\uf8ff]")
_CONTACT_PREFIX = re.compile(r"^\s*(?:e-?mail|mail|phone|tel|telefon|gsm|linkedin|github|web|address|adres)\s*[:\-]\s*", re.I)


def clean_line(line: str) -> str:
    line = _PUA.sub("", line)
    line = EMOJI_RE.sub("", line)
    line = _BAR_TAIL.sub("", line)
    if len(line.split()) <= 5 and not RESULT_RE.search(line):   # "Python 80%" is a skill bar; "cut costs by 40%" is a result
        line = _PCT_TAIL.sub("", line)
    line = "".join(ch for ch in line if ch not in _DECOR)
    line = line.replace("\u00a0", " ")
    return re.sub(r"\s{2,}", " ", line).strip(" \t|")


def _clean_runs(block: Block) -> bool:
    """Remove ATS-hostile decoration (icons, stars, skill bars) from a block. False = block is now empty."""
    for r in block.runs:
        t = _PUA.sub("", r.text)
        t = EMOJI_RE.sub("", t)
        t = "".join(ch for ch in t if ch not in _DECOR).replace("\u00a0", " ")
        r.text = re.sub(r"[ \t]{2,}", " ", t)
    runs = [r for r in block.runs if r.text]
    if not runs:
        return False
    runs[-1].text = _BAR_TAIL.sub("", runs[-1].text)
    if len(block.text.split()) <= 5 and not RESULT_RE.search(block.text):
        runs[-1].text = _PCT_TAIL.sub("", runs[-1].text)
    runs[0].text = runs[0].text.lstrip(" |")
    runs[-1].text = runs[-1].text.rstrip(" |")
    block.runs = [r for r in runs if r.text]
    return bool(block.runs) and bool(block.text.strip())


# --------------------------------------------------------------------------- font families (regular, bold, italic, bold-italic)

_WIN, _MAC, _LIN = "C:/Windows/Fonts/", "/System/Library/Fonts/Supplemental/", "/usr/share/fonts/truetype/"
_FAMILIES = {
    "sans": [
        tuple(_WIN + n for n in ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf")),
        tuple(_MAC + n for n in ("Arial.ttf", "Arial Bold.ttf", "Arial Italic.ttf", "Arial Bold Italic.ttf")),
        tuple("/Library/Fonts/" + n for n in ("Arial.ttf", "Arial Bold.ttf", "Arial Italic.ttf", "Arial Bold Italic.ttf")),
        tuple(_LIN + "liberation/LiberationSans-" + n for n in ("Regular.ttf", "Bold.ttf", "Italic.ttf", "BoldItalic.ttf")),
        tuple(_LIN + "dejavu/DejaVuSans" + n for n in (".ttf", "-Bold.ttf", "-Oblique.ttf", "-BoldOblique.ttf")),
        tuple("/usr/share/fonts/dejavu/DejaVuSans" + n for n in (".ttf", "-Bold.ttf", "-Oblique.ttf", "-BoldOblique.ttf")),
        tuple("/usr/share/fonts/TTF/DejaVuSans" + n for n in (".ttf", "-Bold.ttf", "-Oblique.ttf", "-BoldOblique.ttf")),
    ],
    "serif": [
        tuple(_WIN + n for n in ("times.ttf", "timesbd.ttf", "timesi.ttf", "timesbi.ttf")),
        tuple(_MAC + n for n in ("Times New Roman.ttf", "Times New Roman Bold.ttf", "Times New Roman Italic.ttf",
                                 "Times New Roman Bold Italic.ttf")),
        tuple(_LIN + "liberation/LiberationSerif-" + n for n in ("Regular.ttf", "Bold.ttf", "Italic.ttf", "BoldItalic.ttf")),
        tuple(_LIN + "dejavu/DejaVuSerif" + n for n in (".ttf", "-Bold.ttf", "-Italic.ttf", "-BoldItalic.ttf")),
    ],
}
_FAM_CACHE: dict = {}


def _family(serif: bool) -> tuple[str, bool]:
    """Register a regular/bold/italic family and return (family font name, unicode_ok).

    `<b>` and `<i>` markup works because the family is registered with reportlab."""
    key = "serif" if serif else "sans"
    if key in _FAM_CACHE:
        return _FAM_CACHE[key]
    for kind in (key, "sans"):
        for paths in _FAMILIES[kind]:
            if not all(os.path.exists(x) for x in paths):
                continue
            name = f"ATS-{kind}"
            try:
                for suffix, path in zip(("", "-B", "-I", "-BI"), paths):
                    pdfmetrics.registerFont(TTFont(name + suffix, path))
                registerFontFamily(name, normal=name, bold=name + "-B", italic=name + "-I", boldItalic=name + "-BI")
            except Exception:
                continue
            _FAM_CACHE[key] = (name, True)
            return _FAM_CACHE[key]
    _FAM_CACHE[key] = ("Times-Roman" if serif else "Helvetica", False)
    return _FAM_CACHE[key]


def _markup(runs, uni: bool) -> str:
    out = []
    for r in runs:
        t = _prep(r.text, uni)
        if not t:
            continue
        if r.italic:
            t = f"<i>{t}</i>"
        if r.bold:
            t = f"<b>{t}</b>"
        if r.color:
            t = f'<font color="{r.color}">{t}</font>'
        out.append(t)
    return "".join(out)


# --------------------------------------------------------------------------- CV PDF


@dataclass
class BuildResult:
    path: str
    faithful: bool                  # True = original look kept; False = simple clean layout
    notes: list = field(default_factory=list)   # what changed / why (shown to the user)
    reflowed: bool = False          # True = several columns were merged into one reading-order column


def _simple_layout(analysis: Analysis) -> Layout:
    """Plain single-column layout, used when the original look cannot be read safely."""
    header, sections = analysis.header_lines, analysis.section_lines
    if not sections and not header:
        header, sections = split_sections(analysis.extracted.text)
    blocks: list[Block] = []
    head = [h for h in (clean_line(h) for h in header) if h]
    if head:
        blocks.append(Block([Run(head[0], bold=True)], size=19, leading=23))
        bits = [_CONTACT_PREFIX.sub("", h) for h in head[1:]]
        if bits:
            blocks.append(Block([Run("  |  ".join(bits))], size=9.2, leading=12, space_before=2))
    for key, title, lines in sections:
        blocks.append(Block([Run(L.SECTION_TITLES.get(key, title.title()).upper(), bold=True)], size=11, leading=14,
                            space_before=10, rule_after=0.6, heading=True, section=key))
        for raw in lines:
            ln = clean_line(raw)
            if not ln:
                continue
            if _is_bullet(raw) or _is_bullet(ln):
                blocks.append(Block([Run(_strip_bullet(ln))], size=10, leading=13.2, space_before=1, bullet=True,
                                    bullet_indent=2, left_indent=12, section=key))
            elif key in ("experience", "education", "projects") and DATE_RANGE_RE.search(ln) and len(ln) <= 110:
                blocks.append(Block([Run(ln, bold=True)], size=10, leading=13.2, space_before=4, section=key))
            else:
                blocks.append(Block([Run(ln)], size=10, leading=13.2, section=key))
    mm18, mm15 = 18 * mm, 15 * mm
    return Layout(blocks, A4[0], A4[1], (mm18, mm15, mm18, mm15))


def _render(lay: Layout, out_path: str) -> int:
    """Draw the layout to a PDF and return the number of pages."""
    fam, uni = _family(lay.serif)
    story: list = []
    for b in lay.blocks:
        markup = _markup(b.runs, uni)
        if not markup.strip():
            continue
        st = ParagraphStyle("p", fontName=fam, fontSize=b.size, leading=b.leading,
                            alignment={"center": TA_CENTER, "right": TA_RIGHT}.get(b.align, TA_LEFT),
                            spaceBefore=b.space_before, leftIndent=b.left_indent, bulletIndent=b.bullet_indent,
                            bulletFontName=fam, bulletFontSize=b.size, textColor=colors.black)
        para = Paragraph(markup, st, bulletText="•") if b.bullet else Paragraph(markup, st)
        if b.rule_after:
            rule = HRFlowable(width="100%", thickness=b.rule_after, color=colors.HexColor(b.rule_color),
                              spaceBefore=1, spaceAfter=2)
            item = KeepTogether([para, rule])
            item.keepWithNext = 1 if b.heading else 0
            story.append(item)
        else:
            if b.heading:
                para.keepWithNext = 1
            story.append(para)
    title = lay.blocks[0].text.strip() if lay.blocks else "Resume"
    pad = 6  # reportlab frames add 6pt padding on every side
    left, top, right, bottom = lay.margins
    doc = SimpleDocTemplate(out_path, pagesize=(lay.page_w, lay.page_h),
                            leftMargin=max(0.0, left - pad), rightMargin=max(0.0, right - pad),
                            topMargin=max(0.0, top - pad), bottomMargin=max(0.0, bottom - pad),
                            title=_prep(title, False)[:80] or "Resume", author="")
    doc.build(story or [Paragraph("No readable content was found in the CV.", ParagraphStyle("e", fontName=fam))])
    return int(getattr(doc, "page", 1) or 1)


def _fit_pages(lay: Layout, out_path: str, target: int) -> None:
    """Render; if the result is longer than the original, tighten spacing step by step until it fits."""
    import copy
    pages = _render(lay, out_path)
    if pages <= max(1, target):
        return
    original = copy.deepcopy(lay.blocks)
    for space, shrink, lead in ((0.7, 1.0, 1.0), (0.45, 0.97, 0.95), (0.25, 0.94, 0.9), (0.0, 0.92, 0.86)):
        lay.blocks = copy.deepcopy(original)
        for b in lay.blocks:
            b.space_before *= space
            if b.size <= 10.5:
                b.size = round(b.size * shrink, 2)
            b.leading = max(b.size * 1.12, b.leading * lead)
        pages = _render(lay, out_path)
        if pages <= max(1, target):
            return


_LANG_SKILL = re.compile(r"^(reading|speaking|listening|writing|spoken|written|okuma|konuşma|konusma|dinleme|yazma)"
                         r"\s*[-–:]\s*(.+)$", re.I)
_OPEN_DATE = re.compile(r"((?:19|20)\d{2})\s*[-–—]\s*$")
_NOW_WORD = re.compile(r"([-–—]\s*)(?:now|current|currently|ongoing|present day|till date|to date|halen|devam ediyor)\s*$", re.I)


def _collapse_languages(blocks: list, turkish: bool) -> tuple[list, bool]:
    """'English' + 'Reading - Intermediate' + 'Speaking - Intermediate'... -> 'English - Intermediate'."""
    out: list = []
    cur: dict | None = None
    in_lang = False
    changed = False

    def flush():
        nonlocal cur, changed
        if not cur:
            return
        b, name, levels = cur["b"], cur["name"], cur["levels"]
        if levels:
            same = {lv.lower() for _, lv in levels}
            detail = levels[0][1] if len(same) == 1 else ", ".join(f"{sk}: {lv}" for sk, lv in levels)
            out.append(Block([Run(name, bold=True), Run(" - " + detail)], size=b.size, leading=b.leading,
                             space_before=b.space_before, section=b.section))
            changed = True
        else:
            out.append(b)
        cur = None

    for b in blocks:
        if b.heading:
            flush()
            in_lang = b.section == "languages"
            out.append(b)
            continue
        if not in_lang:
            out.append(b)
            continue
        t = b.text.strip()
        m = _LANG_SKILL.match(t)
        if m and cur is not None:
            cur["levels"].append((m.group(1).title(), m.group(2).strip()))
        elif not m and len(t.split()) <= 3 and not re.search(r"[\d\-–:,()]", t):
            flush()
            cur = {"b": b, "name": nice_case(t, turkish), "levels": []}
        else:
            flush()
            out.append(b)
    flush()
    return out, changed


def _is_project_line(b: Block) -> bool:
    """'Saybeni, numerology app.'  ->  bold name, then a short plain description, no dates."""
    if b.heading or len(b.runs) < 2 or not b.runs[0].bold or b.runs[1].bold:
        return False
    t = b.text.strip()
    return (len(t.split()) <= 16 and not re.search(r"(?:19|20)\d{2}", t)
            and b.runs[1].text.lstrip().startswith((",", "-", "–", ":", "(")) and len(b.runs[0].text.split()) <= 4)


def _move_projects(lay: Layout, turkish: bool, notes: list) -> None:
    """Project lines that sit under Experience (e.g. 'Saybeni, numerology app') move under Projects."""
    import copy
    blocks = lay.blocks
    moved_idx: set[int] = set()
    i = 0
    while i < len(blocks):
        b = blocks[i]
        if b.heading or b.section not in ("experience", "internships") or not _is_project_line(b):
            i += 1
            continue
        j = i
        while j < len(blocks) and not blocks[j].heading and blocks[j].section == b.section and _is_project_line(blocks[j]):
            j += 1
        prev = blocks[i - 1] if i else None
        intro = prev is not None and not prev.heading and prev.text.rstrip().endswith((";", ":"))
        if j - i >= 2 or intro:
            moved_idx.update(range(i, j))
            if intro:
                prev.runs[-1].text = prev.runs[-1].text.rstrip().rstrip(";:").rstrip() + (
                    " (bkz. Projeler)." if turkish else " (see Projects).")
        i = j
    if not moved_idx:
        return
    moved = [blocks[k] for k in sorted(moved_idx)]
    rest = [bl for k, bl in enumerate(blocks) if k not in moved_idx]
    for m in moved:
        if not m.bullet:
            m.bullet, m.bullet_indent, m.left_indent = True, 2.0, 12.0
        m.section = "projects"
        m.space_before = min(m.space_before, 3.0)
    heads = [k for k, bl in enumerate(rest) if bl.heading and bl.section == "projects"]
    if heads:
        end = next((k for k in range(heads[0] + 1, len(rest)) if rest[k].heading), len(rest))
        rest[end:end] = moved
    else:
        proto = next((bl for bl in rest if bl.heading), None)
        if proto is None:
            return
        head = copy.deepcopy(proto)
        head.runs = [Run("Projeler" if turkish else "Projects", bold=any(r.bold for r in proto.runs))]
        head.runs[0].color = proto.runs[0].color
        head.section = "projects"
        last_exp = max((k for k, bl in enumerate(rest) if bl.heading and bl.section in ("experience", "internships")),
                       default=None)
        pos = len(rest)
        if last_exp is not None:
            pos = next((k for k in range(last_exp + 1, len(rest)) if rest[k].heading), len(rest))
        rest[pos:pos] = [head] + moved
    lay.blocks = rest
    notes.append(f"Moved {len(moved)} project line(s) from Experience to Projects.")


def _polish(lay: Layout, text: str, notes: list) -> None:
    """Small ATS clean-ups that apply to any layout."""
    turkish = is_turkish(text)
    present = "Devam Ediyor" if turkish else "Present"
    fixed_dates = 0
    for b in lay.blocks:
        for r in b.runs:
            if not turkish and "İ" in r.text:
                r.text = r.text.replace("İ", "I")       # English has no dotted capital I
            r.text = _NOW_WORD.sub(lambda m: m.group(1) + present, r.text)
        if not b.heading and b.runs and _OPEN_DATE.search(b.text.rstrip()):
            b.runs[-1].text = re.sub(r"\s*[-–—]\s*$", " - " + present, b.runs[-1].text.rstrip())
            fixed_dates += 1
    if fixed_dates:
        notes.append(f"Open-ended date ranges now end with '{present}' instead of a dangling dash ({fixed_dates}).")
    _move_projects(lay, turkish, notes)
    lay.blocks, changed = _collapse_languages(lay.blocks, turkish)
    if changed:
        notes.append("Language levels were merged into one short line per language.")


def _why_not_faithful(ex) -> str:
    if ex.kind not in ("pdf", "docx"):
        return ""
    if ex.tables:
        return "it uses tables"
    if ex.textboxes:
        return "it uses text boxes"
    if ex.kind == "docx" and ex.header_footer_text.strip():
        return "some text sits in the Word header or footer"
    return ""


def build_cv(analysis: Analysis, out_path: str, tailor=None) -> BuildResult:
    """Write the fixed CV.

    By default it keeps your own layout (fonts, bold, centred header, spacing, rules, bullets) and only
    removes ATS blockers. With ``tailor`` (a ``tailor.TailorRequest``) it also adjusts wording for one job."""
    ex = analysis.extracted
    notes: list[str] = []
    lay, reason = None, _why_not_faithful(ex)
    if ex.kind in ("pdf", "docx") and not reason:
        lay = read_layout(ex.path, ex.kind)
        if lay is not None:
            total = len(ex.text.split())
            for b in list(lay.blocks):
                if not _clean_runs(b):
                    lay.blocks.remove(b)
            if total and sum(len(b.text.split()) for b in lay.blocks) < 0.85 * total:
                lay, reason = None, "part of the text could not be placed safely"
        else:
            reason = "its layout could not be read"
    reflowed = bool(lay is not None and getattr(lay, "reflowed", False))
    faithful = lay is not None and not reflowed
    if reflowed:
        notes.append("Your two-column design was merged into one clean column in reading order "
                     "(name, contact, profile, experience, projects, education, skills, languages). "
                     "ATS software reads columns line by line and mixes them up. The photo and decorative shapes were left out.")
    elif lay is None:
        if ex.multi_column and not reason:
            reason = "its columns could not be separated safely"
        lay = _simple_layout(analysis)
        if reason:
            notes.append(f"Kept the content but used a simple single-column layout, because {reason}.")
    _polish(lay, ex.text, notes)
    if tailor is not None:
        notes.extend(apply_tailoring(lay.blocks, tailor))
    _fit_pages(lay, out_path, ex.pages if ex.kind == "pdf" else 99)
    return BuildResult(out_path, faithful, notes, reflowed)


def build_fixed_cv(analysis: Analysis, out_path: str, tailor=None) -> str:
    """Convenience wrapper that returns the output path."""
    return build_cv(analysis, out_path, tailor).path


# --------------------------------------------------------------------------- report PDF


def build_report(analysis: Analysis, out_path: str) -> str:
    reg, bold, uni = _fonts()
    base = ParagraphStyle("b", fontName=reg, fontSize=9.5, leading=12.5)
    h1 = ParagraphStyle("h1", parent=base, fontName=bold, fontSize=18, leading=22, spaceAfter=4)
    h2 = ParagraphStyle("h2", parent=base, fontName=bold, fontSize=12, leading=15, spaceBefore=10, spaceAfter=3)
    li = ParagraphStyle("li", parent=base, leftIndent=12, bulletIndent=2, spaceBefore=1, bulletFontName=reg)

    def P(t, st=base):
        return Paragraph(_prep(t, uni), st)

    def LI(t, mark="•"):
        return Paragraph(_prep(t, uni), li, bulletText=mark)

    s = [P("ATS Scout - Resume Report", h1), P(f"File: {os.path.basename(analysis.extracted.path)}")]
    s.append(P(f"Overall ATS score: {analysis.ats_score}/100 - {analysis.verdict}", h2))
    if analysis.match:
        m = analysis.match
        s.append(P(f"Job match: {m.score}/100 - {m.verdict}"))
        if analysis.combined_score is not None:
            s.append(P(f"Estimated overall fit (ATS 35% + match 65%): {analysis.combined_score}/100"))
    s.append(P("Section scores", h2))
    for sec in analysis.sections:
        s.append(LI(f"{sec.name}: {sec.score}/100" + ("" if sec.found else "  (section not found)")))
        for c in sec.checks:
            if c.label and not c.ok:
                s.append(Paragraph(_prep("x  " + c.label + (f" -> {c.advice}" if c.advice else ""), uni),
                                   ParagraphStyle("sub", parent=base, leftIndent=24, textColor=colors.HexColor("#8a1c1c"))))
    if analysis.issues:
        s.append(P("Warnings", h2))
        for i in analysis.issues:
            s.append(LI(f"[{i.severity.upper()}] {i.title}: {i.detail} Fix: {i.fix}"))
    if analysis.match:
        s.append(P("Keywords", h2))
        s.append(P("Found: " + (", ".join(f"{k.keyword} ({k.count})" for k in analysis.match.matched) or "none")))
        s.append(P("Missing: " + (", ".join(k.keyword for k in analysis.match.missing) or "none")))
        if analysis.match.stuffed:
            s.append(P("Possible keyword stuffing: " + ", ".join(k.keyword for k in analysis.match.stuffed)))
    s.append(P("Top fixes", h2))
    for t in suggestions(analysis, 10):
        s.append(LI(t))
    s.append(Spacer(1, 10))
    s.append(P("Scores are estimates from open, rule-based checks. Real ATS software differs, so treat this as guidance, "
               "not a guarantee."))
    SimpleDocTemplate(out_path, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                      topMargin=16 * mm, bottomMargin=16 * mm, title="ATS Scout Report").build(s)
    return out_path
