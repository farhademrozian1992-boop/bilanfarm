import os
import json
import datetime
from zoneinfo import ZoneInfo
import requests
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

TEHRAN_TZ = ZoneInfo("Asia/Tehran")


def today_tehran():
    return datetime.datetime.now(TEHRAN_TZ).date()


# ====== تنظیمات ======
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8179949701:AAHz5WOFKRKUZzfHywxDOdsn22NQXGGwRXU")
API_URL = os.environ.get("API_URL", "https://script.google.com/macros/s/AKfycbwgu8X3V57pF3EuOPPD7RiEw1K5A0UIO0M3B-F1yJ6AMHXF78v1xWciSz5EDFFmpA7M/exec")
API_TOKEN = os.environ.get("API_TOKEN", "emrozian5852F")
# ======================

TYPE_MAP = {"💰 درآمد": "income", "🏦 قسط وام": "loan", "🛠 نگهداری": "maintenance", "💸 برداشت": "withdrawal"}
TYPE_LABELS = {"income": "درآمد", "loan": "قسط وام", "maintenance": "نگهداری", "withdrawal": "برداشت"}
DELETE_LABEL = "🗑 حذف ثبت"

FLOWS = {
    "income": ["amount", "date"],
    "loan": ["bank", "amount", "date"],
    "maintenance": ["amount", "date", "note"],
    "withdrawal": ["person", "amount", "date"],
}

MAIN_KB = ReplyKeyboardMarkup(
    [["💰 درآمد", "🏦 قسط وام"], ["🛠 نگهداری", "💸 برداشت"], [DELETE_LABEL]],
    resize_keyboard=True,
)
BANK_KB = ReplyKeyboardMarkup([["ملی مهربانی", "کارت اعتباری"]], resize_keyboard=True, one_time_keyboard=True)
PERSON_KB = ReplyKeyboardMarkup([["آبی", "فرهاد"]], resize_keyboard=True, one_time_keyboard=True)
DATE_KB = ReplyKeyboardMarkup([["📅 امروز"]], resize_keyboard=True)

# حافظه‌ی ساده‌ی وضعیت هر چت (در حافظه؛ با ری‌استارت پاک می‌شه)
STATE = {}

FA_MONTHS = ['فروردین', 'اردیبهشت', 'خرداد', 'تیر', 'مرداد', 'شهریور', 'مهر', 'آبان', 'آذر', 'دی', 'بهمن', 'اسفند']


def to_en_digits(s):
    fa = '۰۱۲۳۴۵۶۷۸۹'
    ar = '٠١٢٣٤٥٦٧٨٩'
    s = str(s)
    for i, ch in enumerate(fa):
        s = s.replace(ch, str(i))
    for i, ch in enumerate(ar):
        s = s.replace(ch, str(i))
    return s


def fa_digits(s):
    en = '0123456789'
    fa = '۰۱۲۳۴۵۶۷۸۹'
    return ''.join(fa[en.index(c)] if c in en else c for c in str(s))


def g2j(gy, gm, gd):
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy2 = gy + 1 if gm > 2 else gy
    days = 355666 + (365 * gy) + (gy2 + 3) // 4 - (gy2 + 99) // 100 + (gy2 + 399) // 400 + gd + g_d_m[gm - 1]
    jy = -1595 + (33 * (days // 12053))
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    jm = 1 + days // 31 if days < 186 else 7 + (days - 186) // 30
    jd = 1 + (days % 31 if days < 186 else (days - 186) % 30)
    return jy, jm, jd


def j2g(jy, jm, jd):
    jy1 = jy + 1595
    days = -355668 + (365 * jy1) + (jy1 // 33) * 8 + ((jy1 % 33) + 3) // 4 + jd + ((jm - 1) * 31 if jm < 7 else (jm - 7) * 30 + 186)
    gy = 400 * (days // 146097)
    days %= 146097
    if days > 36524:
        days -= 1
        gy += 100 * (days // 36524)
        days %= 36524
        if days >= 365:
            days += 1
    gy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        gy += (days - 1) // 365
        days = (days - 1) % 365
    gd = days + 1
    leap = (gy % 4 == 0 and gy % 100 != 0) or (gy % 400 == 0)
    sal_a = [0, 31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    gm = 0
    for gm in range(13):
        v = sal_a[gm]
        if gd <= v:
            break
        gd -= v
    return gy, gm, gd


def is_leap_jalali(jy):
    g = j2g(jy, 12, 30)
    back = g2j(*g)
    return back[1] == 12 and back[2] == 30


def days_in_jalali_month(jy, jm):
    if jm <= 6:
        return 31
    if jm <= 11:
        return 30
    return 30 if is_leap_jalali(jy) else 29


def to_fa_date(iso):
    try:
        iso = str(iso)[:10]
        gy, gm, gd = map(int, iso.split('-'))
        jy, jm, jd = g2j(gy, gm, gd)
        return fa_digits(f"{jy}/{jm:02d}/{jd:02d}")
    except Exception:
        return str(iso)


def parse_jalali_date(text):
    t = to_en_digits(text).strip().replace('-', '/').replace('.', '/').replace(' ', '/')
    parts = [p for p in t.split('/') if p]
    if len(parts) != 3:
        return None
    try:
        jy, jm, jd = int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError:
        return None
    if jy < 1300 or jy > 1500:
        return None
    if not (1 <= jm <= 12):
        return None
    if not (1 <= jd <= days_in_jalali_month(jy, jm)):
        return None
    gy, gm, gd = j2g(jy, jm, jd)
    return f"{gy:04d}-{gm:02d}-{gd:02d}"


def fmt_num(n):
    try:
        return fa_digits(f"{float(n):,.0f}")
    except Exception:
        return fa_digits(n)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    STATE.pop(update.effective_chat.id, None)
    await update.message.reply_text("سلام! یکی از گزینه‌ها رو انتخاب کن:", reply_markup=MAIN_KB)


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    STATE.pop(update.effective_chat.id, None)
    await update.message.reply_text("لغو شد.", reply_markup=MAIN_KB)


async def submit_tx(update, tx):
    payload = {"action": "add", "token": API_TOKEN, **tx}
    r = requests.post(API_URL, data=json.dumps(payload),
                       headers={"Content-Type": "text/plain;charset=utf-8"}, timeout=15)
    r.raise_for_status()
    await update.message.reply_text("✅ ثبت شد.", reply_markup=MAIN_KB)


async def fetch_rows():
    r = requests.get(API_URL, params={"action": "list", "token": API_TOKEN}, timeout=15)
    return r.json()


def step_prompt(step):
    if step == "amount":
        return "مبلغ رو به تومان بفرست (فقط عدد):", None
    if step == "date":
        return "تاریخ رو به شمسی بفرست (مثال: ۱۴۰۳/۰۷/۱۰) یا دکمه‌ی پایین رو بزن:", DATE_KB
    if step == "bank":
        return "کدوم بانک؟", BANK_KB
    if step == "person":
        return "برداشت برای کیه؟", PERSON_KB
    if step == "note":
        return 'بابت چی بود؟ (توضیح) - یا بنویس "رد کن"', None
    return "", None


async def start_flow(update, chat_id, ttype):
    flow = FLOWS[ttype]
    STATE[chat_id] = {"mode": "flow", "type": ttype, "flow": flow, "idx": 0, "data": {}}
    text, kb = step_prompt(flow[0])
    await update.message.reply_text(text, reply_markup=kb)


async def advance_flow(update, chat_id, state):
    state["idx"] += 1
    flow = state["flow"]
    if state["idx"] >= len(flow):
        d = state["data"]
        note = d.get("note") or d.get("bank") or ""
        tx = {
            "type": state["type"],
            "amount": d["amount"],
            "date": d["date"],
            "person": d.get("person", ""),
            "note": note,
        }
        STATE.pop(chat_id, None)
        try:
            await submit_tx(update, tx)
        except Exception:
            await update.message.reply_text("❌ خطا در ثبت. دوباره تلاش کن.", reply_markup=MAIN_KB)
        return
    text, kb = step_prompt(flow[state["idx"]])
    await update.message.reply_text(text, reply_markup=kb)


async def start_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    try:
        rows = await fetch_rows()
    except Exception:
        await update.message.reply_text("خطا در دریافت اطلاعات.", reply_markup=MAIN_KB)
        return
    if isinstance(rows, dict) and rows.get("error"):
        await update.message.reply_text("خطا: " + rows["error"], reply_markup=MAIN_KB)
        return
    rows.sort(key=lambda r: (r.get("date", ""), r.get("ts", 0)), reverse=True)
    rows = rows[:20]
    if not rows:
        await update.message.reply_text("هیچ ثبتی وجود نداره.", reply_markup=MAIN_KB)
        return
    id_map = {}
    lines = ["کدوم ثبت رو می‌خوای حذف کنی؟ شماره‌شو بفرست:", ""]
    for i, row in enumerate(rows, start=1):
        id_map[str(i)] = row.get("id")
        label = TYPE_LABELS.get(row.get("type"), row.get("type"))
        person = row.get("person")
        person_txt = f" ({'آبی' if person == 'abi' else 'فرهاد'})" if person else ""
        note = row.get("note") or ""
        note_txt = f" - {note}" if note else ""
        lines.append(f"{fa_digits(i)}. {to_fa_date(row.get('date',''))} | {label}{person_txt} | {fmt_num(row.get('amount'))}{note_txt}")
    STATE[chat_id] = {"mode": "delete_select", "map": id_map}
    await update.message.reply_text("\n".join(lines), reply_markup=ReplyKeyboardRemove())


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = (update.message.text or "").strip()

    # دکمه‌های اصلی همیشه در اولویت‌اند، حتی وسط یک فرآیند ناتمام
    if text in TYPE_MAP:
        await start_flow(update, chat_id, TYPE_MAP[text])
        return
    if text == DELETE_LABEL:
        await start_delete(update, context)
        return
    if text in ("/cancel", "لغو"):
        await cancel(update, context)
        return

    state = STATE.get(chat_id)
    if not state:
        await update.message.reply_text("از دکمه‌های پایین استفاده کن.", reply_markup=MAIN_KB)
        return

    if state.get("mode") == "delete_select":
        sel = to_en_digits(text).strip()
        tx_id = state.get("map", {}).get(sel)
        if not tx_id:
            await update.message.reply_text("شماره نامعتبره. دوباره یکی از شماره‌های لیست رو بفرست یا بنویس لغو.")
            return
        STATE.pop(chat_id, None)
        try:
            r = requests.post(API_URL, data=json.dumps({"action": "delete", "token": API_TOKEN, "id": tx_id}),
                               headers={"Content-Type": "text/plain;charset=utf-8"}, timeout=15)
            r.raise_for_status()
            await update.message.reply_text("✅ حذف شد.", reply_markup=MAIN_KB)
        except Exception:
            await update.message.reply_text("❌ خطا در حذف. دوباره تلاش کن.", reply_markup=MAIN_KB)
        return

    # مرحله‌ی فعلی در یک فرآیند ثبت تراکنش
    flow = state["flow"]
    step = flow[state["idx"]]

    if step == "amount":
        try:
            amount = int(to_en_digits(text).replace(",", "").replace("،", "").strip())
            if amount <= 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text("لطفاً فقط یک عدد درست بفرست.")
            return
        state["data"]["amount"] = amount
        await advance_flow(update, chat_id, state)
        return

    if step == "date":
        if text == "📅 امروز":
            iso = today_tehran().isoformat()
        else:
            iso = parse_jalali_date(text)
        if not iso:
            await update.message.reply_text("تاریخ معتبر نیست. مثال درست: ۱۴۰۳/۰۷/۱۰ (یا دکمه‌ی امروز رو بزن)", reply_markup=DATE_KB)
            return
        state["data"]["date"] = iso
        await advance_flow(update, chat_id, state)
        return

    if step == "bank":
        if text not in ("ملی مهربانی", "کارت اعتباری"):
            await update.message.reply_text("لطفاً یکی از دکمه‌ها رو بزن.", reply_markup=BANK_KB)
            return
        state["data"]["bank"] = text
        await advance_flow(update, chat_id, state)
        return

    if step == "person":
        if text not in ("آبی", "فرهاد"):
            await update.message.reply_text("لطفاً یکی از دکمه‌ها رو بزن.", reply_markup=PERSON_KB)
            return
        state["data"]["person"] = "abi" if text == "آبی" else "feri"
        await advance_flow(update, chat_id, state)
        return

    if step == "note":
        note = "" if text == "رد کن" else text
        state["data"]["note"] = note
        await advance_flow(update, chat_id, state)
        return


def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    print("Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
