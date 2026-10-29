"""Read a CV (PDF or DOCX) as styled paragraph blocks, so the fixed PDF can keep the original look.

A *block* is one paragraph with its own look: bold/italic runs, font size, alignment (left, centre,
right), indent, bullet, spacing before it and an optional rule under it. The fixed-CV builder
re-draws these blocks, so the skeleton of your CV (centred header, bold role lines, rules under
headings, bullets) survives. Wrapped lines are joined back into real paragraphs.

Returns ``None`` when the layout cannot be read safely (multi-column pages, tables, text boxes...).
The caller then falls back to the simple single-column rebuild.
"""
from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field

from .analyzer import heading_key
from .extract import find_gutter
from . import lexicon as L


@dataclass
class Run:
    text: str
    bold: bool = False
    italic: bool = False
    color: str | None = None        # "#rrggbb"; None = black


@dataclass
class Block:
    runs: list
    size: float = 10.0
    leading: float = 12.5
    align: str = "left"             # left | center | right
    space_before: float = 0.0
    left_indent: float = 0.0
    bullet: bool = False
    bullet_indent: float = 0.0
    rule_after: float = 0.0         # line thickness in pt; 0 = no rule
    rule_color: str = "#444444"
    heading: bool = False
    section: str | None = None      # canonical section key this block belongs to

    @property
    def text(self) -> str:
        return "".join(r.text for r in self.runs)


@dataclass
class Layout:
    blocks: list
    page_w: float
    page_h: float
    margins: tuple                  # left, top, right, bottom (pt)
    serif: bool = False
    mono: bool = False
    reflowed: bool = False          # True = columns were merged into one reading-order column


# --------------------------------------------------------------------------- helpers

_BULLET_GLYPH = re.compile(r"^(?:[•●▪■◦‣∙·▫□○◆❖✦➤►▶➢✓✔*\-–—]|\(cid:\d+\)|[-])$")
_GLUED_BULLET = "•●▪■◦‣∙"
_BOLD_WORDS = ("bold", "black", "heavy", "semibold", "demibold", "extrabold", "medium")
_ITALIC_WORDS = ("italic", "oblique")
_SERIF_WORDS = ("times", "georgia", "garamond", "cambria", "palatino", "minion", "charter", "bookman",
                "baskerville", "caslon", "merriweather", "playfair", "lora", "serif", "liberationserif")
_MONO_WORDS = ("courier", "consolas", "mono", "menlo", "monaco")


def _font_flags(fontname: str) -> tuple[bool, bool]:
    n = str(fontname or "").split("+")[-1].lower()
    bold = any(w in n for w in _BOLD_WORDS) or n.endswith(("-bd", ",bold", "-b"))
    italic = any(w in n for w in _ITALIC_WORDS) or n.endswith(("-it", ",italic"))
    return bold, italic


def _is_serif(fontname: str) -> bool:
    n = str(fontname or "").split("+")[-1].lower()
    if "sans" in n.replace("liberationserif", ""):
        return False
    return any(w in n for w in _SERIF_WORDS)


def _hex_color(c) -> str | None:
    """pdf colour tuple -> '#rrggbb'. Black and white return None (we draw on white paper)."""
    if c is None:
        return None
    if isinstance(c, (int, float)):
        c = (c,)
    try:
        c = tuple(float(x) for x in c)
    except (TypeError, ValueError):
        return None
    if len(c) == 1:
        r = g = b = c[0]
    elif len(c) == 3:
        r, g, b = c
    elif len(c) == 4:
        k = c[3]
        r, g, b = ((1 - x) * (1 - k) for x in c[:3])
    else:
        return None
    if max(r, g, b) < 0.12 or min(r, g, b) > 0.92:
        return None
    if 0.299 * r + 0.587 * g + 0.114 * b > 0.62:   # light text (cream, pastel...) was drawn on a dark/coloured page; our page is white
        return None
    return "#%02x%02x%02x" % tuple(max(0, min(255, round(v * 255))) for v in (r, g, b))


def _is_light(c) -> bool:
    """True for white / cream / pastel text colours (text drawn on a dark or coloured page)."""
    if c is None:
        return False
    if isinstance(c, (int, float)):
        c = (c,)
    try:
        c = tuple(float(x) for x in c)
    except (TypeError, ValueError):
        return False
    if len(c) == 1:
        r = g = b = c[0]
    elif len(c) == 3:
        r, g, b = c
    elif len(c) == 4:
        r, g, b = ((1 - x) * (1 - c[3]) for x in c[:3])
    else:
        return False
    return 0.299 * r + 0.587 * g + 0.114 * b > 0.62


def poster_hint(words: list) -> bool:
    """Poster-style page: light text on a dark or coloured background, or giant display lettering."""
    if not words:
        return False
    light = sum(1 for w in words if _is_light(w.get("non_stroking_color")))
    return light / len(words) >= 0.2 or max(float(w.get("size") or 0) for w in words) >= 45


def _merge_chips(words: list, shapes: list) -> list:
    """Skills drawn as rounded 'pills': all words inside one pill become ONE item, so two-line pills stay whole."""
    chips = [sh for sh in shapes if 45 <= sh["width"] <= 240 and 13 <= sh["height"] <= 50]
    taken: set[int] = set()
    merged: list = []
    for sh in sorted(chips, key=lambda c: (c["top"], c["x0"])):
        inside = [w for w in words if id(w) not in taken
                  and sh["x0"] - 2 <= (w["x0"] + w["x1"]) / 2 <= sh["x1"] + 2
                  and sh["top"] - 2 <= (w["top"] + w["bottom"]) / 2 <= sh["bottom"] + 2]
        if not 1 <= len(inside) <= 9:
            continue
        inside.sort(key=lambda w: (round((w["top"] + w["bottom"]) / 2 / 4), w["x0"]))
        taken.update(id(w) for w in inside)
        size = float(inside[0].get("size") or 10)
        mid = (sh["top"] + sh["bottom"]) / 2
        merged.append({**inside[0], "text": " ".join(w["text"] for w in inside),
                       "x0": min(w["x0"] for w in inside), "x1": max(w["x1"] for w in inside),
                       "top": mid - size * 0.6, "bottom": mid + size * 0.6})
    return [w for w in words if id(w) not in taken] + merged


def _comma_gaps(words: list) -> list:
    """Items separated by a wide gap on the same row (pills, 'phone  email  site') get a comma between them."""
    ws = sorted(words, key=lambda w: ((w["top"] + w["bottom"]) / 2, w["x0"]))
    out = list(ws)
    for i, a in enumerate(ws[:-1]):
        b = ws[i + 1]
        same_row = abs((a["top"] + a["bottom"]) / 2 - (b["top"] + b["bottom"]) / 2) <= 0.45 * float(a.get("size") or 10)
        if same_row and b["x0"] - a["x1"] > 2.2 * float(a.get("size") or 10) and not a["text"].endswith((",", ".", ":", ";")):
            out[i] = {**a, "text": a["text"] + ","}
    return out


def _median(xs, default=0.0):
    xs = list(xs)
    return statistics.median(xs) if xs else default


# --------------------------------------------------------------------------- PDF


@dataclass
class _Line:
    words: list
    page: int
    x0: float
    x1: float
    top: float
    bottom: float
    size: float
    bullet: bool = False
    bullet_x: float = 0.0
    text_x: float = 0.0

    @property
    def text(self) -> str:
        return " ".join(w["text"] for w in self.words)

    @property
    def bold_fraction(self) -> float:
        tot = sum(len(w["text"]) for w in self.words) or 1
        return sum(len(w["text"]) for w in self.words if _font_flags(w.get("fontname"))[0]) / tot


def _group_lines(words: list, page: int) -> list:
    ws = sorted(words, key=lambda w: ((w["top"] + w["bottom"]) / 2, w["x0"]))
    groups: list[dict] = []
    for w in ws:
        yc = (w["top"] + w["bottom"]) / 2
        if groups and abs(yc - groups[-1]["yc"]) <= 0.45 * float(w.get("size") or 10):
            g = groups[-1]
            g["w"].append(w)
            g["yc"] = (g["yc"] * (len(g["w"]) - 1) + yc) / len(g["w"])
        else:
            groups.append({"yc": yc, "w": [w]})
    lines = []
    for g in groups:
        row = sorted(g["w"], key=lambda w: w["x0"])
        bullet, bx = False, 0.0
        first = row[0]["text"]
        if len(row) > 1 and _BULLET_GLYPH.match(first):
            bullet, bx = True, row[0]["x0"]
            row = row[1:]
        elif len(first) > 1 and first[0] in _GLUED_BULLET:
            bullet, bx = True, row[0]["x0"]
            row[0] = {**row[0], "text": first[1:], "x0": row[0]["x0"] + 4}
        if not row:
            continue
        chars = sum(len(w["text"]) for w in row) or 1
        size = round(sum(float(w.get("size") or 10) * len(w["text"]) for w in row) / chars * 2) / 2
        lines.append(_Line(row, page, min(w["x0"] for w in row), max(w["x1"] for w in row),
                           min(w["top"] for w in row), max(w["bottom"] for w in row), size,
                           bullet, bx, row[0]["x0"]))
    return lines


def _blocks_from_lines(all_lines, rules, page_w, min_width=120):
    """Group lines into paragraphs and style blocks. Returns (blocks, metas, left, right, width) or None."""
    left = min(l.x0 for l in all_lines)
    right = max(l.x1 for l in all_lines)
    width = right - left
    if width < min_width:
        return None
    col_center = (left + right) / 2

    # ---- decide paragraph boundaries
    def align_of(l: _Line) -> str:
        """center | right | left | full (touches both margins, so it could be any alignment)"""
        if l.bullet:
            return "left"
        lg, rg = l.x0 - left, right - l.x1
        if lg <= 12 and rg <= 12:
            return "full"
        if lg > 10 and rg > 10 and (abs(lg - rg) < 8 or abs((l.x0 + l.x1) / 2 - page_w / 2) < 4):
            return "center"
        if rg < 6 and lg > 0.35 * width:
            return "right"
        return "left"

    def is_full(l: _Line) -> bool:
        return (right - l.x1) <= 0.22 * width

    def continues(prev: _Line, l: _Line, first_of_para: _Line) -> bool:
        """Does line `l` continue the paragraph whose last line is `prev`?"""
        if l.page != prev.page or l.bullet:
            return False
        hang = first_of_para.bullet and abs(l.x0 - first_of_para.text_x) <= 6 and not l.text.isupper()
        if (heading_key(l.text) and not hang) or heading_key(prev.text):
            return False
        if abs(l.size - prev.size) > 0.6 or abs(l.bold_fraction - prev.bold_fraction) > 0.6:
            return False
        pt, lt = prev.text.rstrip(), l.text.rstrip()
        if (pt.endswith((".", "!", "?")) and len(lt.split()) <= 4 and lt[:1].isupper()
                and not lt.endswith((".", "!", "?", ",", ";"))):
            return False                        # a short title-like line after a finished sentence
        pitch = l.bottom - prev.bottom
        if not (0.8 * l.size <= pitch <= 1.65 * l.size):
            return False
        if not is_full(prev):                   # previous line ended early: paragraph is over
            return False
        a, b = align_of(l), align_of(prev)
        if a != b and "full" not in (a, b):     # centre vs left vs right never mix in one paragraph
            return False
        if first_of_para.bullet:                # hanging indent under a bullet
            return abs(l.x0 - first_of_para.text_x) <= 6
        if "center" in (a, b) or a == b == "full" and align_of(first_of_para) == "center":
            return True
        return abs(l.x0 - prev.x0) <= 6

    paras: list[list[_Line]] = []
    for l in all_lines:
        if paras and continues(paras[-1][-1], l, paras[-1][0]):
            paras[-1].append(l)
        else:
            paras.append([l])

    # ---- turn paragraphs into blocks
    ratios = [
        _median(p[i].bottom - p[i - 1].bottom for i in range(1, len(p))) / p[0].size
        for p in paras if len(p) > 1 and p[0].size
    ]
    ratio = min(1.6, max(1.1, _median(ratios, 1.2)))

    blocks: list[Block] = []
    metas: list[tuple[_Line, _Line]] = []       # (first line, last line) per block
    section: str | None = None
    for p in paras:
        runs = _runs_for(p)
        if not runs or not "".join(r.text for r in runs).strip():
            continue
        first, last = p[0], p[-1]
        size = _median((l.size for l in p), first.size)
        leading = _median((p[i].bottom - p[i - 1].bottom for i in range(1, len(p))),
                          size * (ratio if size <= 12.5 else 1.2))
        aligns = [align_of(l) for l in p]
        if "center" in aligns:
            align = "center"
        elif all(a == "right" for a in aligns):
            align = "right"
        else:
            align = "left"
        b = Block(runs=runs, size=size, leading=max(leading, size * 1.05), align=align)
        if first.bullet:
            b.bullet = True
            b.bullet_indent = max(0.0, first.bullet_x - left)
            b.left_indent = max(b.bullet_indent + 6, first.text_x - left)
        elif align == "left" and first.x0 - left > 10 and not b.bullet:
            b.left_indent = first.x0 - left
        key = None if b.text.rstrip().endswith(".") else heading_key(b.text)
        if key:
            b.heading = True
            section = key
        b.section = section
        blocks.append(b)
        metas.append((first, last))
    if not blocks:
        return None

    # ---- spacing between blocks and rules under blocks
    for i, b in enumerate(blocks):
        first, last = metas[i]
        if i == 0 or metas[i - 1][1].page != first.page:
            b.space_before = 0.0
        else:
            prev_last = metas[i - 1][1]
            b.space_before = max(0.0, min(40.0, (first.bottom - prev_last.bottom) - b.leading))
        for r in rules:
            if r.get("used") or r["page"] != last.page:
                continue
            if last.bottom - 2 <= r["top"] <= last.bottom + 0.9 * last.size + 6 and (r["x1"] - r["x0"]) >= 0.4 * width:
                b.rule_after = max(0.4, min(3.0, r["t"]))
                b.rule_color = r["color"]
                r["used"] = True
                if i + 1 < len(blocks):
                    blocks[i + 1].space_before = max(0.0, blocks[i + 1].space_before - (b.rule_after + 4))
                break

    return blocks, metas, left, right, width


def _mark_dots(lines: list, dots: list) -> list:
    """Bullets drawn as tiny vector shapes (not text): mark the line that starts right after one."""
    for l in lines:
        if l.bullet:
            continue
        yc = (l.top + l.bottom) / 2
        for d in dots:
            if d["page"] == l.page and l.x0 - 18 <= d["x1"] <= l.x0 - 1 and abs(d["yc"] - yc) <= 0.6 * l.size + 1:
                l.bullet, l.bullet_x, l.text_x = True, d["x0"], l.x0
                break
    return lines


def _link_text(uri: str) -> str:
    u = re.sub(r"^https?://(www\.)?", "", uri.strip(), flags=re.I).rstrip("/")
    return u


def _apply_links(words: list, links: list) -> tuple[list, list]:
    """Clickable text/icons carry URLs the ATS never sees. Where text sits on a link, add the address
    in brackets after it. Returns (words, links that had no text under them, e.g. icons)."""
    out = list(words)
    loose = []
    for lk in links:
        uri = lk.get("uri") or ""
        if not uri or uri.lower().startswith(("mailto:", "tel:")):
            continue
        shown = _link_text(uri)
        under = [w for w in words if lk["x0"] - 1 <= (w["x0"] + w["x1"]) / 2 <= lk["x1"] + 1
                 and lk["top"] - 2 <= (w["top"] + w["bottom"]) / 2 <= lk["bottom"] + 2]
        if not under:
            loose.append({**lk, "shown": shown})
            continue
        if any(re.search(r"https?:|www\.|\.(?:com|net|org|io|dev|app|me)\b", w["text"], re.I) for w in under):
            continue
        if all(w["text"].startswith("@") for w in under):
            loose.append({**lk, "shown": shown})        # '@handle' beside a social icon
            continue
        last = max(under, key=lambda w: w["x1"])
        size = float(last.get("size") or 10)
        txt = f"({shown})"
        out.append({**last, "text": txt, "x0": last["x1"] + 3, "x1": last["x1"] + 3 + 0.5 * size * len(txt)})
    return out, loose


def fix_tracking(words: list) -> list:
    """Letter-spaced text ("A b o u t  m e") arrives as one-letter words. Glue runs of them back into words,
    splitting where the gap is clearly a space (much wider than the usual letter gap)."""
    ws = sorted(words, key=lambda w: ((w["top"] + w["bottom"]) / 2, w["x0"]))
    rows: list[list] = []
    for w in ws:
        yc = (w["top"] + w["bottom"]) / 2
        if rows and abs(yc - rows[-1][0]) <= 0.45 * float(w.get("size") or 10):
            rows[-1][1].append(w)
        else:
            rows.append([yc, [w]])
    out: list = []
    for _, row in rows:
        row.sort(key=lambda w: w["x0"])
        i = 0
        while i < len(row):
            w = row[i]
            if len(w["text"]) != 1:
                out.append(w)
                i += 1
                continue
            size = float(w.get("size") or 10)
            j = i
            while (j + 1 < len(row) and len(row[j + 1]["text"]) == 1
                   and 0 <= row[j + 1]["x0"] - row[j]["x1"] < 0.9 * size):
                j += 1
            run = row[i:j + 1]
            if len(run) < 3:
                out.extend(run)
                i = j + 1
                continue
            gaps = [run[k + 1]["x0"] - run[k]["x1"] for k in range(len(run) - 1)]
            limit = max(1.6 * _median(gaps), 0.28 * size)
            group = [run[0]]
            for k, g in enumerate(gaps):
                if g > limit:
                    out.append(_join_words(group))
                    group = []
                group.append(run[k + 1])
            out.append(_join_words(group))
            i = j + 1
    return out


def _join_words(grp: list) -> dict:
    if len(grp) == 1:
        return grp[0]
    return {**grp[0], "text": "".join(g["text"] for g in grp), "x1": grp[-1]["x1"],
            "bottom": max(g["bottom"] for g in grp), "top": min(g["top"] for g in grp)}


def _span_rows(words: list, gutter: float) -> tuple[list, list]:
    """Rows that cross the gutter (a full-width contact bar, say) are pulled out of the columns.
    Returns (span_rows, remaining_words); each span row is a list of words sorted left to right."""
    ws = sorted(words, key=lambda w: ((w["top"] + w["bottom"]) / 2, w["x0"]))
    rows: list[list] = []
    for w in ws:
        yc = (w["top"] + w["bottom"]) / 2
        if rows and abs(yc - rows[-1][0]) <= 0.45 * float(w.get("size") or 10):
            rows[-1][1].append(w)
        else:
            rows.append([yc, [w]])
    span, rest = [], []
    for _, row in rows:
        if any(w["x0"] < gutter - 2 and w["x1"] > gutter + 2 for w in row):
            span.append(sorted(row, key=lambda w: w["x0"]))
        else:
            rest.extend(row)
    return span, rest


def _row_items(row: list) -> list[str]:
    """Split one row into items wherever there is a wide gap (icons or tabs between them)."""
    items, cur, prev = [], [], None
    for w in row:
        size = float(w.get("size") or 9)
        if prev is not None and w["x0"] - prev["x1"] > 1.2 * size:
            items.append(" ".join(cur))
            cur = []
        cur.append(w["text"])
        prev = w
    if cur:
        items.append(" ".join(cur))
    return [i.strip() for i in items if i.strip()]


_CONTACT_ITEM = re.compile(r"@|\d|www\.|https?:|\.(?:com|net|org|io|dev|me)\b", re.I)
_PUA_RE = re.compile("[\ue000-\uf8ff]")


def _header_zone(words: list, gutter: float) -> tuple | None:
    """Name, job title and contact items in the band above the columns -> (words, name, size, title, contacts).

    The big name often sits in one column or crosses the gutter, with contact details beside it, so the band
    is read as its own block instead of being split into columns. None when no big name is found."""
    if not words:
        return None
    sizes = sorted(float(w.get("size") or 10) for w in words)
    body = sizes[len(sizes) // 2]
    big = max(sizes)
    if big < max(15.0, 1.35 * body):
        return None
    l, r = _split_sides(words, gutter)
    cut = []
    for side in (l, r):
        for ln in _group_lines(side, 0):
            if heading_key(ln.text) or (len(ln.words) >= 6 and ln.size < 0.8 * big):
                cut.append(ln.top)
    limit = min(cut) if cut else None
    if limit is None:
        return None
    zone = [w for w in words if w["bottom"] <= limit + 1]
    name_words = [w for w in zone if float(w.get("size") or 10) >= max(15.0, 0.75 * big)]
    if not name_words:
        return None
    rows: list[list] = []
    for w in sorted(name_words, key=lambda w: ((w["top"] + w["bottom"]) / 2, w["x0"])):
        yc = (w["top"] + w["bottom"]) / 2
        if rows and abs(yc - rows[-1][0]) <= 0.45 * float(w.get("size") or 10):
            rows[-1][1].append(w)
        else:
            rows.append([yc, [w]])
    name = " ".join(" ".join(x["text"] for x in sorted(row, key=lambda x: x["x0"])) for _, row in rows)
    name_ids = {id(w) for w in name_words}
    rest = [w for w in zone if id(w) not in name_ids]
    items: list[str] = []
    rows = []
    for w in sorted(rest, key=lambda w: ((w["top"] + w["bottom"]) / 2, w["x0"])):
        yc = (w["top"] + w["bottom"]) / 2
        if rows and abs(yc - rows[-1][0]) <= 0.45 * float(w.get("size") or 10):
            rows[-1][1].append(w)
        else:
            rows.append([yc, [w]])
    for _, row in rows:
        items += [_PUA_RE.sub("", it).strip() for it in _row_items(sorted(row, key=lambda x: x["x0"]))]
    items = [i for i in items if i]
    title, contacts = None, []
    for it in items:
        if title is None and not _CONTACT_ITEM.search(it) and len(it.split()) <= 6:
            title = it
        else:
            contacts.append(it)
    size = _median(float(w.get("size") or 10) for w in name_words)
    return zone, name, size, title, contacts


def _split_subcolumns(words: list, dots: list | None = None) -> list:
    """A block of rows laid out as two side-by-side lists (e.g. two references) is read list by list."""
    ws = sorted(words, key=lambda w: ((w["top"] + w["bottom"]) / 2, w["x0"]))
    rows: list[list] = []
    for w in ws:
        yc = (w["top"] + w["bottom"]) / 2
        if rows and abs(yc - rows[-1][0]) <= 0.45 * float(w.get("size") or 10):
            rows[-1][1].append(w)
        else:
            rows.append([yc, [w]])
    info = []
    for yc, row in rows:
        row.sort(key=lambda w: w["x0"])
        cut = None
        for a, b in zip(row, row[1:]):
            gap = b["x0"] - a["x1"]
            if gap > 28 and gap > 2.5 * float(a.get("size") or 9):
                cut = (a["x1"], b["x0"])
                break
        info.append(cut)
    out = list(words)
    shift_from = None
    i = 0
    shifted: dict[int, float] = {}
    n = len(rows)
    while i < n:
        if info[i] is None:
            i += 1
            continue
        j = i
        lo, hi = info[i]
        while j + 1 < n and info[j + 1] is not None and min(hi, info[j + 1][1]) - max(lo, info[j + 1][0]) > 20:
            lo, hi = max(lo, info[j + 1][0]), min(hi, info[j + 1][1])
            j += 1
        if j - i + 1 >= 3:
            cx = (lo + hi) / 2
            top = min(w["top"] for k in range(i, j + 1) for w in rows[k][1])
            bottom = max(w["bottom"] for k in range(i, j + 1) for w in rows[k][1])
            height = bottom - top + 4
            for k in range(i, j + 1):
                for w in rows[k][1]:
                    if (w["x0"] + w["x1"]) / 2 >= cx:
                        shifted[id(w)] = height
            below = bottom
            for d in (dots or []):
                if d["yc"] >= below - 1:
                    d["yc"] += height
            for k in range(j + 1, n):
                for w in rows[k][1]:
                    if w["top"] >= below - 1:
                        shifted[id(w)] = shifted.get(id(w), 0) + height
        i = j + 1
    if not shifted:
        return words
    res = []
    for w in words:
        d = shifted.get(id(w), 0)
        res.append({**w, "top": w["top"] + d, "bottom": w["bottom"] + d} if d else w)
    return res


def _split_sides(words: list, gutter: float) -> tuple[list, list]:
    left = [w for w in words if (w["x0"] + w["x1"]) / 2 < gutter]
    right = [w for w in words if (w["x0"] + w["x1"]) / 2 >= gutter]
    return left, right


def _main_is_left(words: list, gutter: float) -> bool:
    """The main column is the one holding the biggest text (the name)."""
    l, r = _split_sides(words, gutter)
    big = lambda ws: max((float(w.get("size") or 0) for w in ws), default=0.0)
    return big(l) >= big(r)


def column_text(page) -> str | None:
    """Plain text of a two-column page read column by column (main column first). None if single column."""
    try:
        words = page.extract_words(x_tolerance=2, y_tolerance=3, extra_attrs=["fontname", "size"])
    except Exception:
        return None
    words = fix_tracking(words)
    g = find_gutter(words)
    if g is None:
        return None
    head = _header_zone(words, g)
    pre: list[str] = []
    if head:
        ids = {id(w) for w in head[0]}
        words = [w for w in words if id(w) not in ids]
        pre = [head[1]] + ([head[3]] if head[3] else []) + ["  ".join(head[4])] if head[4] else (
            [head[1]] + ([head[3]] if head[3] else []))
    span, words = _span_rows(words, g)
    l, r = _split_sides(words, g)
    first, second = (l, r) if _main_is_left(words, g) else (r, l)
    cols = [[ln.text for ln in _group_lines(_split_subcolumns(col), 0)] for col in (first, second)]
    bar = ["  ".join(_row_items(row)) for row in span]
    at = next((i for i, t in enumerate(cols[0]) if heading_key(t)), len(cols[0]))
    cols[0][at:at] = bar
    return "\n".join(pre + cols[0] + cols[1])


_EN_WORDS = {"the", "and", "with", "of", "for", "in", "to", "my", "a", "an", "on", "at", "as", "i"}
_TR_WORDS = {"ve", "ile", "bir", "icin", "için", "bu", "olarak", "de", "da", "ben", "gelistirdim", "geliştirdim"}


def is_turkish(text: str) -> bool:
    toks = re.findall(r"[^\W\d_]+", text.lower())
    en = sum(1 for t in toks if t in _EN_WORDS)
    tr = sum(1 for t in toks if t in _TR_WORDS)
    return tr > en


def nice_case(t: str, turkish: bool = False) -> str:
    """ALL CAPS -> Capitalised Words (keeps 1-2 letter words such as IT, UK). Mixed case stays as it is."""
    letters = [c for c in t if c.isalpha()]
    if not letters or not all(c.isupper() for c in letters):
        return t
    low = (lambda w: w.replace("İ", "i").replace("I", "ı").lower()) if turkish else (lambda w: w.replace("İ", "I").lower())
    small = {"and", "of", "in", "the", "for", "to", "at", "on", "ve", "ile"}
    out = []
    for n, w in enumerate(t.split(" ")):
        core = [c for c in w if c.isalpha()]
        if n and w.lower() in small:
            out.append(w.lower())
        elif len(core) <= 2 or any(ch in w for ch in "&./@#+0123456789"):
            out.append(w)                       # IT, UI&UX, COREDE.AI, C++ stay as written
        elif "-" in w:
            out.append("-".join(p[:1] + low(p[1:]) for p in w.split("-")))
        else:
            out.append(w[:1] + low(w[1:]))
    return " ".join(out)


_YEAR_RE = re.compile(r"(?:19|20)\d{2}")
_END_YEARS = re.compile(r"\s*((?:19|20)\d{2}\s*[-–—]\s*(?:(?:19|20)\d{2}|present|now)?|(?:19|20)\d{2})\s*$", re.I)
_TAIL_DATE = re.compile(r"(?:(?:19|20)\d{2}\s*[-–—]\s*(?:(?:19|20)\d{2}|present|now|current|devam\w*)|(?:19|20)\d{2})\s*$", re.I)
_DEGREE = re.compile(r"bachelor|master|associate|phd|doctor|degree|diploma|lisans|onlisans|önlisans|doktora|yüksek", re.I)


def _all_bold(b) -> bool:
    return bool(b.runs) and all(r.bold for r in b.runs if r.text.strip())


def _merge_entries(items: list, turkish: bool) -> list:
    """date / job title / company on separate lines -> 'Title | Company | Date' (one line an ATS can parse)."""
    out, i = [], 0
    while i < len(items):
        b = items[i]
        t = b.text.strip()
        if (not b.bullet and len(b.runs) >= 2 and b.runs[0].bold and not b.runs[-1].bold
                and _YEAR_RE.search(b.runs[-1].text) and len(t.split()) <= 12):
            title = nice_case("".join(r.text for r in b.runs if r.bold).strip(), turkish)
            date = nice_case("".join(r.text for r in b.runs if not r.bold).strip(), turkish)
            nxt = items[i + 1] if i + 1 < len(items) else None
            parts = [title]
            j = i + 1
            if (nxt is not None and not nxt.bullet and not _all_bold(nxt) and len(nxt.text.split()) <= 7
                    and not _YEAR_RE.search(nxt.text) and not nxt.text.strip().endswith((".", ":", ";"))):
                parts.append(nice_case(nxt.text.strip(), turkish))
                j += 1
            out.append(Block([Run(" | ".join(parts), bold=True), Run("  |  " + date)], size=b.size,
                             leading=b.leading, space_before=max(b.space_before, 5.0), section=b.section))
            i = j
            continue
        mC = _TAIL_DATE.search(t) if not b.bullet else None
        if mC and mC.start() > 0 and len(t.split()) <= 14 and not t.endswith((".", ";", ",")):
            head = t[:mC.start()].strip(" -–—|,")
            letters = [c for c in re.sub(r"\([^)]*\)", "", head) if c.isalpha()]
            if head and (all(c.isupper() for c in letters) or b.runs[0].bold):
                pm = re.search(r"\s*\([^)]*\)\s*$", head)
                shown = (nice_case(head[:pm.start()], turkish) + " " + pm.group(0).strip()) if pm else nice_case(head, turkish)
                out.append(Block([Run(shown, bold=True),
                                  Run("  |  " + nice_case(mC.group(0).strip(), turkish))], size=b.size,
                                 leading=b.leading, space_before=max(b.space_before, 5.0), section=b.section))
                i += 1
                continue
        if (not b.bullet and not _all_bold(b) and len(t.split()) <= 8 and _YEAR_RE.search(t)):
            j = i + 1
            heads = []
            while (j < len(items) and len(heads) < 3 and _all_bold(items[j]) and not items[j].bullet
                   and len(items[j].text.split()) <= 8 and not items[j].text.strip().endswith((".", ":"))):
                heads.append(nice_case(items[j].text.strip(), turkish))
                j += 1
            if heads:
                m = Block([Run(" | ".join(heads), bold=True), Run("  |  " + nice_case(t, turkish))], size=b.size, leading=b.leading,
                          space_before=max(b.space_before, 5.0), section=b.section)
                out.append(m)
                i = j
                continue
        out.append(b)
        i += 1
    return out


def _merge_education(items: list, turkish: bool) -> list:
    """degree / field / school / years on separate lines -> 'Degree, Field, School | Years'."""
    groups: list[list] = []
    for b in items:
        t = b.text.strip()
        starts = _DEGREE.search(t) and len(t.split()) <= 12 and not _END_YEARS.fullmatch(t)
        if starts or not groups:
            groups.append([b])
        else:
            groups[-1].append(b)
    out = []
    for g in groups:
        if len(g) < 2 or any(len(b.text.split()) > 10 or b.bullet for b in g):
            out.extend(g)
            continue
        parts, years = [], ""
        for b in g:
            t = b.text.strip()
            m = _END_YEARS.search(t)
            if m:
                years = years or m.group(1).strip()
                t = t[:m.start()].strip()
            if t:
                parts.append(nice_case(t, turkish))
        runs = [Run(", ".join(parts), bold=True)]
        if years:
            runs.append(Run("  |  " + years))
        out.append(Block(runs, size=g[0].size, leading=g[0].leading, space_before=max(g[0].space_before, 5.0),
                         section=g[0].section))
    return out


_CONTACT_LIKE = re.compile(r"@|\+?\d[\d\s().-]{6,}\d|https?://|www\.", re.I)


def _group_references(items: list) -> list:
    """name / role / company / phone lines -> '**Name, Role**' then 'Company | Phone' for each person."""
    groups, cur = [], []
    for b in items:
        cur.append(b)
        if _CONTACT_LIKE.search(b.text) and len(b.text.split()) <= 6:
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    out = []
    for g in groups:
        if len(g) < 2 or any(b.bullet or len(b.text.split()) > 10 for b in g):
            out.extend(g)
            continue
        first = g[0]
        name = re.sub(r"\s*\|\s*", ", ", first.text.strip())
        out.append(Block([Run(name, bold=True)], size=first.size, leading=first.leading,
                         space_before=max(first.space_before, 5.0), section=first.section))
        out.append(Block([Run("  |  ".join(b.text.strip() for b in g[1:]))], size=first.size,
                         leading=first.leading, space_before=0.0, section=first.section))
    return out


_ORDER = ["summary", "experience", "internships", "projects", "education", "certifications", "skills",
          "languages", "awards", "publications", "volunteer", "interests", "references"]


def _two_column_layout(page_words: list, gutters: list, page_w: float, page_h: float, votes: tuple,
                       dots: list | None = None, links: list | None = None) -> Layout | None:
    """Merge a two-column page into ONE column in sensible reading order (what ATS software needs)."""
    g0 = next(g for g in gutters if g is not None)
    main_left = _main_is_left(page_words[0], gutters[0] if gutters[0] is not None else g0)
    main_lines: list = []
    side_lines: list = []
    bar_items: list[str] = []
    loose_links: list[dict] = []
    header = None
    for pi, ws in enumerate(page_words):
        g = gutters[pi] if gutters[pi] is not None else g0
        ws, loose = _apply_links(ws, [k for k in (links or []) if k["page"] == pi])
        loose_links += loose
        if pi == 0:
            header = _header_zone(ws, g)
            if header:
                ids = {id(w) for w in header[0]}
                ws = [w for w in ws if id(w) not in ids]
        span, ws = _span_rows(ws, g)
        for row in span:
            bar_items += _row_items(row)
        l, r = _split_sides(ws, g)
        l, r = _split_subcolumns(l), _split_subcolumns(r)
        m, sd = (l, r) if main_left else (r, l)
        main_lines += _mark_dots(_group_lines(m, pi), dots or [])
        side_lines += _mark_dots(_group_lines(sd, pi), dots or [])

    def blocks_of(lines):
        if not lines:
            return []
        built = _blocks_from_lines(lines, [], page_w, min_width=40)
        return built[0] if built else []

    mb, sb = blocks_of(main_lines), blocks_of(side_lines)
    if not mb:
        return None

    def split(blocks):
        head, secs = [], []
        for b in blocks:
            if b.heading:
                secs.append([b.section, b.text.strip(), []])
            elif secs:
                secs[-1][2].append(b)
            else:
                head.append(b)
        return head, secs

    from .pdf_builder import _clean_runs        # strip stars, skill bars and icons before blocks get merged
    mb = [b for b in mb if _clean_runs(b)]
    sb = [b for b in sb if _clean_runs(b)]
    turkish = is_turkish(" ".join(b.text for b in mb + sb))
    mh, ms = split(mb)
    sh, ss = split(sb)

    def body(b: Block, keep_space: bool = True) -> Block:
        for r in b.runs:
            r.color = None
        b.size, b.leading = (10.0, 13.0) if not b.bullet else (10.0, 13.0)
        b.align, b.rule_after, b.heading = "left", 0.0, False
        b.space_before = min(b.space_before, 7.0) if keep_space else 0.0
        if not b.bullet:
            b.left_indent = 0.0
        return b

    while (len(mh) > 1 and abs(mh[0].size - mh[1].size) <= 1.0 and all(r.bold for r in mh[0].runs + mh[1].runs)):
        mh[0].runs.append(Run(" "))                 # a long name wrapped onto two lines
        mh[0].runs.extend(mh[1].runs)
        del mh[1]
    out: list[Block] = []
    if header:
        _, hname, hsize, htitle, hcontacts = header
        size = min(hsize, 22.0)
        out.append(Block([Run(hname.strip(), bold=True)], size=size, leading=size * 1.2, align="center"))
        if htitle:
            out.append(Block([Run(htitle.upper() if turkish else htitle.replace("İ", "I").upper())], size=11.0,
                             leading=14.0, space_before=2.0, align="center"))
        hcontacts = list(hcontacts)
        zone_bottom = max((w["bottom"] for w in header[0]), default=0)
        for lk in loose_links:
            if lk["top"] > zone_bottom:
                continue
            shown = lk["shown"]
            low = shown.lower()
            for n, it in enumerate(hcontacts):
                bare = it.lstrip("@").lower()
                if len(bare) >= 4 and bare in low and bare != low:
                    hcontacts[n] = shown            # '@handle' next to a LinkedIn icon -> full address
                    break
            else:
                if not any(shown.lower() in it.lower() for it in hcontacts):
                    hcontacts.append(shown)
        bar_items = hcontacts + bar_items
        mh = []
    # --- header: name, title, then one contact line
    for i, b in enumerate(mh):
        for r in b.runs:
            r.color = None
            r.text = re.sub(r"\s{2,}", " ", r.text)
        if i == 0:
            b.size = min(b.size, 22.0)
            b.leading = b.size * 1.2
            b.space_before = 0.0
            for r in b.runs:
                r.bold = True
        else:
            b.size = min(max(b.size, 10.0), 12.0)
            b.leading = b.size * 1.3
            b.space_before = 2.0
        b.align, b.rule_after, b.left_indent, b.bullet = "center", 0.0, 0.0, False
        if i == 1:
            for r in b.runs:
                r.text = r.text.replace("İ", "I").upper() if not turkish else r.text.upper()
        out.append(b)
    out.extend(body(b) for b in sh)

    contact_bits: list[str] = list(bar_items)
    sections = [(k, t, bl) for k, t, bl in ms + ss]
    keep = []
    for k, t, bl in sections:
        if k == "contact":
            contact_bits += [b.text.strip() for b in bl if b.text.strip()]
        else:
            keep.append((k, t, bl))
    if contact_bits:
        out.append(Block([Run("  |  ".join(contact_bits))], size=10.0, leading=13.0, space_before=3.0, align="center"))

    def rank(item):
        k = item[0]
        return _ORDER.index(k) if k in _ORDER else len(_ORDER)

    keep = sorted(keep, key=rank)      # stable: unknown sections keep their original order
    for k, t, bl in keep:
        out.append(Block([Run(t, bold=True)], size=11.0, leading=14.0, space_before=11.0, rule_after=0.6,
                         heading=True, section=k))
        items = []
        for b in (body(b) for b in bl):
            p = items[-1] if items else None
            plain = lambda x: not x.bullet and not any(r.bold for r in x.runs)
            if (k not in ("education", "languages", "skills", "tools", "references", "certifications") and p is not None and plain(p) and plain(b)
                    and b.space_before <= 3.0
                    and not re.search(r"[.!?:;]\s*$", p.text)):
                p.runs.append(Run(" "))         # a column wrapped one sentence early ("I HAVE / DEVELOPED ...")
                p.runs.extend(b.runs)
            else:
                items.append(b)
        if k in ("experience", "internships", "projects"):
            items = _merge_entries(items, turkish)
        if k == "education":
            items = _merge_education(items, turkish)
        if k == "references":
            items = _group_references(items)
        if k == "languages":
            fixed = []
            for b in items:
                m = re.match(r"^([^\s\d\-–:,()]+)\s+([^\d:]{3,40})$", b.text.strip())
                if (m and 2 <= len(b.text.split()) <= 5 and m.group(1).isupper() and not m.group(2).isupper()
                        and not b.bullet):
                    b = Block([Run(nice_case(m.group(1), turkish), bold=True), Run(" - " + m.group(2).strip())],
                              size=b.size, leading=b.leading, space_before=b.space_before, section=k)
                fixed.append(b)
            items = fixed
        if k == "languages" and len(items) >= 2 and all(
                not b.bullet and len(b.text.split()) <= 3 and not re.search(r"[-–:\d]", b.text) for b in items):
            txt = ", ".join(nice_case(b.text.strip(), turkish) for b in items)
            items = [Block([Run(txt)], size=10.0, leading=13.0, space_before=2.0, section=k)]
        if k in ("skills", "tools"):         # one skill per line in a sidebar -> one comma-separated list
            short = [b for b in items if len(b.text.split()) <= 6]
            if len(items) >= 3 and len(short) == len(items):
                txt = ", ".join(b.text.strip().rstrip(",;") for b in items)
                items = [Block([Run(txt)], size=10.0, leading=13.0, space_before=2.0, section=k)]
        for b in items:
            b.section = k
        if items:
            items[0].space_before = min(items[0].space_before, 3.0)
        out.extend(items)

    total, serif, mono = votes
    return Layout(out, page_w, page_h, (40.0, 38.0, 40.0, 40.0), serif=serif > 0.5 * total,
                  mono=mono > 0.5 * total, reflowed=True)


def read_pdf_layout(path: str) -> Layout | None:
    import pdfplumber

    all_lines: list[_Line] = []
    page_words: list[list] = []
    dots: list[dict] = []
    links: list[dict] = []
    rules: list[dict] = []
    serif_votes = mono_votes = total_votes = 0
    light_words = n_words = 0
    biggest = 0.0
    with pdfplumber.open(path) as pdf:
        if not pdf.pages:
            return None
        page_w, page_h = float(pdf.pages[0].width), float(pdf.pages[0].height)
        for pi, page in enumerate(pdf.pages):
            attrs = ["fontname", "size", "non_stroking_color"]
            try:
                words = page.extract_words(x_tolerance=2, y_tolerance=3, extra_attrs=attrs)
            except Exception:
                words = page.extract_words(x_tolerance=2, y_tolerance=3, extra_attrs=attrs[:2])
            words = fix_tracking(words)
            page_words.append(words)
            for w in words:
                n_words += 1
                light_words += 1 if _is_light(w.get("non_stroking_color")) else 0
                biggest = max(biggest, float(w.get("size") or 0))
                n = len(w["text"])
                total_votes += n
                serif_votes += n if _is_serif(w.get("fontname")) else 0
                mono_votes += n if any(m in str(w.get("fontname", "")).lower() for m in _MONO_WORDS) else 0
            for sh in list(getattr(page, "curves", []) or []) + list(page.rects):
                if 1.2 <= sh["width"] <= 4.8 and 1.2 <= sh["height"] <= 4.8:
                    dots.append({"page": pi, "x0": sh["x0"], "x1": sh["x1"], "yc": (sh["top"] + sh["bottom"]) / 2})
            for h in (getattr(page, "hyperlinks", None) or []):
                if h.get("uri"):
                    links.append({"page": pi, "x0": h["x0"], "x1": h["x1"], "top": h["top"], "bottom": h["bottom"],
                                  "uri": h["uri"]})
            if poster_hint(words):
                words = _merge_chips(words, list(getattr(page, "curves", []) or []) + list(page.rects))
                # side-by-side items (two degrees, two lists) are read one after the other; bullet shapes move with the text
                words = _split_subcolumns(words, [d for d in dots if d["page"] == pi])
                words = _comma_gaps(words)
                page_words[-1] = words
            all_lines.extend(_mark_dots(_group_lines(words, pi), dots))
            for ln in page.lines:
                if abs(ln["top"] - ln["bottom"]) < 1.5:
                    rules.append({"page": pi, "x0": ln["x0"], "x1": ln["x1"], "top": ln["top"],
                                  "t": float(ln.get("linewidth") or 0.75),
                                  "color": _hex_color(ln.get("stroking_color")) or "#444444"})
            for rc in page.rects:
                if rc["height"] <= 3 and rc["width"] > 60:
                    rules.append({"page": pi, "x0": rc["x0"], "x1": rc["x1"], "top": rc["top"],
                                  "t": max(0.5, float(rc["height"])),
                                  "color": _hex_color(rc.get("non_stroking_color")) or "#444444"})
    if not all_lines or total_votes == 0:
        return None

    gutters = [find_gutter(w) for w in page_words]
    if sum(g is not None for g in gutters) >= max(1, (len(page_words) + 1) // 2):
        return _two_column_layout(page_words, gutters, page_w, page_h, (total_votes, serif_votes, mono_votes), dots, links)
    built = _blocks_from_lines(all_lines, rules, page_w)
    if built is None:
        return None
    blocks, metas, left, right, width = built
    poster_doc = any(poster_hint(w) for w in page_words)
    if poster_doc:
        blocks = _tame_display_text(blocks)
        for i, b in enumerate(blocks):
            if i == 1 and not b.heading and len(b.text.split()) < 14:
                b.align = "center"                      # contact line sits centred under the name
            elif i > 0 and not b.bullet:
                b.align, b.left_indent = "left", 0.0
        # an intro paragraph under the name with no heading: give it one, so every ATS reads it as the summary
        first_head = next((i for i, b in enumerate(blocks) if b.heading), len(blocks))
        intro = [i for i in range(1, first_head) if len(blocks[i].text.split()) >= 12]
        if intro and first_head < len(blocks):
            tr = is_turkish(" ".join(b.text for b in blocks))
            h = Block([Run("ÖZET" if tr else "SUMMARY", bold=True)], size=12.0, leading=15.0,
                      space_before=blocks[first_head].space_before, rule_after=blocks[first_head].rule_after,
                      rule_color=blocks[first_head].rule_color, heading=True, section="summary")
            blocks.insert(intro[0], h)

    first_page_lines = [l for l in all_lines if l.page == 0]
    top = min(l.top for l in first_page_lines) if first_page_lines else 36
    if any(poster_hint(w) for w in page_words):
        top = min(top, 40.0)           # the original's big header artwork is not rebuilt
    bottom = page_h - max(l.bottom for l in all_lines)
    margins = (max(18.0, left), max(18.0, top), max(18.0, page_w - right), max(24.0, min(bottom, 60.0)))
    return Layout(blocks, page_w, page_h, margins,
                  serif=serif_votes > 0.5 * total_votes, mono=mono_votes > 0.5 * total_votes)


_GREETING_RE = re.compile(r"^(merhaba|selam|hello|hi|hey|hola|bonjour|hallo)\W*$", re.I)


def _tame_display_text(blocks: list, name_pt: float = 22.0, body_max: float = 15.0) -> list:
    """Poster-style CVs use huge decorative lettering ('MERHABA!', 80 pt names). Drop pure greetings, cap sizes,
    put the name first and make headings clearly bold, so the rebuilt CV reads like a normal one."""
    out = list(blocks)
    while out and out[0].runs and _GREETING_RE.match("".join(r.text for r in out[0].runs).strip()):
        out.pop(0)
    name = next((b for b in out[:6] if b.size > body_max), None)
    for b in out:
        if b is name:
            b.size, b.leading = name_pt, name_pt * 1.2
            for r in b.runs:
                r.bold = True
        elif b.size > body_max:
            b.size, b.leading = body_max, body_max * 1.2
        if b.heading:
            b.size, b.leading = 12.0, 15.0
            for r in b.runs:
                r.bold = True
    if name is not None and out.index(name) > 0:
        out.remove(name)
        out.insert(0, name)
    return out


def _runs_for(lines: list) -> list:
    runs: list[Run] = []
    for li, l in enumerate(lines):
        prev = None
        for w in l.words:
            bold, italic = _font_flags(w.get("fontname"))
            color = _hex_color(w.get("non_stroking_color"))
            size = float(w.get("size") or l.size)
            if not runs:
                sep = ""
            elif prev is None:
                sep = " "                       # new line inside the same paragraph
            else:
                sep = "" if (w["x0"] - prev["x1"]) < 0.15 * size else " "
            style = (bold, italic, color)
            if runs and (runs[-1].bold, runs[-1].italic, runs[-1].color) == style:
                runs[-1].text += sep + w["text"]
            else:
                if runs and sep:
                    runs[-1].text += sep
                runs.append(Run(w["text"], bold, italic, color))
            prev = w
    return runs


# --------------------------------------------------------------------------- DOCX


def read_docx_layout(path: str) -> Layout | None:
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.text.run import Run as DocxRun

    doc = Document(path)
    sec = doc.sections[0]
    try:
        page_w, page_h = sec.page_width.pt, sec.page_height.pt
        margins = (sec.left_margin.pt, sec.top_margin.pt, sec.right_margin.pt, sec.bottom_margin.pt)
    except Exception:
        return None

    def eff(par, getter):
        """paragraph value, falling back to its style chain"""
        v = getter(par.paragraph_format)
        st = par.style
        while v is None and st is not None:
            v = getter(st.paragraph_format)
            st = st.base_style
        return v

    def font_val(r, par, attr):
        v = getattr(r.font, attr)
        if v is not None:
            return v
        st = r.style or par.style
        while st is not None:
            v = getattr(st.font, attr)
            if v is not None:
                return v
            st = st.base_style
        return None

    blocks: list[Block] = []
    section: str | None = None
    serif_votes = total_votes = 0
    pending_after = 0.0
    default_size = 11.0
    for par in doc.paragraphs:
        runs: list[Run] = []
        sizes: list[float] = []
        for r_el in par._p.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}r"):
            r = DocxRun(r_el, par)
            txt = r.text.replace("\t", "    ").replace("\n", " ")
            if not txt:
                continue
            bold = bool(font_val(r, par, "bold"))
            italic = bool(font_val(r, par, "italic"))
            color = None
            try:
                rgb = r.font.color.rgb if r.font.color is not None else None
                if rgb is not None:
                    color = _hex_color(tuple(int(str(rgb)[i:i + 2], 16) / 255 for i in (0, 2, 4)))
            except Exception:
                color = None
            sz = font_val(r, par, "size")
            sizes.append(sz.pt if sz is not None else default_size)
            fname = str(font_val(r, par, "name") or "")
            total_votes += len(txt)
            serif_votes += len(txt) if _is_serif(fname) else 0
            if runs and (runs[-1].bold, runs[-1].italic, runs[-1].color) == (bold, italic, color):
                runs[-1].text += txt
            else:
                runs.append(Run(txt, bold, italic, color))
        if not runs or not "".join(r.text for r in runs).strip():
            continue
        size = _median(sizes, default_size)
        al = par.alignment if par.alignment is not None else eff(par, lambda pf: pf.alignment)
        align = {WD_ALIGN_PARAGRAPH.CENTER: "center", WD_ALIGN_PARAGRAPH.RIGHT: "right"}.get(al, "left")
        sb = eff(par, lambda pf: pf.space_before)
        sa = eff(par, lambda pf: pf.space_after)
        ls = eff(par, lambda pf: pf.line_spacing)
        if ls is None:
            leading = size * 1.2
        elif isinstance(ls, float):
            leading = size * 1.17 * ls
        else:
            leading = ls.pt
        li = eff(par, lambda pf: pf.left_indent)
        ppr = par._p.pPr
        is_bullet = (ppr is not None and ppr.numPr is not None) or (par.style is not None and "list" in par.style.name.lower())
        b = Block(runs=runs, size=size, leading=max(leading, size * 1.05), align=align,
                  space_before=min(40.0, (sb.pt if sb is not None else 0.0) + pending_after))
        pending_after = sa.pt if sa is not None else 0.0
        if is_bullet:
            b.bullet = True
            b.bullet_indent = max(0.0, (li.pt if li is not None else 18.0) - 14)
            b.left_indent = (li.pt if li is not None else 18.0)
        elif li is not None and li.pt > 4:
            b.left_indent = li.pt
        if ppr is not None and ppr.find("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}pBdr") is not None:
            if ppr.find(".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}bottom") is not None:
                b.rule_after, b.rule_color = 0.75, "#444444"
        key = heading_key(b.text)
        if key:
            b.heading = True
            section = key
        b.section = section
        blocks.append(b)
    if not blocks:
        return None
    if blocks:
        blocks[0].space_before = 0.0
    return Layout(blocks, page_w, page_h, margins, serif=serif_votes > 0.5 * max(1, total_votes))


def read_layout(path: str, kind: str) -> Layout | None:
    """Best-effort layout read. None means: use the simple fallback builder."""
    try:
        if kind == "pdf":
            return read_pdf_layout(path)
        if kind == "docx":
            return read_docx_layout(path)
    except Exception:
        return None
    return None
