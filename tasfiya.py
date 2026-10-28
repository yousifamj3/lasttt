# -*- coding: utf-8 -*-
"""
تصفية الشحنات [يوسف اسطورة]
----------------------------
قائمة 1 «صاعد وواصل»  : كشوفات الصاعد  ضد  كشوفات الواصل  ->  pdf المفقودات
قائمة 2 «واصل ومفقودات»: كشوفات المفقودات  ضد  واصل جديد  ->  pdf المفقودات المتبقية

التشغيل:
    pip install streamlit pdfplumber pandas reportlab
    streamlit run tasfiya.py

الخط العربي للـPDF: حط DejaVuSans.ttf و DejaVuSans-Bold.ttf بنفس مكان هذا الملف.
"""
import io
import os
import re
import unicodedata
from functools import lru_cache
from datetime import datetime, timedelta, timezone

import pandas as pd
import pdfplumber
import streamlit as st

IRAQ_TZ = timezone(timedelta(hours=3))
WEEKDAYS = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]

# ======================================================================
#                          أدوات النص العربي
# ======================================================================
_AR_LETTER = re.compile(r"[\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF]")
_PRESENTATION = re.compile(r"[\uFB50-\uFDFF\uFE70-\uFEFF]")
_MARKS = re.compile(r"[\u064B-\u065F\u0670\u0640]")  # تشكيل + تطويل
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_MIRROR = str.maketrans("()[]{}<>«»", ")(][}{><»«")


def _reorder(line):
    """يعكس ترتيب سطر فيه عربي وأرقام. نفس العملية تحوّل (بصري←منطقي) وبالعكس."""
    toks = line.split()
    kind = ["R" if _AR_LETTER.search(t) else "L" if re.search(r"[0-9A-Za-z]", t) else "N" for t in toks]
    strong = [k if k != "N" else None for k in kind]
    out = list(kind)
    for i, k in enumerate(kind):
        if k == "N":  # علامة (: , -) بين عربي ورقم تاخذ اتجاه العربي
            before = next((strong[j] for j in range(i - 1, -1, -1) if strong[j]), None)
            after = next((strong[j] for j in range(i + 1, len(kind)) if strong[j]), None)
            out[i] = before if before and before == after else "R"
    runs = []
    for t, k in zip(toks, out):
        if runs and runs[-1][0] == k:
            runs[-1][1].append(t)
        else:
            runs.append((k, [t]))
    parts = [" ".join(t[::-1].translate(_MIRROR) for t in reversed(ts)) if k == "R" else " ".join(ts)
             for k, ts in reversed(runs)]
    return " ".join(parts)


def fix_cell(text, visual=None):
    """pdfplumber يطلّع العربي مقلوب (ترتيب بصري) — هنا نرجّعه للترتيب الصحيح."""
    if not text:
        return ""
    if visual is None:
        visual = bool(_PRESENTATION.search(text))
    lines = []
    for line in str(text).split("\n"):
        line = " ".join(line.split())
        if line:
            lines.append(_reorder(line) if visual else line)
    out = unicodedata.normalize("NFKC", " ".join(lines))
    return re.sub(r"\s+", " ", _MARKS.sub("", out)).strip()


def norm(text):
    """تطبيع للمقارنة: توحيد الهمزات والياء والتاء المربوطة وحذف التشكيل."""
    s = unicodedata.normalize("NFKC", str(text or ""))
    s = _MARKS.sub("", s)
    for a, b in (("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ٱ", "ا"), ("ى", "ي"), ("ئ", "ي"), ("ؤ", "و"), ("ة", "ه")):
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s).strip().lower()


def to_int(text):
    t = str(text or "").translate(_DIGITS).replace(",", "").replace("٬", "")
    m = re.search(r"\d+(?:\.\d+)?", t)
    return int(round(float(m.group()))) if m else 0


def digits_only(text):
    return re.sub(r"\D", "", str(text or "").translate(_DIGITS))


def money(n):
    return "\u200e" + f"{int(n):,}"


def ship_key(ship):
    """مفتاح المطابقة: رقم الشحنة بدون أصفار بالبداية."""
    s = digits_only(ship)
    return s.lstrip("0") or s


# ---------- تشكيل الحروف العربية للرسم بالـPDF (بدون مكتبات إضافية) ----------
_FORMS = {}


def _arabic_forms():
    """جدول أشكال الحروف (معزول/أول/وسط/آخر) نبنيه من يونيكود نفسه."""
    if not _FORMS:
        for cp in range(0xFE80, 0xFEFD):
            dec = unicodedata.decomposition(chr(cp))
            if dec.startswith("<"):
                tag, _, rest = dec[1:].partition("> ")
                base = "".join(chr(int(x, 16)) for x in rest.split())
                _FORMS.setdefault(base, {})[tag] = chr(cp)
    return _FORMS


def shape(text):
    forms = _arabic_forms()
    items, i = [], 0
    while i < len(text):
        if text[i] == "ل" and i + 1 < len(text) and text[i + 1] in "آأإا":
            items.append(text[i:i + 2])  # لام + ألف = حرف واحد (لا)
            i += 2
        else:
            items.append(text[i])
            i += 1

    def to_next(it):
        return it == "\u0640" or "initial" in forms.get(it, {})

    def to_prev(it):
        return it == "\u0640" or "final" in forms.get(it, {})

    out = []
    for k, it in enumerate(items):
        fm = forms.get(it)
        if not fm:
            out.append(it)
            continue
        prev_ok = k > 0 and to_next(items[k - 1]) and to_prev(it)
        next_ok = k + 1 < len(items) and to_next(it) and to_prev(items[k + 1])
        tag = "medial" if prev_ok and next_ok else "final" if prev_ok else "initial" if next_ok else "isolated"
        out.append(fm.get(tag) or fm.get("isolated") or it)
    return "".join(out)


@lru_cache(maxsize=50000)
def visual(text, force=False):
    """النص مشكّل وبترتيب العرض (يسار←يمين) حتى ينرسم صح بالـPDF.
    force=True: الخلية عربية فنرتّب حتى السطر اللي ما بيه حروف عربية (مثل «... 0780»)."""
    s = shape(str(text))
    return _reorder(s) if force or _AR_LETTER.search(s) else s


# ======================================================================
#                 قراءة الكشوفات (صيغة برايم) والواصل
# ======================================================================
def _cached(fn):
    """كاش لقراءة الملف (إذا نسخة ستريملت تدعمه) حتى ما ينقرأ كل مرة."""
    deco = getattr(st, "cache_data", None)
    return deco(show_spinner=False)(fn) if deco else fn


DEFAULT_COLS = dict(amount=0, notes=1, goods=2, pieces=3, phone=4, address=5, ship=6, store=7)


def header_map(cells):
    """إذا الصف هو سطر عناوين كشف برايم يرجّع مواقع الأعمدة، وإلا None."""
    m = {}
    for i, c in enumerate(cells):
        h = norm(c)
        if "مبلغ" in h:
            m["amount"] = i
        elif "ملاحظ" in h:
            m["notes"] = i
        elif "بضاع" in h:
            m["goods"] = i
        elif "قطع" in h:
            m["pieces"] = i
        elif "هاتف" in h:
            m["phone"] = i
        elif "عنوان" in h:
            m["address"] = i
        elif "رقم" in h and "شحن" in h:
            m["ship"] = i
        elif "متجر" in h:
            m["store"] = i
    return m if {"amount", "address", "store", "ship"} <= set(m) else None


def _head_info(page):
    """عدد الشحنات المكتوب واسم التاجر من أعلى الكشف."""
    declared, merchant = None, ""
    for raw in (page.extract_text() or "").split("\n")[:10]:
        line = fix_cell(raw)
        m = re.search(r"عدد الشحنات\s*:?\s*(\d+)", line)
        if m and declared is None:
            declared = int(m.group(1))
        m = re.search(r"التاجر\s*:\s*(.+)$", line)
        if m and not merchant:
            merchant = m.group(1).strip()
    return declared, merchant


def to_order(cells, cols):
    def get(key):
        i = cols.get(key)
        return cells[i] if i is not None and i < len(cells) else ""

    ship, phone = digits_only(get("ship")), digits_only(get("phone"))
    if not (ship or phone):
        return None  # مو طلب (سطر فاضي أو مجموع)
    return {
        "ship": ship,
        "store": get("store"),
        "address": get("address"),
        "phone": get("phone"),
        "pieces": get("pieces"),
        "goods": get("goods"),
        "notes": get("notes"),
        "amount": to_int(get("amount")),
    }


@_cached
def parse_manifest(data):
    """كشف بصيغة برايم -> (الطلبات ، عدد الشحنات المكتوب ، اسم التاجر)."""
    orders, declared, merchant, cols = [], None, "", None
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            if declared is None or not merchant:
                d, mer = _head_info(page)
                declared = d if declared is None else declared
                merchant = merchant or mer
            for table in page.extract_tables():
                for row in table:
                    cells = [fix_cell(c) for c in row]
                    hm = header_map(cells)
                    if hm:
                        cols = hm
                        continue
                    if cols is None:
                        continue
                    order = to_order(cells, cols)
                    if order:
                        orders.append(order)
    return orders, declared, merchant


def _arrived_cols(cells):
    """سطر عناوين كشف الواصل: عمود (رقم الوصل/رقم الشحنة) وعمود (المبلغ/مبلغ الشحنة)."""
    num_c, amt_c = [], []
    for i, c in enumerate(cells):
        h = norm(c)

        def has(kw):
            return kw in h or kw[::-1] in h

        if has("مبلغ"):
            amt_c.append((0 if has("شحن") else 1, i))
        if has("شحن") and has("رقم"):
            num_c.append((0, i))
        elif has("وصل"):
            num_c.append((1, i))
    if num_c and amt_c:
        return {"ship": min(num_c)[1], "amount": min(amt_c)[1]}
    return None


def _first_number(cell):
    toks = re.findall(r"\d+", str(cell or "").translate(_DIGITS))
    return next((t for t in toks if len(t) >= 4), toks[0] if toks else "")


def _lines_records(page):
    """إذا الواصل مو جدول بخطوط: نقرأ كل سطر ونطلع منه رقم الشحنة والمبلغ."""
    words = sorted(page.extract_words(x_tolerance=2, y_tolerance=2), key=lambda w: (w["top"], w["x0"]))
    rtl = any(_PRESENTATION.search(w["text"]) for w in words)
    rows, cur, top0 = [], [], None
    for w in words:
        if top0 is None or abs(w["top"] - top0) > 3:
            if cur:
                rows.append(cur)
            cur, top0 = [], w["top"]
        cur.append(w)
    if cur:
        rows.append(cur)
    recs = []
    for row in rows:
        nums = []  # (x, نص الرقم)
        for w in sorted(row, key=lambda w: w["x0"]):
            tt = w["text"].translate(_DIGITS)
            if re.fullmatch(r"\d{1,3}(,\d{3})+(\.\d+)?|\d+", tt):
                nums.append((w["x0"], tt))
        ships = [x for x in nums if re.fullmatch(r"\d{6,12}", x[1]) and not (len(x[1]) == 11 and x[1].startswith("07"))]
        if not ships:
            continue
        ship = max(ships, key=lambda x: len(x[1]))
        rest = [x for x in nums if x is not ship and len(re.sub(r"\D", "", x[1])) <= 9]
        comma = [x for x in rest if "," in x[1]]
        if comma:
            amt = comma[0][1]
        elif len(rest) == 1:
            amt = rest[0][1]
        elif rest:  # عربي: المبلغ غالباً أقصى اليسار
            amt = (rest[0] if rtl else rest[-1])[1]
        else:
            continue
        recs.append({"ship": ship[1], "amount": int(round(float(amt.replace(",", ""))))})
    return recs


@_cached
def parse_arrived(data):
    """كشف الواصل -> (قائمة {ship, amount} ، طريقة القراءة)."""
    recs, cols = [], None
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                for row in table:
                    cells = [fix_cell(c) for c in row]
                    c = _arrived_cols(cells)
                    if c:
                        cols = c
                        continue
                    if not cols or max(cols.values()) >= len(cells):
                        continue
                    ship = _first_number(cells[cols["ship"]])
                    if ship:
                        recs.append({"ship": ship, "amount": to_int(cells[cols["amount"]])})
        if recs:
            return recs, "جدول"
        for page in pdf.pages:
            recs.extend(_lines_records(page))
    return recs, ("نص" if recs else "ما انقرأ")


# ======================================================================
#                              المطابقة
# ======================================================================
def reconcile(out_orders, arrived, loose=False):
    """يطابق الطلبات (رقم الشحنة + المبلغ) مع الواصل.
    loose=True: الرقم موجود يكفي حتى لو المبلغ مختلف."""
    by_ship = {}
    for a in arrived:
        by_ship.setdefault(ship_key(a["ship"]), set()).add(a["amount"])
    out_keys = {ship_key(o["ship"]) for o in out_orders}
    matched, missing, mismatch, todo = [], [], [], []
    for o in out_orders:
        amts = by_ship.get(ship_key(o["ship"]))
        if amts is None:
            missing.append(o)
            todo.append(dict(o, status="غير موجود بالواصل"))
        elif o["amount"] in amts:
            matched.append(o)
        else:
            shown = " / ".join(f"{a:,}" for a in sorted(amts))
            mismatch.append(dict(o, arrived=shown))
            if loose:
                matched.append(o)
            else:
                todo.append(dict(o, status=f"المبلغ مختلف (بالواصل: {shown})"))
    arrived_only = [(k, sorted(v)) for k, v in by_ship.items() if k not in out_keys]
    return {"matched": matched, "missing": missing, "mismatch": mismatch,
            "todo": todo, "arrived_only": arrived_only, "arrived_n": len(by_ship)}


# ======================================================================
#                        رسم pdf المفقودات (نفس تخطيط كشف الصاعد)
# ======================================================================
# الأعمدة من اليمين لليسار بنفس عروض الكشف الأصلي
COLS = [("no", "#", 44.9), ("store", "المتجر", 89.6), ("ship", "رقم الشحنة", 71.8),
        ("address", "العنوان", 134.5), ("phone", "رقم الهاتف", 71.8), ("pieces", "عدد القطع", 44.8),
        ("goods", "البضاعة", 179.4), ("notes", "ملاحظات", 107.6), ("amount", "مبلغ الشحنة", 71.8)]
FS, LEAD, PAD, MIN_H = 9, 11, 3, 20


def _find_font(names):
    """يدور على الخط بجنب هذا الملف، وبعدين بمجلدات الخطوط المعروفة."""
    here = os.path.dirname(os.path.abspath(globals().get("__file__", ".")))
    folders = [here, os.path.join(here, "fonts"),
               "/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/dejavu", "/usr/share/fonts/TTF",
               "/Library/Fonts", "/System/Library/Fonts/Supplemental", "C:/Windows/Fonts"]
    for folder in folders:
        for name in names:
            path = os.path.join(folder, name)
            if os.path.isfile(path):
                return path
    return None


def _fonts():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    reg = _find_font(["DejaVuSans.ttf", "arial.ttf", "Arial.ttf", "tahoma.ttf"])
    bold = _find_font(["DejaVuSans-Bold.ttf", "arialbd.ttf", "Arial Bold.ttf", "tahomabd.ttf"])
    if not reg and not bold:
        raise RuntimeError("ما لكيت خط عربي — حط ملف DejaVuSans.ttf (و DejaVuSans-Bold.ttf) بنفس مكان الملف")
    reg, bold = reg or bold, bold or reg
    for name, path in (("TsRegular", reg), ("TsBold", bold)):
        if name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(name, path))
    return "TsRegular", "TsBold"


def build_missing_pdf(orders, merchant="", when=None, title="كشف المفقودات"):
    """يرسم كشف بنفس تخطيط كشوفات الصاعد ويرجّع الـPDF (bytes)."""
    try:
        from reportlab.lib.colors import HexColor, black
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.pdfbase.pdfmetrics import stringWidth
        from reportlab.pdfgen import canvas
    except ImportError:
        raise RuntimeError("ينقص مكتبة reportlab — ضيفها بملف requirements.txt") from None

    reg, bold = _fonts()
    when = when or datetime.now(IRAQ_TZ)
    W, H = landscape(A4)
    LIMIT, TOP_NEXT = 548.0, 24.0
    x_right = W - 12.9
    edges = [x_right]
    for _, _, w in COLS:
        edges.append(edges[-1] - w)

    def wrap(text, width):
        def fits(s):
            return stringWidth(visual(s), reg, FS) <= width

        lines, cur = [], ""
        for w in str(text).split():
            trial = f"{cur} {w}".strip()
            if fits(trial):
                cur = trial
                continue
            if cur:
                lines.append(cur)
            while len(w) > 1 and not fits(w):  # كلمة أطول من العمود: نقطعها
                k = len(w) - 1
                while k > 1 and not fits(w[:k]):
                    k -= 1
                lines.append(w[:k])
                w = w[k:]
            cur = w
        if cur:
            lines.append(cur)
        return lines or [""]

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(W, H))
    c.setTitle("Missing shipments")
    head_fill, fills = HexColor("#C0C0C0"), (HexColor("#FCFCFD"), HexColor("#ECECEC"))

    def cell(i, top, h, fill, lines):
        x_l, x_r = edges[i + 1], edges[i]
        c.setFillColor(fill)
        c.setStrokeColor(black)
        c.setLineWidth(0.5)
        c.rect(x_l, H - top - h, x_r - x_l, h, stroke=1, fill=1)
        c.setFillColor(black)
        c.setFont(reg, FS)
        start = top + (h - len(lines) * LEAD) / 2
        rtl = any(_AR_LETTER.search(ln) for ln in lines)
        for k, ln in enumerate(lines):
            c.drawRightString(x_r - PAD, H - (start + (k + 0.5) * LEAD) - FS * 0.36, visual(ln, rtl))

    def header_row(top):
        lines = [wrap(t, w - 2 * PAD) for _, t, w in COLS]
        h = max(len(ls) for ls in lines) * LEAD + 2 * PAD
        for i, ls in enumerate(lines):
            cell(i, top, h, head_fill, ls)
        return h

    def footer(n):
        c.setFillColor(black)
        c.setFont("Helvetica-Oblique", 6)
        c.drawCentredString(W / 2, 32, f"Page {n}")

    def put(s, x, y_top, align):
        c.setFillColor(black)
        c.setFont(reg, 10)
        v = visual(s)
        (c.drawRightString if align == "r" else c.drawString)(x, H - y_top, v)

    # أعلى الصفحة الأولى: يمين (الشركة/العنوان/العدد) ويسار (التاجر/التاريخ/المنفيست)
    date_line = f"بتاريخ : {WEEKDAYS[when.weekday()]} ,{when:%Y/%m/%d %H:%M}"
    for y, s in ((68, "برايم للتوصيل السريع"), (93, title), (113, f"عدد الشحنات : {len(orders)}")):
        put(s, W - 52, y, "r")
    for y, s in ((68, f"التاجر : {merchant}" if merchant else ""), (93, date_line), (113, "رقم المنفيست: 0")):
        if s:
            put(s, 52, y, "l")

    page, top = 1, 148.0
    top += header_row(top)
    max_lines = int((LIMIT - TOP_NEXT - 40) / LEAD)
    for idx, o in enumerate(orders, 1):
        vals = {"no": str(idx), "store": o.get("store", ""), "ship": o.get("ship", ""),
                "address": o.get("address", ""), "phone": o.get("phone", ""),
                "pieces": o.get("pieces", ""), "goods": o.get("goods", ""), "notes": o.get("notes", ""),
                "amount": f"{int(o.get('amount', 0)):,}"}
        cols = []
        for key, _, w in COLS:
            ls = wrap(vals[key], w - 2 * PAD)
            if len(ls) > max_lines:
                ls = ls[:max_lines]
                ls[-1] += " …"
            cols.append(ls)
        h = max(MIN_H, max(len(ls) for ls in cols) * LEAD + 2 * PAD)
        if top + h > LIMIT:
            footer(page)
            c.showPage()
            page, top = page + 1, TOP_NEXT
            top += header_row(top)
        for i, ls in enumerate(cols):
            cell(i, top, h, fills[idx % 2 == 0], ls)
        top += h
    footer(page)
    c.showPage()
    c.save()
    return buf.getvalue()


# ======================================================================
#                              الواجهة
# ======================================================================
CSS = """
<style>
.stApp { direction: rtl; text-align: right; }
.stApp h1, .stApp h2, .stApp h3, .stApp p, .stApp label, .stApp li { text-align: right; }
[data-testid="stMetric"] { text-align: right; }
[data-testid="stTable"] table { direction: rtl; }
/* الأعمدة: الأولى باليسار والثانية باليمين (الواصل باليمين) */
[data-testid="stHorizontalBlock"] { direction: ltr; }
[data-testid="stColumn"], [data-testid="column"] { direction: rtl; }
pre, code { direction: ltr; unicode-bidi: plaintext; text-align: start; }
</style>
"""


def show_df(df):
    try:
        st.dataframe(df, hide_index=True)
    except TypeError:  # نسخ ستريملت القديمة
        st.dataframe(df)


def load_manifests(files):
    """يقرأ كشوفات برايم (صاعد أو مفقودات) ويشيل المكرر برقم الشحنة."""
    orders, first, merchants = [], {}, []
    for idx, f in enumerate(files):
        try:
            found, declared, merchant = parse_manifest(f.getvalue())
        except Exception as e:  # noqa: BLE001
            st.error(f"ما كدرت أقرأ الملف «{f.name}»: {e}")
            continue
        if not found:
            st.warning(f"⚠️ «{f.name}»: ما لكيت جدول طلبات بصيغة كشف برايم.")
            continue
        if merchant:
            merchants.append(merchant)
        dups = []
        for o in found:
            key = ship_key(o["ship"])
            if key and key in first:
                dups.append((o["ship"], first[key]))
                continue
            if key:
                first[key] = (idx, f.name)
            orders.append(o)
        if declared is not None and declared != len(found):
            st.warning(f"⚠️ «{f.name}»: الكشف مكتوب بيه {declared} شحنة بس انقرأ {len(found)} — "
                       "راجع الملف قبل ما تعتمد النتيجة.")
        elif declared is not None:
            st.caption(f"✅ «{f.name}»: {len(found)} طلب (مطابق لعدد الشحنات بالكشف)")
        else:
            st.caption(f"📄 «{f.name}»: {len(found)} طلب")
        if dups:
            parts = [f"{ship} (أصله بـ " + ("نفس الملف" if i == idx else f"«{name}»") + ")"
                     for ship, (i, name) in dups[:5]]
            more = f" … و{len(dups) - 5} غيرها" if len(dups) > 5 else ""
            st.warning(f"⚠️ {len(dups)} طلب مكرر (نفس رقم الشحنة) بـ «{f.name}» انتجاهل وانحسب مرة وحدة: "
                       + " ، ".join(parts) + more)
    return orders, merchants


def load_arrived(files):
    recs = []
    for f in files:
        try:
            found, method = parse_arrived(f.getvalue())
        except Exception as e:  # noqa: BLE001
            st.error(f"ما كدرت أقرأ الملف «{f.name}»: {e}")
            continue
        if not found:
            st.warning(f"⚠️ «{f.name}»: ما كدرت أقرأ منه رقم الشحنة والمبلغ — ابعثلي عينة منه حتى أضبط القراءة.")
            continue
        st.caption(f"📄 «{f.name}»: {len(found)} سجل من الواصل (انقرأ كـ{method})")
        recs.extend(found)
    if recs:
        with st.expander("شنو قريت من الواصل (أول 10)"):
            show_df(pd.DataFrame([{"رقم الشحنة": r["ship"], "المبلغ": money(r["amount"])} for r in recs[:10]]))
    return recs


def header_merchant(merchants):
    uniq = sorted(set(merchants))
    return uniq[0] if len(uniq) == 1 else ("متعدد" if uniq else "")


def show_result(res, total_n, title, file_stub, merchants, labels):
    """ملخص المطابقة + جدول + زر تحميل pdf. labels = (كلمة المجموع، كلمة المتبقي)."""
    todo, matched = res["todo"], res["matched"]
    c1, c2, c3 = st.columns(3)
    c1.metric(labels[0], total_n)
    c2.metric("واصل ومطابق", len(matched))
    c3.metric(labels[1], len(todo))
    miss_sum = sum(o["amount"] for o in todo)
    c4, c5, c6 = st.columns(3)
    c4.metric("مجموع مبالغ " + labels[1], money(miss_sum))
    c5.metric("مبلغ مختلف", len(res["mismatch"]))
    c6.metric("وصل وما إله بالكشف", len(res["arrived_only"]))

    if res["mismatch"]:
        st.warning(f"⚠️ {len(res['mismatch'])} طلب رقمه موجود بالواصل بس المبلغ مختلف "
                   "(داخل بالمفقودات إلا إذا فعّلت خيار «الرقم يكفي»).")
        with st.expander("الطلبات اللي المبلغ مختلف"):
            show_df(pd.DataFrame([{"رقم الشحنة": o["ship"], "المتجر": o["store"],
                                   "مبلغ الكشف": money(o["amount"]), "مبلغ الواصل": o["arrived"]}
                                  for o in res["mismatch"]]))
    if res["arrived_only"]:
        with st.expander("وصلت بس ما موجودة بالكشوفات (رقم + مبلغ)"):
            show_df(pd.DataFrame([{"رقم الشحنة": k, "المبلغ": " / ".join(f"{a:,}" for a in v)}
                                  for k, v in res["arrived_only"]]))

    if not todo:
        st.success("✅ ما اكو مفقودات — كل الطلبات واصلة ومطابقة.")
        return
    zero = sum(1 for o in todo if o["amount"] == 0)
    if zero:
        st.info(f"ℹ️ منهم {zero} طلب مبلغه 0.")
    by_store = {}
    for o in todo:
        s = by_store.setdefault(o["store"] or "—", [0, 0])
        s[0] += 1
        s[1] += o["amount"]
    st.caption("حسب المتجر:")
    show_df(pd.DataFrame([{"المتجر": k, "العدد": v[0], "المجموع": money(v[1])} for k, v in by_store.items()]))
    show_df(pd.DataFrame([{"#": i, "رقم الشحنة": o["ship"], "المتجر": o["store"], "العنوان": o["address"],
                           "المبلغ": money(o["amount"]), "الحالة": o["status"]}
                          for i, o in enumerate(todo, 1)]))
    now = datetime.now(IRAQ_TZ)
    try:
        pdf = build_missing_pdf(todo, header_merchant(merchants), now, title)
    except Exception as e:  # noqa: BLE001
        st.error(f"ما كدرت أسوي الـPDF: {e}")
        return
    st.download_button(f"⬇️ تحميل pdf {file_stub.replace('_', ' ')}", data=pdf,
                       file_name=f"{file_stub}_{now:%Y-%m-%d}.pdf", mime="application/pdf")


def page_out_in():
    st.caption("ارفع كل كشوفات الصاعد (يسار) وكشوفات الواصل (يمين). المطابقة برقم الشحنة + المبلغ، "
               "واللي ما يطابق يطلع بـ pdf المفقودات.")
    col_out, col_in = st.columns(2)
    with col_out:
        out_files = st.file_uploader("كشوفات الصاعد (كلها)", type=["pdf"],
                                     accept_multiple_files=True, key="out_files")
    with col_in:
        in_files = st.file_uploader("كشوفات الواصل", type=["pdf"],
                                    accept_multiple_files=True, key="in_files")
    loose = st.checkbox("الرقم يكفي (اعتبره واصل حتى لو المبلغ مختلف)", key="loose1")
    if not out_files or not in_files:
        st.info("ارفع كشوفات الصاعد والواصل حتى تبدأ المطابقة.")
        return
    out_orders, merchants = load_manifests(out_files)
    arrived = load_arrived(in_files)
    if not out_orders or not arrived:
        return
    res = reconcile(out_orders, arrived, loose)
    show_result(res, len(out_orders), "كشف المفقودات", "المفقودات", merchants, ("عدد الصواعد", "مفقود"))


def page_in_missing():
    st.caption("ارفع كشوفات المفقودات اللي طلعت من القائمة الأولى (يسار) وكشف الواصل الجديد (يمين). "
               "اللي ينلقى بالواصل ينشال، والباقي يطلع بـ pdf جديد.")
    col_miss, col_in = st.columns(2)
    with col_miss:
        miss_files = st.file_uploader("كشوفات المفقودات", type=["pdf"],
                                      accept_multiple_files=True, key="miss_files")
    with col_in:
        in_files = st.file_uploader("كشوفات الواصل", type=["pdf"],
                                    accept_multiple_files=True, key="in2_files")
    loose = st.checkbox("الرقم يكفي (اعتبره واصل حتى لو المبلغ مختلف)", key="loose2")
    if not miss_files or not in_files:
        st.info("ارفع كشوفات المفقودات والواصل حتى تبدأ المطابقة.")
        return
    miss_orders, merchants = load_manifests(miss_files)
    arrived = load_arrived(in_files)
    if not miss_orders or not arrived:
        return
    res = reconcile(miss_orders, arrived, loose)
    show_result(res, len(miss_orders), "كشف المفقودات المتبقية", "المفقودات_المتبقية", merchants,
                ("كان مفقود", "باقي مفقود"))


def main():
    st.set_page_config(page_title="تصفية الشحنات", page_icon="🧾")
    st.markdown(CSS, unsafe_allow_html=True)
    st.title("🧾 تصفية الشحنات [يوسف اسطورة]")
    menu = st.radio("القائمة", ["صاعد وواصل", "واصل ومفقودات"], horizontal=True)
    if menu == "صاعد وواصل":
        page_out_in()
    else:
        page_in_missing()


if __name__ == "__main__":
    main()
