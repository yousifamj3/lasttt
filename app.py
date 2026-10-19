# -*- coding: utf-8 -*-
"""
حاسبة يوسف الأسطورة
--------------------
تقرأ كشوفات PDF (برايم) وتجمع الطلبات وتخصم التوصيل.

التشغيل:
    pip install streamlit pdfplumber
    streamlit run app.py
"""
import io
import re
import unicodedata
from collections import OrderedDict

import pandas as pd
import pdfplumber
import streamlit as st

# ======================================================================
#                              الإعدادات
#     كل الأرقام بالدينار. إذا تغيّر سعر تعدله من هنا بس.
# ======================================================================
REGIONS = ("محافظات", "بغداد", "موصل")


def F(provinces, baghdad, mosul):
    """سعر التوصيل حسب المنطقة: (محافظات ، بغداد ، موصل)"""
    return {"محافظات": provinces, "بغداد": baghdad, "موصل": mosul}


# ---------- القائمة الأولى: كل كشف يخص متجر واحد ----------
LIST1 = OrderedDict([
    ("اونيلا", F(7000, 6000, 5000)),
    ("روح",    F(7000, 6000, 5000)),
    ("نورا",   F(6000, 6000, 5000)),
    ("سارة",   F(6000, 6000, 5000)),
    ("ادينا",  F(7000, 6000, 5000)),
    ("فينوس",  F(6000, 6000, 5000)),
])

# ---------- القائمة الثانية: كشف فيه عدة متاجر، والنتيجة تنفصل لكل متجر ----------
# القاعدة = (الاسم بالنتيجة ، [كلمات يدور عليها باسم المتجر بالكشف] ، سعر التوصيل)
# السعر None = بدون خصم (المبلغ يبقى كما هو)
LIST2 = OrderedDict([
    ("متفرقة كولدن", {
        "rules": [
            ("شي براند",           ["شي براند"],  F(6000, 6000, 5000)),
            ("أزياء برو",          ["ازياء برو"], F(7000, 7000, 5000)),
            ("أزياء كاريزا",       ["كاريزا"],    F(7000, 7000, 5000)),
            ("زيزفونه",            ["زيزفونه"],   F(6000, 6000, 5000)),
            ("توتة",               ["توته"],      F(7000, 7000, 5000)),
            ("حذيفة براند",        ["حذيفه"],     F(6000, 6000, 5000)),
            ("Velure lingeri",     ["velure", "valure"], F(6000, 6000, 5000)),
            ("سوز",               ["سوز"],       F(6000, 6000, 5000)),
            ("سونامي",            ["سونامي"],    F(6000, 6000, 5000)),
            ("مازن",              ["مازن"],      F(8000, 7000, 5000)),
            ("طلبات متفرقة كولدن", ["متفرقه كولدن", "خارجيه متفرقه"], None),
        ],
        "others": None,        # أي متجر ثاني مو مذكور فوق: بدون خصم
        "warn_others": True,   # ويطلّع عليه تنبيه ⚠️ حتى تنتبه له
    }),
    ("خارجية متفرقة", {
        "rules": [
            ("أزياء رشا",     ["ازياء رشا"], F(6000, 6000, 5000)),
            ("مخور رشا",      ["مخور رشا"],  F(6000, 6000, 5000)),
            ("مكتبة الميثاق", ["الميثاق"],   F(3000, 3000, 3000)),
            ("طوق الحمامة", ["طوق الحمامة"], F(6000, 6000, 5000)),
            ("الحرمين", ["الحرمين"], F(6000, 6000, 5000)),
            ("ابن الاثير", ["ابن الاثير"], F(6000, 6000, 5000)),
            ("الكبيسي", ["الكبيسي"], F(6000, 6000, 5000)),
            ("عبد الرحمن", ["عبد الرحمن"], F(6000, 6000, 5000)),
            ("كنوز", ["كنوز"], F(6000, 6000, 5000)),
            ("المنهجية", ["المنهجية"], F(6000, 6000, 5000)),
            ("العلماء", ["العلماء"], F(6000, 6000, 5000)),
            ("المؤمنين", ["المؤمنين"], F(6000, 6000, 5000)),
            ("تبارك", ["تبارك"], F(6000, 6000, 5000)),
            ("خارجية متفرقة", ["خارجيه متفرقه", "متفرقه كولدن"], None),
        ],
        # باقي المكاتب: تنترك كما هي (بدون خصم).
        # إذا تريد عليهم خصم اكتب مثلاً:  F(6000, 6000, 5000)
        "others": None,
        "warn_others": False,
    }),
])

# ======================================================================
#                          أدوات النص العربي
# ======================================================================
_AR_LETTER = re.compile(r"[\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF]")
_PRESENTATION = re.compile(r"[\uFB50-\uFDFF\uFE70-\uFEFF]")
_MARKS = re.compile(r"[\u064B-\u065F\u0670\u0640]")  # تشكيل + تطويل
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def fix_cell(text):
    """pdfplumber يطلّع العربي مقلوب (ترتيب بصري) — هنا نرجّعه للترتيب الصحيح."""
    if not text:
        return ""
    visual = bool(_PRESENTATION.search(text))
    lines = []
    for line in str(text).split("\n"):
        words = line.split()
        if visual:
            words = [w[::-1] if _AR_LETTER.search(w) else w for w in words]
            words.reverse()
        lines.append(" ".join(words))
    out = unicodedata.normalize("NFKC", " ".join(l for l in lines if l))
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


def region_of(address):
    """أول كلمة بالعنوان هي المحافظة: بغداد / موصل / غيرها = محافظات."""
    words = norm(address).split()
    first = words[0] if words else ""
    if first.startswith("ال"):
        first = first[2:]
    if first == "بغداد":
        return "بغداد"
    if first == "موصل":
        return "موصل"
    return "محافظات"


# ======================================================================
#                            قراءة الـ PDF
# ======================================================================
DEFAULT_COLS = dict(amount=0, notes=1, goods=2, pieces=3, phone=4, address=5, ship=6, store=7)


def header_map(cells):
    """إذا الصف هو سطر العناوين يرجّع مواقع الأعمدة، وإلا None."""
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
    return m if {"amount", "address", "store"} <= set(m) else None


def declared_count(page):
    """عدد الشحنات المكتوب بأعلى الكشف (للتأكد إن ما فاتنا طلب)."""
    head = "\n".join((page.extract_text() or "").split("\n")[:8])
    m = re.search(r"عدد الشحنات\s*:?\s*(\d+)", fix_cell(head))
    return int(m.group(1)) if m else None


def to_order(cells, cols):
    def get(key):
        i = cols.get(key)
        return cells[i] if i is not None and i < len(cells) else ""

    ship, phone = digits_only(get("ship")), digits_only(get("phone"))
    if not (ship or phone):
        return None  # مو طلب (سطر فاضي أو مجموع)
    address = get("address")
    return {
        "ship": ship,
        "store": get("store"),
        "address": address,
        "phone": phone,
        "amount": to_int(get("amount")),
        "region": region_of(address),
        "fee": 0,
    }


def parse_pdf(data):
    """يرجّع (قائمة الطلبات ، عدد الشحنات المكتوب بالكشف)."""
    orders, declared, cols = [], None, None
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            if declared is None:
                declared = declared_count(page)
            for table in page.extract_tables():
                for row in table:
                    cells = [fix_cell(c) for c in row]
                    hm = header_map(cells)
                    if hm:
                        cols = hm
                        continue
                    order = to_order(cells, cols or DEFAULT_COLS)
                    if order:
                        orders.append(order)
    return orders, declared


# ======================================================================
#                              الحسابات
# ======================================================================
def money(n):
    return "\u200e" + f"{int(n):,}"


def describe_fees(fees):
    if not fees:
        return "بدون خصم"
    p, b, m = (fees[r] for r in REGIONS)
    if p == b == m:
        return f"{p:,} ثابت"
    if p == b:
        return f"{p:,} (موصل {m:,})"
    return f"محافظات {p:,} · بغداد {b:,} · موصل {m:,}"


def _words(text):
    """الاسم بعد التطبيع وحذف الرموز، محاط بمسافات حتى نقارن بالكلمة الكاملة."""
    return " " + re.sub(r"[\W_]+", " ", norm(text)).strip() + " "


def resolve_store(store, cfg):
    """يرجّع (الاسم ، سعر التوصيل ، هل مذكور بالقواعد ، الترتيب)."""
    s = _words(store)
    for rank, (display, keys, fees) in enumerate(cfg["rules"]):
        if any(_words(k) in s for k in keys):
            return display, fees, True, rank
    return store, cfg.get("others"), False, len(cfg["rules"])


def calc_list1(orders, fees):
    for o in orders:
        o["fee"] = fees[o["region"]]
    total = sum(o["amount"] for o in orders)
    fee_total = sum(o["fee"] for o in orders)
    rows = []
    for r in REGIONS:
        n = sum(1 for o in orders if o["region"] == r)
        if n:
            rows.append({"المنطقة": r, "عدد الطلبات": n,
                         "سعر التوصيل": money(fees[r]), "مجموع الخصم": money(n * fees[r])})
    return total, fee_total, total - fee_total, rows


def calc_list2(orders, cfg):
    groups = OrderedDict()
    for o in orders:
        display, fees, known, rank = resolve_store(o["store"], cfg)
        o["fee"] = fees[o["region"]] if fees else 0
        key = display if known else norm(display)
        g = groups.setdefault(key, {"name": display, "rank": rank, "known": known,
                                    "fees": fees, "n": 0, "gross": 0, "fee": 0})
        g["n"] += 1
        g["gross"] += o["amount"]
        g["fee"] += o["fee"]
    return sorted(groups.values(), key=lambda g: g["rank"])  # sorted ثابت: يحافظ على ترتيب الظهور


# ======================================================================
#                              الواجهة
# ======================================================================
CSS = """
<style>
.stApp { direction: rtl; text-align: right; }
.stApp h1, .stApp h2, .stApp h3, .stApp p, .stApp label, .stApp li { text-align: right; }
[data-testid="stMetric"] { text-align: right; }
[data-testid="stTable"] table { direction: rtl; }
pre, code { direction: ltr; unicode-bidi: plaintext; text-align: start; }
</style>
"""


def show_df(df):
    try:
        st.dataframe(df, hide_index=True)
    except TypeError:  # نسخ ستريملت القديمة
        st.dataframe(df)


def load_orders(files):
    orders, seen = [], set()
    for f in files:
        try:
            found, declared = parse_pdf(f.getvalue())
        except Exception as e:  # noqa: BLE001
            st.error(f"ما كدرت أقرأ الملف «{f.name}»: {e}")
            continue
        dup = 0
        for o in found:
            if o["ship"] and o["ship"] in seen:
                dup += 1
                continue
            seen.add(o["ship"])
            orders.append(o)
        if declared is not None and declared != len(found):
            st.warning(f"⚠️ «{f.name}»: الكشف مكتوب بيه {declared} شحنة بس انقرأ {len(found)} — "
                       "راجع الملف قبل ما تعتمد الحساب.")
        elif declared is not None:
            st.caption(f"✅ «{f.name}»: {len(found)} طلب (مطابق لعدد الشحنات بالكشف)")
        else:
            st.caption(f"📄 «{f.name}»: {len(found)} طلب")
        if dup:
            st.warning(f"⚠️ {dup} طلب مكرر بين الملفات انتجاهل (انحسب مرة وحدة).")
    return orders


def ask_orders(key):
    files = st.file_uploader("ارفع ملف الكشف (PDF)", type=["pdf"],
                             accept_multiple_files=True, key=key)
    if not files:
        st.info("ارفع الكشف حتى ينحسب.")
        return []
    orders = load_orders(files)
    if not orders:
        st.error("ما لكيت طلبات داخل الملف. تأكد انه كشف برايم الأصلي.")
    return orders


def zero_note(orders):
    z = sum(1 for o in orders if o["amount"] == 0)
    if z:
        st.info(f"ℹ️ فيه {z} طلب مبلغه 0 — انحسب عليه التوصيل مثل باقي الطلبات.")


def details_table(orders):
    df = pd.DataFrame([{
        "رقم الشحنة": o["ship"], "المتجر": o["store"], "المنطقة": o["region"],
        "العنوان": o["address"], "المبلغ": money(o["amount"]),
        "التوصيل": money(o["fee"]), "الصافي": money(o["amount"] - o["fee"]),
    } for o in orders])
    with st.expander("تفاصيل الطلبات واحد واحد (للتأكد)"):
        show_df(df)


def show_list1(name):
    fees = LIST1[name]
    st.caption("سعر التوصيل لكل طلب: " + describe_fees(fees))
    orders = ask_orders("up1")
    if not orders:
        return

    key = norm(name)
    foreign = [o for o in orders if key not in norm(o["store"])]
    if foreign:
        names = " ، ".join(sorted({o["store"] for o in foreign}))
        st.warning(f"⚠️ {len(foreign)} طلب باسم متجر غير «{name}»: {names} — "
                   "تأكد انك مختار الاسم الصحيح.")

    total, fee_total, net, rows = calc_list1(orders, fees)
    c1, c2, c3 = st.columns(3)
    c1.metric("عدد الطلبات", len(orders))
    c2.metric("مجموع الكشف", money(total))
    c3.metric("خصم التوصيل", money(fee_total))
    st.success(f"✅ الصافي لـ {name}:  {money(net)} د.ع")
    st.table(pd.DataFrame(rows).set_index("المنطقة"))
    zero_note(orders)
    details_table(orders)
    st.code(f"{name}\nعدد الطلبات: {len(orders)}\nمجموع الكشف: {money(total)}\n"
            f"خصم التوصيل: {money(fee_total)}\nالصافي: {money(net)}", language=None)


def show_list2(name):
    cfg = LIST2[name]
    orders = ask_orders("up2")
    if not orders:
        return

    groups = calc_list2(orders, cfg)
    rows, lines = [], [name]
    tot_n = tot_gross = tot_fee = 0
    unknown = []
    for g in groups:
        flag = " ⚠️" if (not g["known"] and cfg.get("warn_others")) else ""
        if flag:
            unknown.append(g["name"])
        net = g["gross"] - g["fee"]
        rows.append({"المتجر": g["name"] + flag, "الطلبات": g["n"],
                     "المجموع": money(g["gross"]), "الخصم": money(g["fee"]),
                     "الصافي": money(net), "نوع الخصم": describe_fees(g["fees"])})
        lines.append(f"{g['name']} ({g['n']} طلب): {money(net)}")
        tot_n += g["n"]
        tot_gross += g["gross"]
        tot_fee += g["fee"]
    rows.append({"المتجر": "الإجمالي", "الطلبات": tot_n, "المجموع": money(tot_gross),
                 "الخصم": money(tot_fee), "الصافي": money(tot_gross - tot_fee), "نوع الخصم": ""})
    lines.append(f"الإجمالي: {money(tot_gross - tot_fee)}")

    if unknown:
        st.warning("⚠️ هذي المتاجر مو مذكورة بالقواعد فانحسبت بدون خصم: " + " ، ".join(unknown))
    c1, c2, c3 = st.columns(3)
    c1.metric("عدد الطلبات", tot_n)
    c2.metric("المجموع", money(tot_gross))
    c3.metric("الخصم", money(tot_fee))
    st.success(f"✅ الصافي الكلي:  {money(tot_gross - tot_fee)} د.ع")
    st.table(pd.DataFrame(rows).set_index("المتجر"))
    zero_note(orders)
    details_table(orders)
    st.code("\n".join(lines), language=None)


def main():
    st.set_page_config(page_title="حاسبة يوسف الأسطورة", page_icon="🧮")
    st.markdown(CSS, unsafe_allow_html=True)
    st.title("🧮 حاسبة يوسف الأسطورة")

    menu = st.radio("القائمة", ["القائمة الأولى", "القائمة الثانية"], horizontal=True)
    if menu == "القائمة الأولى":
        show_list1(st.selectbox("اختر المتجر", list(LIST1)))
    else:
        show_list2(st.selectbox("اختر الكشف", list(LIST2)))


if __name__ == "__main__":
    main()
