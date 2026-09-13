# ═══════════════════════════════════════════════════════════════
# 🔧 تهيئة Asyncio
# ═══════════════════════════════════════════════════════════════
import asyncio
import sys
import warnings

warnings.filterwarnings("ignore", category=DeprecationWarning)

try:
    _loop = asyncio.get_running_loop()
except RuntimeError:
    _loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_loop)

# ═══════════════════════════════════════════════════════════════
import os
import io
import re
from datetime import datetime
from collections import OrderedDict

from pyrogram import Client, filters
from pyrogram.types import (
    Message, ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
)
from pyrogram.errors import FloodWait

# ==================== الإعدادات ====================
API_ID = int(os.getenv("API_ID", "20084899"))
API_HASH = os.getenv("API_HASH", "a860b181d2f15d0473ee309523a9fc19")
BOT_TOKEN = os.getenv("BOT_TOKEN", "8839466034:AAF_ONFjOcoOSrcQtiTRrtWlTQJCDtR-Cxw")

BOT_SESSION_STRING = os.getenv("BOT_SESSION_STRING", "").strip()
USER_SESSION_STRING = os.getenv("USER_SESSION_STRING", "").strip()

OWNER_IDS = [int(x) for x in os.getenv("OWNER_IDS", "8604513259,7105884739").split(",") if x.strip()]

DEFAULT_CHANNEL_ID = -1004457550992
DEFAULT_CHANNEL_LINK = "https://t.me/+TGlg7tFi1SIyOTJh"

MAX_FILE_SIZE = 1024 * 1024 * 1024
DEFAULT_DEST = OWNER_IDS[0] if OWNER_IDS else None

BACKFILL_ENABLED = os.getenv("BACKFILL_ENABLED", "1") == "1"
BACKFILL_LIMIT = int(os.getenv("BACKFILL_LIMIT", "1000000"))

NETWORK_RETRY_DELAY = 10
DOWNLOAD_ATTEMPTS = 5
PAUSE_BETWEEN_FILES = 2.0
PAUSE_BETWEEN_CHUNKS = 15.0

BATCH_SIZE = int(os.getenv("BATCH_SIZE", "5000"))
FLUSH_INTERVAL = int(os.getenv("FLUSH_INTERVAL", "3600"))

ULP_PATTERNS = [
    re.compile(r"repost\s*from", re.IGNORECASE),
    re.compile(r"meowleak", re.IGNORECASE),
]

BUTTON_TEXTS = {
    "🎛 لوحة التحكم", "👁 المراقبة", "📊 الإحصائيات", "📈 حالة البوت",
    "🔍 بحث دومين", "📤 رفع ULP", "📂 فرز ULP", "🎁 هدية",
    "✅ تفعيل", "🚫 إغلاق", "💰 رصيدي", "📋 آخر العمليات",
}

# ==================== الحالة العامة (RAM) ====================
_monitor_chat_id_cache = None
_monitor_chat_obj = None
_userbot_ready = False
_backfill_running = False
_bot_running = False

_pending_lock = asyncio.Lock()
_pending_list = []
_batch_num = 0

_combos_lock = asyncio.Lock()
_combos_set = set()
COMBOS_MAX = int(os.getenv("COMBOS_MAX", "200000"))

_processed_lock = asyncio.Lock()
_processed_set = OrderedDict()

# ==================== ملف قائمة المعالجة على القرص ====================
PROCESSED_FILE = os.getenv("PROCESSED_FILE", "/data/processed.txt")
PROCESSED_DIR = os.path.dirname(PROCESSED_FILE)
if PROCESSED_DIR:
    try:
        os.makedirs(PROCESSED_DIR, exist_ok=True)
    except Exception as e:
        print(f"[PROCESSED DIR] {e}")

def _load_processed_from_disk():
    if not os.path.exists(PROCESSED_FILE):
        print(f"[PROCESSED] لا يوجد ملف سابق في {PROCESSED_FILE}")
        return
    try:
        count = 0
        with open(PROCESSED_FILE, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                key = line.strip()
                if key:
                    _processed_set[key] = True
                    count += 1
        print(f"[PROCESSED] ✅ تم تحميل {count:,} معرف من القرص")
    except Exception as e:
        print(f"[PROCESSED LOAD ERROR] {e}")

def _append_processed_to_disk(key):
    try:
        with open(PROCESSED_FILE, "a", encoding="utf-8") as f:
            f.write(f"{key}\n")
    except Exception as e:
        print(f"[PROCESSED APPEND ERROR] {e}")

async def is_already_processed(identifier):
    async with _processed_lock:
        return str(identifier) in _processed_set

async def mark_as_processed(identifier):
    async with _processed_lock:
        key = str(identifier)
        if key in _processed_set:
            return
        _processed_set[key] = True
        await asyncio.to_thread(_append_processed_to_disk, key)

async def reset_processed():
    async with _processed_lock:
        count = len(_processed_set)
        _processed_set.clear()
        try:
            if os.path.exists(PROCESSED_FILE):
                os.remove(PROCESSED_FILE)
        except Exception as e:
            print(f"[RESET ERROR] {e}")
        return count

# تحميل فوري عند الإقلاع
_load_processed_from_disk()

# ==================== إعدادات ثابتة في RAM ====================
_settings = {
    "monitor_domain": os.getenv("MONITOR_DOMAIN", ""),
    "monitor_enabled": "1",
    "saved_channel_id": "",
    "total_operations": "0",
}

def get_setting(key, default=""):
    return _settings.get(key, default)

def set_setting(key, value):
    _settings[key] = str(value)

def del_setting(key):
    _settings.pop(key, None)

def is_monitor_enabled():
    return _settings.get("monitor_enabled", "1") == "1"

def get_monitor_domain():
    return _settings.get("monitor_domain", "").strip().lower()

# ==================== قائمة الانتظار (RAM) ====================
async def pending_add(accounts):
    if not accounts:
        return 0
    async with _pending_lock:
        added = 0
        for a in accounts:
            a = a.strip()
            if a:
                _pending_list.append(a)
                added += 1
        return added

def pending_count():
    return len(_pending_list)

async def pending_get_all():
    async with _pending_lock:
        return list(_pending_list)

async def pending_clear():
    async with _pending_lock:
        _pending_list.clear()

# ==================== كومبوهات البحث (RAM) ====================
async def combos_add(lines):
    if not lines:
        return 0
    async with _combos_lock:
        added = 0
        for l in lines:
            l = l.strip()
            if l and l not in _combos_set:
                if len(_combos_set) >= COMBOS_MAX:
                    try:
                        _combos_set.pop()
                    except Exception:
                        pass
                _combos_set.add(l)
                added += 1
        return added

async def combos_search(domain, limit):
    domain_lower = domain.lower()
    results = []
    async with _combos_lock:
        for c in list(_combos_set):
            if domain_lower in c.lower():
                results.append(c)
                if len(results) >= limit:
                    break
        for r in results:
            _combos_set.discard(r)
    return results

async def combos_count(domain=None):
    async with _combos_lock:
        if domain is None:
            return len(_combos_set)
        d = domain.lower()
        return sum(1 for c in _combos_set if d in c.lower())

# ==================== دوال مساعدة ====================
def extract_email_pass(line: str) -> str:
    line = line.strip()
    if not line:
        return line
    parts = line.split(':')
    if len(parts) >= 3:
        return f"{parts[-2]}:{parts[-1]}"
    if len(parts) == 2:
        return f"{parts[0]}:{parts[1]}"
    return line

def clean_line(line: str) -> str:
    line = line.strip()
    if not line:
        return ""
    parts = [p.strip() for p in line.split(":")]
    if len(parts) >= 3:
        email_idx = -1
        for i, p in enumerate(parts):
            if "@" in p:
                email_idx = i
                break
        if email_idx >= 0 and email_idx < len(parts) - 1:
            return f"{parts[email_idx]}:{parts[email_idx + 1]}"
        return f"{parts[-2]}:{parts[-1]}"
    if len(parts) == 2:
        return f"{parts[0]}:{parts[1]}"
    return line

def sort_file_by_domain(file_path: str, domain_filter: str, output_path: str) -> int:
    enc = 'utf-8'
    for e in ['utf-8-sig', 'utf-8', 'latin-1', 'cp1252', 'utf-16']:
        try:
            with open(file_path, 'r', encoding=e, errors='ignore') as f:
                f.read(2048)
            enc = e
            break
        except Exception:
            continue
    target = domain_filter.lower().strip()
    matched = 0
    seen = set()
    with open(output_path, 'w', encoding='utf-8') as out:
        with open(file_path, 'r', encoding=enc, errors='ignore') as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                if target in s.lower():
                    cleaned = clean_line(s)
                    if cleaned and cleaned not in seen:
                        seen.add(cleaned)
                        out.write(cleaned + "\n")
                        matched += 1
    return matched

def increment_operations():
    try:
        _settings["total_operations"] = str(int(_settings.get("total_operations", "0")) + 1)
    except Exception:
        _settings["total_operations"] = "1"

def get_total_operations():
    try:
        return int(_settings.get("total_operations", "0"))
    except Exception:
        return 0

# ==================== العملاء ====================
if BOT_SESSION_STRING:
    app = Client(
        "combo_bot",
        api_id=API_ID,
        api_hash=API_HASH,
        session_string=BOT_SESSION_STRING,
        sleep_threshold=120,
        max_concurrent_transmissions=1,
    )
else:
    app = Client(
        "combo_bot",
        api_id=API_ID,
        api_hash=API_HASH,
        bot_token=BOT_TOKEN,
        sleep_threshold=120,
        max_concurrent_transmissions=1,
    )

userbot = None
if USER_SESSION_STRING:
    userbot = Client(
        "account",
        api_id=API_ID,
        api_hash=API_HASH,
        session_string=USER_SESSION_STRING,
        sleep_threshold=120,
        max_concurrent_transmissions=1,
    )

# ==================== حل القناة ====================
async def _resolve_monitor_chat(client: Client):
    global _monitor_chat_id_cache, _monitor_chat_obj

    if _monitor_chat_id_cache is not None and _monitor_chat_obj is not None:
        return _monitor_chat_id_cache

    sources = [
        ("ID ثابت", DEFAULT_CHANNEL_ID),
        ("الرابط الثابت", DEFAULT_CHANNEL_LINK),
        ("ID محفوظ", get_setting("saved_channel_id", "")),
    ]

    for label, source in sources:
        if source is None or source == "":
            continue
        source_str = str(source).strip()
        if not source_str:
            continue
        print(f"🎯 محاولة: {label} → {source_str[:60]}")
        if source_str.lstrip("-").isdigit():
            try:
                cid = int(source_str)
                chat = await client.get_chat(cid)
                _monitor_chat_obj = chat
                _monitor_chat_id_cache = chat.id
                set_setting("saved_channel_id", str(chat.id))
                print(f"✅ [{label}] {chat.title} ({chat.id})")
                return chat.id
            except Exception as e:
                print(f"⚠️ [{label}] فشل: {str(e)[:80]}")
                continue
        try:
            try:
                chat = await client.join_chat(source_str)
                _monitor_chat_obj = chat
                _monitor_chat_id_cache = chat.id
                set_setting("saved_channel_id", str(chat.id))
                print(f"✅ [{label}] join → {chat.title} ({chat.id})")
                return chat.id
            except Exception as e:
                err = str(e)
                if "USER_ALREADY_PARTICIPANT" in err:
                    try:
                        hash_part = source_str.split("+")[-1] if "+" in source_str else source_str
                        chat = await client.get_chat(hash_part)
                        _monitor_chat_obj = chat
                        _monitor_chat_id_cache = chat.id
                        set_setting("saved_channel_id", str(chat.id))
                        print(f"✅ [{label}] get_chat → {chat.title} ({chat.id})")
                        return chat.id
                    except Exception as e2:
                        print(f"⚠️ [{label}] get_chat: {str(e2)[:80]}")
        except Exception as e:
            print(f"⚠️ [{label}] خطأ: {str(e)[:80]}")

    _monitor_chat_id_cache = DEFAULT_CHANNEL_ID
    print(f"⚠️ Fallback: {_monitor_chat_id_cache}")
    return _monitor_chat_id_cache

# ==================== الكيبوردات ====================
def owner_reply_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("🎛 لوحة التحكم"), KeyboardButton("👁 المراقبة")],
        [KeyboardButton("📊 الإحصائيات"), KeyboardButton("📈 حالة البوت")],
        [KeyboardButton("🔍 بحث دومين"), KeyboardButton("📤 رفع ULP")],
        [KeyboardButton("📂 فرز ULP"), KeyboardButton("🎁 هدية")],
        [KeyboardButton("✅ تفعيل"), KeyboardButton("🚫 إغلاق")]
    ], resize_keyboard=True)

def owner_main_inline():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👁 المراقبة", callback_data="menu_monitor"),
         InlineKeyboardButton("📊 الإحصائيات", callback_data="menu_stats")],
        [InlineKeyboardButton("📚 إعادة المسح", callback_data="menu_rescan")],
        [InlineKeyboardButton("🔍 بحث دومين", callback_data="menu_search"),
         InlineKeyboardButton("📤 رفع ملف ULP", callback_data="menu_upload")],
        [InlineKeyboardButton("📂 فرز ULP", callback_data="menu_filter"),
         InlineKeyboardButton("🎁 إنشاء هدية", callback_data="menu_gift")],
    ])

def monitor_inline():
    enabled = is_monitor_enabled()
    dom = get_monitor_domain() or "غير محدد"
    ub_status = "✅ متصل" if _userbot_ready else "🚫 غير متصل"
    backfill_status = "⏳ جارٍ الآن" if _backfill_running else "✅ جاهز"
    chat_display = _monitor_chat_id_cache or get_setting("saved_channel_id", "") or "قيد الاتصال..."

    buffer_size = pending_count()
    combos_size = len(_combos_set)
    processed_size = len(_processed_set)

    text = (
        f"👁 <b>لوحة المراقبة</b>\n\n"
        f"<b>الحالة:</b> {'✅ مفعّلة' if enabled else '🚫 معطّلة'}\n"
        f"<b>Userbot:</b> {ub_status}\n"
        f"<b>القناة المصدر:</b> <code>{chat_display}</code>\n"
        f"<b>دومين الفرز:</b> <code>{dom}</code>\n"
        f"<b>الوجهة:</b> أنت (<code>{DEFAULT_DEST}</code>)\n"
        f"<b>المسح التاريخي:</b> {backfill_status}\n\n"
        f"📦 <b>البيانات:</b>\n"
        f"<b>الحسابات المتراكمة (RAM):</b> <code>{buffer_size:,}</code> / {BATCH_SIZE:,}\n"
        f"<b>كومبوهات للبحث (RAM):</b> <code>{combos_size:,}</code>\n"
        f"<b>الدفعات المُرسَلة:</b> <code>{_batch_num}</code>\n"
        f"<b>📋 ملفات معالجة (قرص):</b> <code>{processed_size:,}</code>"
    )

    buttons = [
        [InlineKeyboardButton(
            f"{'🚫 إيقاف' if enabled else '✅ تفعيل'} المراقبة",
            callback_data="mon_toggle"
        )],
        [InlineKeyboardButton("📚 مسح تاريخي الآن", callback_data="mon_rescan")],
        [InlineKeyboardButton("🎯 تغيير دومين الفرز", callback_data="mon_set_domain"),
         InlineKeyboardButton("❌ إزالة الدومين", callback_data="mon_clear_domain")],
        [InlineKeyboardButton(f"📤 سحب الكل ({buffer_size:,})", callback_data="mon_flush_auto")],
        [InlineKeyboardButton("🗑 حذف المتراكم", callback_data="mon_clear_buffer")],
        [InlineKeyboardButton(f"🗑 تصفير قائمة المعالجة ({processed_size:,})", callback_data="mon_reset_processed")],
        [InlineKeyboardButton("🔄 إعادة الاتصال بالقناة", callback_data="mon_reconnect")],
        [InlineKeyboardButton("🔄 تحديث", callback_data="mon_refresh"),
         InlineKeyboardButton("⬅️ رجوع", callback_data="menu_home")],
    ]
    return text, InlineKeyboardMarkup(buttons)

def stats_inline():
    total_combos = len(_combos_set)
    pending = pending_count()
    processed = len(_processed_set)

    text = (
        f"📊 <b>إحصائيات البوت</b>\n\n"
        f"<b>كومبوهات في RAM:</b> <code>{total_combos:,}</code>\n"
        f"<b>إجمالي العمليات:</b> <code>{get_total_operations():,}</code>\n"
        f"<b>📦 الحسابات المتراكمة:</b> <code>{pending:,}</code> / {BATCH_SIZE:,}\n"
        f"<b>📋 ملفات معالجة:</b> <code>{processed:,}</code>\n"
        f"<b>الدفعات المُرسَلة:</b> <code>{_batch_num}</code>\n"
    )
    buttons = [
        [InlineKeyboardButton("🔄 تحديث", callback_data="menu_stats"),
         InlineKeyboardButton("⬅️ رجوع", callback_data="menu_home")],
    ]
    return text, InlineKeyboardMarkup(buttons)

# ==================== الإرسال التلقائي ====================
async def _flush_pending(reason="auto"):
    global _batch_num

    async with _pending_lock:
        if not _pending_list:
            return 0
        accounts = list(_pending_list)

    count = len(accounts)
    _batch_num += 1
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"ULP_Batch{_batch_num}_{count}_{timestamp}.txt"
    content = "\n".join(accounts)

    try:
        file_obj = io.BytesIO(content.encode("utf-8"))
        file_obj.name = filename

        await app.send_document(
            DEFAULT_DEST,
            file_obj,
            caption=(
                f"📤 <b>دفعة ULP #{_batch_num}</b>\n\n"
                f"🔢 العدد: <b>{count:,}</b> حساب\n"
                f"🎯 الدومين: <code>{get_monitor_domain()}</code>\n"
                f"📅 {timestamp}\n"
                f"⚙️ السبب: {reason}"
            )
        )
        print(f"[FLUSH] ✅ تم رفع {count} حساب (دفعة #{_batch_num})")

        async with _pending_lock:
            del _pending_list[:count]

        return count

    except Exception as e:
        print(f"[FLUSH ERROR] {e}")
        raise

async def _check_and_flush():
    if pending_count() >= BATCH_SIZE:
        try:
            await _flush_pending(reason=f"وصل {BATCH_SIZE}")
        except Exception as e:
            print(f"[AUTO FLUSH ERROR] {e}")

async def _auto_flush_loop():
    while True:
        try:
            await asyncio.sleep(FLUSH_INTERVAL)
            if pending_count() > 0:
                print(f"[TIMER FLUSH] {pending_count()} حساب")
                await _flush_pending(reason="timer")
        except Exception as e:
            print(f"[TIMER ERROR] {e}")

# ==================== المراقبة ====================
def _passes_filters(message: Message):
    doc = message.document
    if not doc:
        return False, "لا يوجد ملف"
    name = (doc.file_name or "").lower()
    caption = (message.caption or "").lower()

    if not name.endswith(".txt"):
        return False, "ليس .txt"
    if doc.file_size and doc.file_size > MAX_FILE_SIZE:
        return False, ">1GB"
    if "ulp" not in name and "ulp" not in caption:
        return False, "لا يحتوي ulp"
    haystack = f"{name} {caption}"
    if not any(p.search(haystack) for p in ULP_PATTERNS):
        return False, "لا يطابق الأنماط"
    return True, "OK"

async def _process_monitored_document(client: Client, message: Message):
    doc = message.document
    uid = doc.file_unique_id

    if await is_already_processed(uid):
        print(f"[SKIP] مكرر: {doc.file_name}")
        return

    domain_filter = get_monitor_domain()

    temp = None
    sorted_path = None

    for attempt in range(DOWNLOAD_ATTEMPTS):
        try:
            temp = await client.download_media(message)
            if temp and os.path.exists(temp):
                break
        except (TimeoutError, ConnectionError, OSError) as e:
            wait_time = NETWORK_RETRY_DELAY * (attempt + 1)
            print(f"⚠️ تنزيل {attempt + 1}/{DOWNLOAD_ATTEMPTS}: {e}")
            await asyncio.sleep(wait_time)
        except Exception as e:
            print(f"⚠️ {e}")
            await asyncio.sleep(5)

    if not temp or not os.path.exists(temp):
        print(f"❌ فشل تنزيل {doc.file_name}")
        return

    try:
        print(f"[DOWNLOAD] ✅ {doc.file_name}")

        if domain_filter:
            sorted_path = temp + "_sorted.txt"
            try:
                count = await asyncio.to_thread(sort_file_by_domain, temp, domain_filter, sorted_path)
                print(f"[SORT] {count} سطر لـ '{domain_filter}'")
            except Exception as e:
                print(f"[SORT ERROR] {e}")
                count = 0

            if count == 0:
                await mark_as_processed(uid)
                return

            try:
                with open(sorted_path, 'r', encoding='utf-8', errors='ignore') as f:
                    lines = [l.strip() for l in f if l.strip()]
                if lines:
                    added = await pending_add(lines)
                    await combos_add(lines)
                    current = pending_count()
                    print(f"[PENDING] +{added} جديد | الإجمالي: {current}/{BATCH_SIZE}")

                    await _check_and_flush()
            except Exception as e:
                print(f"[PENDING ERROR] {e}")

        await mark_as_processed(uid)
        await mark_as_processed(f"{message.chat.id}:{message.id}")

    except Exception as e:
        print(f"[MONITOR ERROR] {e}")
    finally:
        for p in (temp, sorted_path):
            if p and os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass

async def _backfill_history(client: Client, limit: int):
    global _backfill_running

    if _backfill_running:
        print("⚠️ المسح قيد التنفيذ.")
        return

    _backfill_running = True
    print("=" * 60)
    print(f"📚 بدء المسح (حد: {limit})")
    print("=" * 60)

    total = 0
    processed = 0
    skipped = 0
    rejected = 0
    errors = 0

    try:
        chat_id = await _resolve_monitor_chat(client)
        if chat_id is None:
            print("❌ لا يمكن حل القناة.")
            return

        print(f"📌 القناة: {chat_id}")

        attempt = 0
        max_attempts = 3
        history_ok = False

        while attempt < max_attempts:
            attempt += 1
            try:
                async for msg in client.get_chat_history(chat_id, limit=limit):
                    total += 1

                    if total % 100 == 0:
                        print(f"⏳ {total} | ✅ {processed} | ⏭ {skipped} | ❌ {rejected} | ⚠️ {errors}")
                        await asyncio.sleep(PAUSE_BETWEEN_CHUNKS)

                    if not msg.document:
                        continue

                    uid = msg.document.file_unique_id
                    if await is_already_processed(uid):
                        skipped += 1
                        continue

                    ok, reason = _passes_filters(msg)
                    if not ok:
                        rejected += 1
                        await mark_as_processed(uid)
                        await mark_as_processed(f"{msg.chat.id}:{msg.id}")
                        continue

                    try:
                        print(f"🎯 {msg.document.file_name}")
                        await _process_monitored_document(client, msg)
                        processed += 1
                        await asyncio.sleep(PAUSE_BETWEEN_FILES)
                    except FloodWait as e:
                        print(f"⏸ FloodWait {e.value}s")
                        await asyncio.sleep(e.value + 5)
                    except (TimeoutError, ConnectionError, OSError) as e:
                        errors += 1
                        print(f"⚠️ شبكة: {e}")
                        await asyncio.sleep(PAUSE_BETWEEN_CHUNKS)
                    except Exception as e:
                        errors += 1
                        print(f"❌ {e}")
                        await asyncio.sleep(5)

                history_ok = True
                break

            except Exception as e:
                print(f"❌ محاولة {attempt}/{max_attempts}: {e}")
                if attempt < max_attempts:
                    await asyncio.sleep(15 * attempt)
                    globals()['_monitor_chat_id_cache'] = None
                    chat_id = await _resolve_monitor_chat(client)

        if history_ok:
            print("=" * 60)
            print(f"✅ انتهى المسح")
            print(f"📊 مفحوصة: {total} | ✅ {processed} | ⏭ {skipped} | ❌ {rejected} | ⚠️ {errors}")
            print("=" * 60)

            pending = pending_count()
            try:
                for oid in OWNER_IDS:
                    await app.send_message(
                        oid,
                        f"📚 <b>انتهى المسح</b>\n\n"
                        f"📊 إجمالي: <code>{total:,}</code>\n"
                        f"✅ معالَجة: <code>{processed:,}</code>\n"
                        f"⏭ متجاوزة: <code>{skipped:,}</code>\n"
                        f"❌ مرفوضة: <code>{rejected:,}</code>\n"
                        f"⚠️ أخطاء: <code>{errors:,}</code>\n\n"
                        f"📦 <b>الحسابات المتراكمة:</b> <code>{pending:,}</code> / {BATCH_SIZE:,}\n"
                        f"💡 عند وصول {BATCH_SIZE} سيُرسل تلقائياً."
                    )
            except Exception:
                pass

    except Exception as e:
        print(f"❌ خطأ: {e}")
    finally:
        _backfill_running = False

async def _monitor_startup():
    global _userbot_ready

    if userbot is None:
        print("⚠️ Userbot غير متصل")
        return

    if not is_monitor_enabled():
        print("ℹ️ المراقبة معطّلة")
        return

    try:
        me = await userbot.get_me()
        print(f"👤 Userbot: @{me.username or me.id}")

        chat_id = await _resolve_monitor_chat(userbot)
        if chat_id is None:
            print("❌ لم نتمكن من حل القناة.")
            return

        print(f"📌 القناة: {chat_id}")
        print(f"📦 الحسابات المتراكمة الحالية: {pending_count()}")

        if BACKFILL_ENABLED:
            print(f"📚 سيبدأ المسح (حد: {BACKFILL_LIMIT})")
            asyncio.create_task(_backfill_history(userbot, BACKFILL_LIMIT))

        @userbot.on_message(filters.document, group=-1)
        async def monitor_handler(client, message):
            try:
                if not is_monitor_enabled():
                    return
                if _monitor_chat_id_cache is None:
                    return
                if message.chat.id != _monitor_chat_id_cache:
                    return
                uid = message.document.file_unique_id
                if await is_already_processed(uid):
                    return
                ok, reason = _passes_filters(message)
                if not ok:
                    print(f"[REJECT] {message.document.file_name} ({reason})")
                    return
                print(f"🎯 [LIVE] {message.document.file_name}")
                asyncio.create_task(_process_monitored_document(client, message))
            except Exception as e:
                print(f"[HANDLER ERROR] {e}")

        _userbot_ready = True
        print(f"👁 المراقبة الحية نشطة على: {chat_id}")

    except Exception as e:
        print(f"[MONITOR STARTUP ERROR] {e}")

# ==================== /start ====================
@app.on_message(filters.command("start"))
async def start_handler(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id in OWNER_IDS:
        text = (
            f"👑 <b>مرحباً بك أيها المالك</b>\n\n"
            f"📱 استخدم لوحة التحكم أدناه 👇"
        )
        await message.reply(text, reply_markup=owner_reply_keyboard())
        await message.reply("🎛 <b>اللوحة الرئيسية</b>", reply_markup=owner_main_inline())
        return
    await message.reply("👋 أهلاً بك")

@app.on_message(filters.command("menu") & filters.user(OWNER_IDS))
async def menu_cmd(client: Client, message: Message):
    await message.reply("🎛 <b>اللوحة الرئيسية</b>", reply_markup=owner_main_inline())

# ==================== أزرار Reply ====================
@app.on_message(filters.regex(r"^🎛 لوحة التحكم$") & filters.user(OWNER_IDS))
async def kb_control(client: Client, message: Message):
    await message.reply("🎛 <b>اللوحة</b>", reply_markup=owner_main_inline())

@app.on_message(filters.regex(r"^👁 المراقبة$") & filters.user(OWNER_IDS))
async def kb_monitor(client: Client, message: Message):
    text, kb = monitor_inline()
    await message.reply(text, reply_markup=kb)

@app.on_message(filters.regex(r"^📊 الإحصائيات$") & filters.user(OWNER_IDS))
async def kb_stats(client: Client, message: Message):
    text, kb = stats_inline()
    await message.reply(text, reply_markup=kb)

@app.on_message(filters.regex(r"^📈 حالة البوت$") & filters.user(OWNER_IDS))
async def kb_status(client: Client, message: Message):
    text = (
        f"📈 <b>حالة البوت</b>\n\n"
        f"<b>Userbot:</b> {'✅' if _userbot_ready else '🚫'}\n"
        f"<b>المراقبة:</b> {'✅' if is_monitor_enabled() else '🚫'}\n"
        f"<b>المسح:</b> {'⏳ جارٍ' if _backfill_running else '✅ جاهز'}\n"
        f"<b>القناة:</b> <code>{_monitor_chat_id_cache or get_setting('saved_channel_id', '') or '—'}</code>\n"
        f"<b>📦 المتراكم:</b> <code>{pending_count():,}</code> / {BATCH_SIZE:,}\n"
        f"<b>📋 معرفات معالجة:</b> <code>{len(_processed_set):,}</code>"
    )
    await message.reply(text)

@app.on_message(filters.regex(r"^✅ تفعيل$") & filters.user(OWNER_IDS))
async def kb_enable(client: Client, message: Message):
    global _bot_running
    _bot_running = True
    await message.reply("✅")

@app.on_message(filters.regex(r"^🚫 إغلاق$") & filters.user(OWNER_IDS))
async def kb_disable(client: Client, message: Message):
    global _bot_running
    _bot_running = False
    await message.reply("🚫")

@app.on_message(filters.regex(r"^🔍 بحث دومين$") & filters.user(OWNER_IDS))
async def kb_search(client: Client, message: Message):
    user_action_state[message.from_user.id] = "awaiting_search_domain"
    await message.reply("🔍 أرسل الدومين المطلوب:")

@app.on_message(filters.regex(r"^📤 رفع ULP$") & filters.user(OWNER_IDS))
async def kb_upload(client: Client, message: Message):
    user_action_state[message.from_user.id] = "awaiting_ulp_upload"
    await message.reply("📤 أرسل ملف ULP:")

@app.on_message(filters.regex(r"^📂 فرز ULP$") & filters.user(OWNER_IDS))
async def kb_filter(client: Client, message: Message):
    await message.reply("⚠️ فرز الكلمات غير مفعّل حالياً (بدون تخزين).")

@app.on_message(filters.regex(r"^🎁 هدية$") & filters.user(OWNER_IDS))
async def kb_gift(client: Client, message: Message):
    await message.reply("🎁 غير مفعّل حالياً (بدون تخزين).")

# ==================== معالجة النصوص ====================
@app.on_message(
    filters.text & filters.private & filters.user(OWNER_IDS)
    & ~filters.regex(r"^[🎛👁📊📈🔍📤📂🎁✅🚫💰📋]"),
    group=1
)
async def handle_text_states(client: Client, message: Message):
    user_id = message.from_user.id
    state = user_action_state.get(user_id)
    text = (message.text or "").strip()

    if not state:
        return
    if text in BUTTON_TEXTS:
        return

    try:
        if state == "awaiting_search_domain":
            user_action_state.pop(user_id, None)
            if not text or len(text) < 3:
                await message.reply("❌ أرسل دومين صحيح:")
                user_action_state[user_id] = "awaiting_search_domain"
                return
            await _do_search(client, message, text)

        elif state == "awaiting_monitor_domain":
            user_action_state.pop(user_id, None)
            clean = text.strip().lower()
            if clean:
                set_setting("monitor_domain", clean)
                await message.reply(f"✅ دومين الفرز: <code>{clean}</code>")
            else:
                await message.reply("❌")

    except Exception as e:
        print(f"[TEXT STATE ERROR] {e}")

async def _do_search(client: Client, message: Message, domain: str):
    domain = domain.strip().lower()
    domain = re.sub(r'[^\w\.\-\_]', '', domain)

    if not domain or len(domain) < 3:
        await message.reply("❌ دومين غير صحيح.")
        return

    available = await combos_count(domain)

    if available == 0:
        await message.reply(f"❌ لا حسابات لـ <code>{domain}</code> في RAM")
        return

    limit = available if available < 50000 else 50000
    msg = await message.reply(f"👑 <code>{domain}</code> ({available:,})...")

    rows = await combos_search(domain, limit)

    cleaned_rows = []
    seen = set()
    for c in rows:
        cc = clean_line(c)
        if cc and cc not in seen:
            seen.add(cc)
            cleaned_rows.append(cc)

    content = "\n".join(cleaned_rows)
    file_obj = io.BytesIO(content.encode("utf-8"))
    file_obj.name = f"{domain}_{len(cleaned_rows)}.txt"
    await client.send_document(
        message.chat.id, file_obj,
        caption=f"✅ <code>{domain}</code> — <b>{len(cleaned_rows):,}</b>"
    )
    try:
        await msg.delete()
    except Exception:
        pass

# ==================== Callbacks ====================
async def _safe_edit(callback, text, kb=None):
    try:
        if kb is None:
            await callback.message.edit_text(text)
        else:
            await callback.message.edit_text(text, reply_markup=kb)
    except Exception as e:
        err = str(e)
        if "MESSAGE_NOT_MODIFIED" in err or "message is not modified" in err.lower():
            return
        try:
            await callback.message.reply(text, reply_markup=kb)
        except Exception:
            pass

@app.on_callback_query()
async def on_callback(client: Client, callback: CallbackQuery):
    user_id = callback.from_user.id
    if user_id not in OWNER_IDS:
        await callback.answer("❌", show_alert=True)
        return

    data = callback.data

    try:
        if data == "menu_home":
            await _safe_edit(callback, "🎛 <b>اللوحة</b>", owner_main_inline())

        elif data == "menu_monitor":
            text, kb = monitor_inline()
            await _safe_edit(callback, text, kb)

        elif data == "menu_stats":
            text, kb = stats_inline()
            await _safe_edit(callback, text, kb)

        elif data == "menu_rescan":
            await _safe_edit(
                callback,
                "📚 <b>المسح التاريخي</b>\n\nهل تريد البدء؟",
                InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ نعم", callback_data="trigger_rescan")],
                    [InlineKeyboardButton("⬅️ رجوع", callback_data="menu_home")],
                ])
            )

        elif data == "menu_search":
            await callback.answer()
            user_action_state[user_id] = "awaiting_search_domain"
            await callback.message.reply("🔍 أرسل الدومين:")

        elif data == "menu_upload":
            await callback.answer()
            user_action_state[user_id] = "awaiting_ulp_upload"
            await callback.message.reply("📤 أرسل ملف ULP:")

        elif data == "menu_filter":
            await callback.answer("⚠️ غير مفعّل حالياً.", show_alert=True)

        elif data == "menu_gift":
            await callback.answer("⚠️ غير مفعّل حالياً.", show_alert=True)

        elif data == "mon_toggle":
            current = is_monitor_enabled()
            set_setting("monitor_enabled", "0" if current else "1")
            text, kb = monitor_inline()
            await _safe_edit(callback, text, kb)
            await callback.answer(f"{'🚫' if current else '✅'}")

        elif data == "mon_rescan":
            await callback.answer()
            if userbot is None:
                await callback.answer("⚠️ لا يوجد userbot", show_alert=True)
                return
            asyncio.create_task(_backfill_history(userbot, BACKFILL_LIMIT))
            await _safe_edit(callback, f"📚 بدأ المسح (حد: {BACKFILL_LIMIT})",
                InlineKeyboardMarkup([[InlineKeyboardButton("⬅️", callback_data="menu_monitor")]]))

        elif data == "trigger_rescan":
            await callback.answer()
            if userbot is None:
                await callback.answer("⚠️ لا يوجد userbot", show_alert=True)
                return
            asyncio.create_task(_backfill_history(userbot, BACKFILL_LIMIT))
            await _safe_edit(callback, "📚 بدأ المسح",
                InlineKeyboardMarkup([[InlineKeyboardButton("⬅️", callback_data="menu_home")]]))

        elif data == "mon_set_domain":
            await callback.answer()
            user_action_state[user_id] = "awaiting_monitor_domain"
            await callback.message.reply("🎯 أرسل الدومين:")

        elif data == "mon_clear_domain":
            set_setting("monitor_domain", "")
            text, kb = monitor_inline()
            await _safe_edit(callback, text, kb)
            await callback.answer("🗑")

        elif data == "mon_flush_auto":
            await callback.answer()
            size = pending_count()
            if size == 0:
                await callback.answer("📭 لا يوجد متراكم.", show_alert=True)
                return
            await _safe_edit(callback, f"⏳ جارٍ سحب <b>{size:,}</b> حساب...")
            try:
                sent = await _flush_pending(reason="يدوي")
                text, kb = monitor_inline()
                await _safe_edit(callback, text, kb)
                await callback.answer(f"✅ تم رفع {sent:,} حساب")
            except Exception as e:
                await callback.answer(f"❌ {str(e)[:50]}", show_alert=True)

        elif data == "mon_clear_buffer":
            await _safe_edit(
                callback,
                f"⚠️ حذف <b>{pending_count():,}</b> حساب من RAM؟",
                InlineKeyboardMarkup([
                    [InlineKeyboardButton("⚠️ نعم", callback_data="mon_clear_buffer_confirm")],
                    [InlineKeyboardButton("❌ إلغاء", callback_data="menu_monitor")],
                ])
            )

        elif data == "mon_clear_buffer_confirm":
            await callback.answer()
            size = pending_count()
            await pending_clear()
            text, kb = monitor_inline()
            await _safe_edit(callback, text, kb)
            await callback.answer(f"🗑 تم حذف {size:,}")

        elif data == "mon_reset_processed":
            count = len(_processed_set)
            await _safe_edit(
                callback,
                f"⚠️ <b>تصفير قائمة المعالجة</b>\n\n"
                f"عدد المعرفات الحالية: <code>{count:,}</code>\n\n"
                f"بعد التصفير، أي مسح تاريخي جديد راح <b>يعيد تنزيل كل الملفات</b> من الصفر.\n\n"
                f"هل أنت متأكد؟",
                InlineKeyboardMarkup([
                    [InlineKeyboardButton("⚠️ نعم، صفّر", callback_data="mon_reset_processed_confirm")],
                    [InlineKeyboardButton("❌ إلغاء", callback_data="menu_monitor")],
                ])
            )

        elif data == "mon_reset_processed_confirm":
            await callback.answer()
            count = await reset_processed()
            text, kb = monitor_inline()
            await _safe_edit(callback, text, kb)
            await callback.answer(f"🗑 تم حذف {count:,} معرف")

        elif data == "mon_reconnect":
            await callback.answer("🔄")
            if userbot is None:
                await callback.answer("⚠️", show_alert=True)
                return
            globals()['_monitor_chat_id_cache'] = None
            globals()['_monitor_chat_obj'] = None
            del_setting("saved_channel_id")
            cid = await _resolve_monitor_chat(userbot)
            if cid:
                await _safe_edit(callback, f"✅ تم الاتصال: <code>{cid}</code>",
                    InlineKeyboardMarkup([[InlineKeyboardButton("⬅️", callback_data="menu_monitor")]]))
                asyncio.create_task(_backfill_history(userbot, BACKFILL_LIMIT))
            else:
                await _safe_edit(callback, "❌ فشل.",
                    InlineKeyboardMarkup([[InlineKeyboardButton("⬅️", callback_data="menu_monitor")]]))

        elif data == "mon_refresh":
            text, kb = monitor_inline()
            await _safe_edit(callback, text, kb)
            try:
                await callback.answer("🔄")
            except Exception:
                pass

        else:
            await callback.answer()

    except Exception as e:
        print(f"[CALLBACK ERROR] {data}: {e}")
        try:
            await callback.answer("❌", show_alert=False)
        except Exception:
            pass

# ==================== رفع الملفات ====================
@app.on_message(filters.document & filters.private & filters.user(OWNER_IDS), group=2)
async def handle_document(client: Client, message: Message):
    user_id = message.from_user.id
    state = user_action_state.get(user_id)

    if state == "awaiting_ulp_upload":
        user_action_state.pop(user_id, None)
        temp = None
        try:
            msg = await message.reply("⏳ رفع...")
            temp = await message.download()

            enc = 'utf-8'
            for e in ['utf-8-sig', 'utf-8', 'latin-1', 'cp1252', 'utf-16']:
                try:
                    with open(temp, "r", encoding=e, errors="ignore") as f:
                        f.readlines()
                    enc = e
                    break
                except Exception:
                    continue

            lines = []
            with open(temp, "r", encoding=enc, errors="ignore") as f:
                for line in f:
                    s = line.strip()
                    if s and len(s) >= 3:
                        lines.append(s)

            await combos_add(lines)
            added = await pending_add(lines)
            await msg.edit_text(f"✅ <b>{len(lines):,}</b> سطر (أُضيف {added})")
            await _check_and_flush()
        except Exception as e:
            await message.reply(f"❌ {e}")
        finally:
            if temp and os.path.exists(temp):
                try:
                    os.remove(temp)
                except Exception:
                    pass

# ==================== أوامر ====================
@app.on_message(filters.command("monitor_status") & filters.user(OWNER_IDS))
async def cmd_monitor_status(client: Client, message: Message):
    text, kb = monitor_inline()
    await message.reply(text, reply_markup=kb)

@app.on_message(filters.command("set_monitor_domain") & filters.user(OWNER_IDS))
async def cmd_set_monitor_domain(client: Client, message: Message):
    if len(message.command) > 1:
        dom = message.command[1].lower().strip()
        set_setting("monitor_domain", dom)
        await message.reply(f"✅ <code>{dom}</code>")
    else:
        user_action_state[message.from_user.id] = "awaiting_monitor_domain"
        await message.reply("🎯 أرسل الدومين:")

@app.on_message(filters.command("monitor_on") & filters.user(OWNER_IDS))
async def cmd_monitor_on(client: Client, message: Message):
    set_setting("monitor_enabled", "1")
    await message.reply("✅")

@app.on_message(filters.command("monitor_off") & filters.user(OWNER_IDS))
async def cmd_monitor_off(client: Client, message: Message):
    set_setting("monitor_enabled", "0")
    await message.reply("🚫")

@app.on_message(filters.command("rescan_history") & filters.user(OWNER_IDS))
async def cmd_rescan_history(client: Client, message: Message):
    if userbot is None:
        await message.reply("⚠️")
        return
    asyncio.create_task(_backfill_history(userbot, BACKFILL_LIMIT))
    await message.reply(f"📚 بدأ المسح (حد: {BACKFILL_LIMIT})")

@app.on_message(filters.command("flush") & filters.user(OWNER_IDS))
async def cmd_flush(client: Client, message: Message):
    size = pending_count()
    if size == 0:
        await message.reply("📭 لا يوجد متراكم.")
        return
    msg = await message.reply(f"⏳ جارٍ سحب <b>{size:,}</b>...")
    try:
        sent = await _flush_pending(reason="يدوي")
        await msg.edit_text(f"✅ تم رفع <b>{sent:,}</b>")
    except Exception as e:
        await msg.edit_text(f"❌ {e}")

@app.on_message(filters.command("pending") & filters.user(OWNER_IDS))
async def cmd_pending(client: Client, message: Message):
    await message.reply(
        f"📦 <b>حالة الذاكرة والقرص</b>\n\n"
        f"<b>💾 على القرص (ملف صغير):</b>\n"
        f"• معرفات معالجة: <code>{len(_processed_set):,}</code>\n\n"
        f"<b>🧠 في RAM:</b>\n"
        f"• الحسابات المتراكمة: <code>{pending_count():,}</code> / {BATCH_SIZE:,}\n"
        f"• كومبوهات البحث: <code>{len(_combos_set):,}</code>\n"
        f"• الدفعات المُرسَلة: <code>{_batch_num}</code>"
    )

@app.on_message(filters.command("reset_processed") & filters.user(OWNER_IDS))
async def cmd_reset_processed(client: Client, message: Message):
    count = len(_processed_set)
    if count == 0:
        await message.reply("📭 قائمة المعالجة فارغة أصلاً.")
        return
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"⚠️ نعم احذف {count:,}", callback_data="mon_reset_processed_confirm")],
        [InlineKeyboardButton("❌ إلغاء", callback_data="menu_monitor")],
    ])
    await message.reply(
        f"⚠️ <b>تصفير قائمة المعالجة</b>\n\n"
        f"عدد المعرفات: <code>{count:,}</code>\n"
        f"سيُعاد تنزيل كل الملفات من الصفر بعد التصفير.",
        reply_markup=kb
    )

@app.on_message(filters.command("debug_chat") & filters.user(OWNER_IDS))
async def cmd_debug_chat(client: Client, message: Message):
    if userbot is None:
        await message.reply("⚠️")
        return
    lines = ["🔍 <b>تشخيص</b>\n"]
    lines.append(f"cache: <code>{_monitor_chat_id_cache}</code>")
    lines.append(f"saved_id: <code>{get_setting('saved_channel_id', '')}</code>")
    lines.append(f"pending: <code>{pending_count():,}</code>")
    lines.append(f"processed: <code>{len(_processed_set):,}</code>")
    lines.append(f"batch_num: <code>{_batch_num}</code>")
    lines.append(f"file: <code>{PROCESSED_FILE}</code>")
    await message.reply("\n".join(lines))

# ==================== نقطة التشغيل ====================
async def _async_main():
    global userbot

    print("=" * 60)
    print("🚀 بدء التشغيل...")
    print("=" * 60)
    print(f"📦 BATCH_SIZE = {BATCH_SIZE}")
    print(f"⏱ FLUSH_INTERVAL = {FLUSH_INTERVAL}s")
    print(f"📚 BACKFILL_LIMIT = {BACKFILL_LIMIT}")
    print(f"💾 PROCESSED_FILE = {PROCESSED_FILE}")
    print(f"📋 معرفات محمّلة: {len(_processed_set):,}")
    print("=" * 60)

    if userbot is not None:
        try:
            await userbot.start()
            me = await userbot.get_me()
            print(f"✅ Userbot: @{me.username or me.id}")
            await asyncio.sleep(5)
            await _monitor_startup()
        except Exception as e:
            print(f"❌ Userbot: {e}")
            userbot = None

    await app.start()
    print("🤖 Bot online")
    print("=" * 60)

    asyncio.create_task(_auto_flush_loop())

    stop = asyncio.Event()
    try:
        await stop.wait()
    except asyncio.CancelledError:
        pass
    finally:
        try:
            await app.stop()
        except Exception:
            pass
        if userbot is not None:
            try:
                await userbot.stop()
            except Exception:
                pass

if __name__ == "__main__":
    try:
        _loop.run_until_complete(_async_main())
    except KeyboardInterrupt:
        print("\n⏹ إيقاف.")
    finally:
        try:
            _loop.close()
        except Exception:
            pass
