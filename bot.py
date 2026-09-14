
import asyncio
import html
import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv
from aiohttp import web


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger("apnastore")


# =========================================================
# CONFIG
# =========================================================

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

BOT_TOKEN = os.getenv("BOT_TOKEN")

ADMIN_ID = 7464364112

CHANNEL_USERNAME = "@apnaxstore"
CHANNEL_LINK = "https://t.me/apnaxstore"

GROUP_ID = -1004462426006
GROUP_LINK = "https://t.me/+MRaSyFL47X40ZjU9"

UPI_ID = "rohitpalpersonal-2@okicici"

MIN_RECHARGE = 10
MAX_RECHARGE = 10000

DB_FILE = BASE_DIR / "apnastore.db"


# =========================================================
# DATABASE
# =========================================================

db = sqlite3.connect(DB_FILE, check_same_thread=False)
db.row_factory = sqlite3.Row
db.execute("PRAGMA journal_mode=WAL")
db.execute("PRAGMA foreign_keys=ON")
db.execute("PRAGMA busy_timeout=5000")


def init_db():
    db.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        first_name TEXT,
        username TEXT,
        balance REAL NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS wallet_transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        amount REAL NOT NULL,
        type TEXT NOT NULL,
        description TEXT,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        category TEXT NOT NULL DEFAULT 'Digital Products',
        price REAL NOT NULL,
        description TEXT DEFAULT '',
        active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS stock (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER NOT NULL,
        item TEXT NOT NULL,
        sold INTEGER NOT NULL DEFAULT 0,
        sold_to INTEGER,
        sold_at TEXT,
        FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        product_id INTEGER NOT NULL,
        stock_id INTEGER,
        amount REAL NOT NULL,
        item TEXT,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS recharge_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        amount REAL NOT NULL,
        utr TEXT NOT NULL,
        screenshot_file_id TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        admin_note TEXT DEFAULT '',
        created_at TEXT NOT NULL,
        reviewed_at TEXT
    );

    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    );

    CREATE TABLE IF NOT EXISTS admins (
        user_id INTEGER PRIMARY KEY,
        role TEXT NOT NULL DEFAULT 'admin',
        added_by INTEGER,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS wishlist (
        user_id INTEGER NOT NULL,
        product_id INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY(user_id, product_id)
    );

    CREATE TABLE IF NOT EXISTS coupons (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT NOT NULL UNIQUE,
        kind TEXT NOT NULL DEFAULT 'percent',
        value REAL NOT NULL DEFAULT 0,
        max_uses INTEGER NOT NULL DEFAULT 0,
        used_count INTEGER NOT NULL DEFAULT 0,
        min_order REAL NOT NULL DEFAULT 0,
        active INTEGER NOT NULL DEFAULT 1,
        expires_at TEXT,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS coupon_uses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        coupon_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        order_id INTEGER,
        amount_saved REAL NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        UNIQUE(coupon_id, user_id)
    );

    CREATE TABLE IF NOT EXISTS reviews (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        order_id INTEGER NOT NULL UNIQUE,
        rating INTEGER NOT NULL,
        comment TEXT DEFAULT '',
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        body TEXT NOT NULL,
        is_read INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS support_tickets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        category TEXT NOT NULL,
        subject TEXT NOT NULL,
        message TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'open',
        order_id INTEGER,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS support_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ticket_id INTEGER NOT NULL,
        sender_id INTEGER NOT NULL,
        message TEXT NOT NULL,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS loyalty_points (
        user_id INTEGER PRIMARY KEY,
        points INTEGER NOT NULL DEFAULT 0,
        lifetime_points INTEGER NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS pass_levels (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        min_points INTEGER NOT NULL,
        discount_percent REAL NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS referrals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        referrer_id INTEGER NOT NULL,
        referred_user_id INTEGER NOT NULL UNIQUE,
        reward REAL NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    );
    """)
    db.commit()

    # Migrate older ApnaStore databases safely.
    columns = {row[1] for row in db.execute("PRAGMA table_info(users)").fetchall()}
    if "verified" not in columns:
        db.execute("ALTER TABLE users ADD COLUMN verified INTEGER NOT NULL DEFAULT 0")

    product_columns = {row[1] for row in db.execute("PRAGMA table_info(products)").fetchall()}
    if "image_file_id" not in product_columns:
        db.execute("ALTER TABLE products ADD COLUMN image_file_id TEXT DEFAULT ''")
    if "sale_price" not in product_columns:
        db.execute("ALTER TABLE products ADD COLUMN sale_price REAL")

    # New customer/profile fields, safe migrations for older databases.
    user_columns = {row[1] for row in db.execute("PRAGMA table_info(users)").fetchall()}
    for col, definition in [
        ("blocked", "INTEGER NOT NULL DEFAULT 0"),
        ("notification_enabled", "INTEGER NOT NULL DEFAULT 1"),
        ("referred_by", "INTEGER"),
        ("referral_credited", "INTEGER NOT NULL DEFAULT 0"),
    ]:
        if col not in user_columns:
            db.execute(f"ALTER TABLE users ADD COLUMN {col} {definition}")

    product_columns = {row[1] for row in db.execute("PRAGMA table_info(products)").fetchall()}
    if "featured" not in product_columns:
        db.execute("ALTER TABLE products ADD COLUMN featured INTEGER NOT NULL DEFAULT 0")

    db.execute("INSERT OR IGNORE INTO settings(key,value) VALUES ('referral_reward','10')")
    db.execute("INSERT OR IGNORE INTO settings(key,value) VALUES ('store_name','ApnaStore')")
    for name, minimum, discount in [("Basic",0,0),("Silver",100,2),("Gold",300,5),("Elite",750,10)]:
        db.execute("INSERT OR IGNORE INTO pass_levels(name,min_points,discount_percent,created_at) VALUES (?,?,?,?)", (name, minimum, discount, now()))

    # Performance + integrity indexes. The UTR index prevents duplicate
    # payment proofs from being submitted more than once.
    db.execute("CREATE INDEX IF NOT EXISTS idx_stock_product_sold ON stock(product_id, sold, id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_orders_user_id ON orders(user_id, id DESC)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_wallet_user_id ON wallet_transactions(user_id, id DESC)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_recharge_status ON recharge_requests(status, id DESC)")
    try:
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_recharge_utr ON recharge_requests(utr)")
    except sqlite3.IntegrityError:
        logger.warning("Could not create unique UTR index because duplicate legacy UTRs exist.")

    db.execute(
        """
        INSERT OR IGNORE INTO admins(user_id, role, added_by, created_at)
        VALUES (?, 'owner', ?, ?)
        """,
        (ADMIN_ID, ADMIN_ID, now()),
    )
    db.commit()


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def ensure_user(user):
    existing = db.execute(
        "SELECT user_id FROM users WHERE user_id=?",
        (user.id,),
    ).fetchone()

    if existing:
        db.execute(
            """
            UPDATE users
            SET first_name=?, username=?
            WHERE user_id=?
            """,
            (user.first_name or "", user.username or "", user.id),
        )
    else:
        db.execute(
            """
            INSERT INTO users(
                user_id, first_name, username, balance, verified, created_at
            )
            VALUES (?, ?, ?, 0, 0, ?)
            """,
            (user.id, user.first_name or "", user.username or "", now()),
        )

    db.commit()


def is_verified(user_id):
    row = db.execute(
        "SELECT verified FROM users WHERE user_id=?",
        (user_id,),
    ).fetchone()
    return bool(row and row["verified"] == 1)


def set_verified(user_id, value=True):
    db.execute(
        "UPDATE users SET verified=? WHERE user_id=?",
        (1 if value else 0, user_id),
    )
    db.commit()


def get_balance(user_id):
    row = db.execute("SELECT balance FROM users WHERE user_id=?", (user_id,)).fetchone()
    return float(row["balance"]) if row else 0.0


def get_setting(key):
    row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else None


def set_setting(key, value):
    db.execute("""
        INSERT INTO settings(key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
    """, (key, value))
    db.commit()


# =========================================================
# FSM STATES
# =========================================================

class RechargeStates(StatesGroup):
    waiting_amount = State()
    waiting_utr = State()
    waiting_screenshot = State()


class ProductStates(StatesGroup):
    waiting_name = State()
    waiting_category = State()
    waiting_price = State()
    waiting_description = State()
    waiting_image = State()
    waiting_edit_value = State()
    waiting_sale_price = State()


class StockStates(StatesGroup):
    waiting_product_id = State()
    waiting_items = State()
    waiting_remove_items = State()


class WalletStates(StatesGroup):
    waiting_user_id = State()
    waiting_amount = State()


class BroadcastStates(StatesGroup):
    waiting_message = State()


class AdminStates(StatesGroup):
    waiting_add_admin_id = State()


class SearchStates(StatesGroup):
    waiting_query = State()

class CouponApplyStates(StatesGroup):
    waiting_code = State()

class ReviewStates(StatesGroup):
    waiting_rating = State()
    waiting_comment = State()

class CouponCreateStates(StatesGroup):
    waiting_code = State()
    waiting_kind = State()
    waiting_value = State()
    waiting_min_order = State()
    waiting_max_uses = State()


# =========================================================
# BOT
# =========================================================

dp = Dispatcher()


def main_menu_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛍️  EXPLORE STORE", callback_data="shop", style="success")],
        [InlineKeyboardButton(text="🔎  SEARCH PRODUCTS", callback_data="search", style="primary")],
        [InlineKeyboardButton(text="🔥  WHAT'S HOT", callback_data="whats_hot", style="success"), InlineKeyboardButton(text="🆕  NEW ARRIVALS", callback_data="new_arrivals", style="primary")],
        [InlineKeyboardButton(text="💳  WALLET", callback_data="wallet", style="success"), InlineKeyboardButton(text="📦  MY ORDERS", callback_data="orders", style="primary")],
        [InlineKeyboardButton(text="❤️  SAVED", callback_data="wishlist", style="primary"), InlineKeyboardButton(text="🎁  REWARDS", callback_data="rewards", style="success")],
        [InlineKeyboardButton(text="🏆  APNAPASS", callback_data="apnapass", style="primary"), InlineKeyboardButton(text="🔔  NOTIFICATIONS", callback_data="notifications", style="primary")],
        [InlineKeyboardButton(text="⭐  REVIEWS", callback_data="my_reviews", style="primary"), InlineKeyboardButton(text="🎟️  COUPONS", callback_data="my_coupons", style="success")],
        [InlineKeyboardButton(text="🆘  HELP CENTER", callback_data="support", style="primary"), InlineKeyboardButton(text="📢  COMMUNITY", url=CHANNEL_LINK, style="primary")],
        [InlineKeyboardButton(text="👤  MY ACCOUNT", callback_data="account", style="primary")],
    ])


def join_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 JOIN OFFICIAL CHANNEL", url=CHANNEL_LINK, style="primary")],
        [InlineKeyboardButton(text="👥 JOIN COMMUNITY GROUP", url=GROUP_LINK, style="primary")],
        [InlineKeyboardButton(text="✅ VERIFY MEMBERSHIP", callback_data="verify_membership", style="success")],
    ])


def back_home_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠 HOME", callback_data="home", style="primary")]
    ])


# =========================================================
# START + VERIFY
# =========================================================

@dp.message(CommandStart())
async def start_handler(message: Message):
    ensure_user(message.from_user)

    # IMPORTANT: verification is persistent. Once verified, /start opens
    # the store directly instead of showing Join + Verify again.
    if is_verified(message.from_user.id):
        balance = get_balance(message.from_user.id)
        await message.answer(
            "💙 <b>APNASTORE</b>  •  <i>YOUR DIGITAL STORE</i>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👋 <b>Welcome back, {html.escape(message.from_user.first_name or 'there')}!</b>\n"
            "Great to see you again. Your store is ready. 🚀\n\n"
            f"💳 <b>Wallet Balance:</b> ₹{balance:.2f}\n\n"
            "🛍️ <b>Shop</b> — subscriptions, vouchers & digital products\n"
            "⚡ <b>Fast Delivery</b> — quick and simple checkout\n"
            "🔥 <b>Best Deals</b> — offers worth checking out\n"
            "🔐 <b>Secure Service</b> — smooth & reliable experience\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "✨ <b>WHAT ARE YOU LOOKING FOR TODAY?</b>\n"
            "Choose an option below 👇",
            reply_markup=main_menu_keyboard(),
            parse_mode="HTML",
        )
        return

    await message.answer(
        "💙 <b>WELCOME TO APNASTORE</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "🛍️ <b>Your trusted digital store</b>\n"
        "Discover subscriptions, vouchers and digital products — all in one place. ✨\n\n"
        "🎬 <b>Entertainment</b>  •  🎟️ <b>Coupons</b>\n"
        "💎 <b>Digital Products</b>  •  🔥 <b>Exclusive Deals</b>\n\n"
        "⚡ Fast Delivery   •   💰 Great Deals   •   🔐 Secure Service\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🔐 <b>ONE-TIME VERIFICATION</b>\n\n"
        "Join our official <b>Channel</b> and <b>Community</b>, then verify your membership.\n\n"
        "✨ <i>One quick verification unlocks your complete ApnaStore experience.</i>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "👇 <b>JOIN • VERIFY • SHOP</b>",
        reply_markup=join_keyboard(),
        parse_mode="HTML",
    )

@dp.callback_query(F.data == "verify_membership")
async def verify_membership(callback: CallbackQuery):
    user_id = callback.from_user.id

    try:
        channel_member = await callback.bot.get_chat_member(
            chat_id=CHANNEL_USERNAME, user_id=user_id
        )
        group_member = await callback.bot.get_chat_member(
            chat_id=GROUP_ID, user_id=user_id
        )

        valid_status = {"member", "administrator", "creator"}
        valid_channel = channel_member.status in valid_status
        valid_group = group_member.status in valid_status

        if valid_channel and valid_group:
            set_verified(user_id, True)
            ref = db.execute("SELECT referred_by FROM users WHERE user_id=?", (user_id,)).fetchone()
            if ref and ref["referred_by"] and not db.execute("SELECT 1 FROM referrals WHERE referred_user_id=?", (user_id,)).fetchone():
                referrer_id = int(ref["referred_by"])
                if referrer_id != user_id and db.execute("SELECT 1 FROM users WHERE user_id=?", (referrer_id,)).fetchone():
                    reward = float(get_setting("referral_reward") or 10)
                    db.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (reward, referrer_id))
                    db.execute("INSERT INTO wallet_transactions(user_id,amount,type,description,created_at) VALUES (?,?,?,?,?)", (referrer_id,reward,"REFERRAL",f"Referral reward for {user_id}",now()))
                    db.execute("INSERT INTO referrals(referrer_id,referred_user_id,reward,created_at) VALUES (?,?,?,?)", (referrer_id,user_id,reward,now()))
                    db.commit()
                    try:
                        await callback.bot.send_message(referrer_id, f"🎉 <b>REFERRAL REWARD</b>\n\nYou earned <b>{money(reward)}</b>.\nYour wallet has been credited.", parse_mode="HTML")
                    except Exception:
                        pass
            await callback.message.edit_text(
                "🎉 <b>VERIFICATION COMPLETE!</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"👋 Welcome to <b>ApnaStore</b>, {html.escape(callback.from_user.first_name or 'there')}!\n\n"
                "Your membership is verified and your store is unlocked. 🔓\n\n"
                "🛍️ Browse products\n"
                "💰 Manage your wallet\n"
                "📦 Track your orders\n"
                "🔥 Discover fresh deals\n\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "🚀 <b>LET'S START SHOPPING!</b>",
                reply_markup=main_menu_keyboard(),
                parse_mode="HTML"
            )
            await callback.answer("✅ Membership verified!")
        else:
            missing = []
            if not valid_channel:
                missing.append("📢 Channel")
            if not valid_group:
                missing.append("👥 Group")
            await callback.answer(
                "❌ Please join:\n\n" + "\n".join(missing),
                show_alert=True
            )

    except Exception as e:
        logger.exception("Verification error")
        await callback.answer(
            "⚠️ Verification error. Make sure the bot is admin in the channel/group.",
            show_alert=True
        )


# =========================================================
# HOME
# =========================================================

@dp.callback_query(F.data == "home")
async def home_handler(callback: CallbackQuery):
    ensure_user(callback.from_user)
    await callback.message.edit_text(
        "🏠 <b>APNASTORE</b>  •  <i>HOME</i>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👋 <b>Hi {html.escape(callback.from_user.first_name or 'there')}!</b>\n"
        "Everything you need is just a tap away. ✨\n\n"
        f"💳 <b>Wallet:</b> ₹{get_balance(callback.from_user.id):.2f}\n\n"
        "🛍️ <b>SHOP</b>  — explore products\n"
        "🔥 <b>DEALS</b>  — grab special offers\n"
        "📦 <b>ORDERS</b>  — view your purchases\n"
        "💰 <b>WALLET</b>  — add & manage balance\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "✨ <b>WHAT'S YOUR NEXT MOVE?</b> 👇",
        reply_markup=main_menu_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()


# =========================================================
# WALLET
# =========================================================

def wallet_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ ADD BALANCE", callback_data="add_balance", style="success")],
        [InlineKeyboardButton(text="📜 TRANSACTIONS", callback_data="transactions", style="primary")],
        [InlineKeyboardButton(text="🏠 HOME", callback_data="home", style="primary")]
    ])


@dp.callback_query(F.data == "wallet")
async def wallet_handler(callback: CallbackQuery):
    ensure_user(callback.from_user)
    balance = get_balance(callback.from_user.id)

    await callback.message.edit_text(
        "💰 <b>MY WALLET</b>  •  <i>ACCOUNT BALANCE</i>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"💳 <b>Available Balance</b>\n<b>₹{balance:.2f}</b>\n\n"
        "⚡ Add balance securely, then use your wallet for quick checkout.\n\n"
        "💡 <b>HOW IT WORKS</b>\n"
        "➕ Add Balance  →  🛍️ Choose Product  →  💳 Pay  →  📦 Receive Item\n\n"
        "🔐 <i>Your wallet is for ApnaStore purchases only.</i>",
        reply_markup=wallet_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()


def recharge_amount_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="₹50", callback_data="recharge_amt:50", style="success"),
         InlineKeyboardButton(text="₹100", callback_data="recharge_amt:100", style="success")],
        [InlineKeyboardButton(text="₹200", callback_data="recharge_amt:200", style="success"),
         InlineKeyboardButton(text="₹500", callback_data="recharge_amt:500", style="success")],
        [InlineKeyboardButton(text="₹1000", callback_data="recharge_amt:1000", style="success")],
        [InlineKeyboardButton(text="✏️ CUSTOM AMOUNT", callback_data="recharge_custom", style="primary")],
        [InlineKeyboardButton(text="⬅️ BACK", callback_data="wallet", style="primary")]
    ])


async def show_payment_instructions(message: Message, amount: float):
    qr_file_id = get_setting("upi_qr_file_id")

    text = (
        "💳 <b>ADD BALANCE</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"💰 <b>Recharge Amount:</b> ₹{amount:.2f}\n\n"
        "📲 <b>PAYMENT DETAILS</b>\n\n"
        f"UPI ID:\n<code>{UPI_ID}</code>\n\n"
        "1️⃣ Open your UPI app\n"
        "2️⃣ Send the exact amount\n"
        "3️⃣ Complete the payment\n"
        "4️⃣ Keep your UTR / Transaction ID ready\n"
        "5️⃣ Submit the payment proof below\n\n"
        "⚠️ <i>Send the exact amount to avoid verification delays.</i>\n"
        "━━━━━━━━━━━━━━━━━━━━"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 SUBMIT PAYMENT", callback_data=f"submit_recharge:{amount}", style="success")],
        [InlineKeyboardButton(text="⬅️ BACK", callback_data="add_balance", style="primary")]
    ])

    if qr_file_id:
        await message.answer_photo(
            photo=qr_file_id,
            caption=text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    else:
        await message.answer(text, reply_markup=keyboard, parse_mode="HTML")


async def render_add_balance(callback: CallbackQuery):
    """Show the recharge amount screen safely from either a text or photo message."""
    text = (
        "➕ <b>ADD BALANCE</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "Choose how much you'd like to add to your wallet. 💳\n\n"
        f"🔹 Minimum: <b>₹{MIN_RECHARGE}</b>\n"
        f"🔹 Maximum: <b>₹{MAX_RECHARGE}</b>\n\n"
        "⚡ After payment, submit your UTR + screenshot for verification."
    )

    # Payment instructions may be a photo message (QR). Telegram does not
    # allow edit_text() on a photo message, so remove that message first.
    if callback.message.photo:
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer(
            text,
            reply_markup=recharge_amount_keyboard(),
            parse_mode="HTML"
        )
    else:
        await callback.message.edit_text(
            text,
            reply_markup=recharge_amount_keyboard(),
            parse_mode="HTML"
        )


@dp.callback_query(F.data == "add_balance")
async def add_balance_handler(callback: CallbackQuery, state: FSMContext):
    ensure_user(callback.from_user)
    await state.clear()
    await render_add_balance(callback)
    await callback.answer()


@dp.callback_query(F.data.startswith("recharge_amt:"))
async def fixed_recharge_amount(callback: CallbackQuery, state: FSMContext):
    amount = float(callback.data.split(":")[1])
    if amount < MIN_RECHARGE or amount > MAX_RECHARGE:
        await callback.answer("❌ Invalid recharge amount.", show_alert=True)
        return
    await state.update_data(recharge_amount=amount)
    await show_payment_instructions(callback.message, amount)
    await callback.answer()


@dp.callback_query(F.data == "recharge_custom")
async def custom_recharge(callback: CallbackQuery, state: FSMContext):
    await state.set_state(RechargeStates.waiting_amount)
    await callback.message.edit_text(
        "✏️ <b>CUSTOM RECHARGE</b>\n\n"
        f"Enter amount between ₹{MIN_RECHARGE} and ₹{MAX_RECHARGE}.\n\n"
        "Example: <code>750</code>",
        parse_mode="HTML"
    )
    await callback.answer()


@dp.message(RechargeStates.waiting_amount)
async def custom_amount_received(message: Message, state: FSMContext):
    try:
        amount = float(message.text.strip())
    except (ValueError, AttributeError):
        await message.answer("❌ Please enter a valid number.")
        return

    if amount < MIN_RECHARGE or amount > MAX_RECHARGE:
        await message.answer(
            f"❌ Amount must be between ₹{MIN_RECHARGE} and ₹{MAX_RECHARGE}."
        )
        return

    amount = round(amount, 2)
    await state.update_data(recharge_amount=amount)
    await state.clear()
    await show_payment_instructions(message, amount)


@dp.callback_query(F.data.startswith("submit_recharge:"))
async def submit_recharge_start(callback: CallbackQuery, state: FSMContext):
    amount = round(float(callback.data.split(":")[1]), 2)
    if amount < MIN_RECHARGE or amount > MAX_RECHARGE:
        await callback.answer("❌ Invalid recharge amount.", show_alert=True)
        return

    await state.update_data(recharge_amount=amount)
    await state.set_state(RechargeStates.waiting_utr)

    await callback.message.answer(
        f"🧾 <b>PAYMENT VERIFICATION</b>\n\n"
        f"Amount: <b>₹{amount:.2f}</b>\n\n"
        "Please send your <b>UTR / Transaction ID</b>.\n\n"
        "Example: <code>123456789012</code>",
        parse_mode="HTML"
    )
    await callback.answer()


@dp.message(RechargeStates.waiting_utr)
async def recharge_utr_received(message: Message, state: FSMContext):
    utr = (message.text or "").strip()
    utr_display = html.escape(utr)

    if len(utr) < 4 or len(utr) > 100:
        await message.answer("❌ Please send a valid UTR / Transaction ID.")
        return

    await state.update_data(utr=utr)
    await state.set_state(RechargeStates.waiting_screenshot)

    await message.answer(
        "📸 <b>NOW SEND PAYMENT SCREENSHOT</b>\n\n"
        "Send the screenshot/photo of your successful payment.",
        parse_mode="HTML"
    )


@dp.message(RechargeStates.waiting_screenshot, F.photo)
async def recharge_screenshot_received(message: Message, state: FSMContext):
    data = await state.get_data()
    amount = float(data["recharge_amount"])
    utr = data["utr"]
    screenshot_file_id = message.photo[-1].file_id

    # Prevent the exact same UTR from being submitted again.
    existing = db.execute(
        "SELECT id, status FROM recharge_requests WHERE utr=?",
        (utr,)
    ).fetchone()

    if existing:
        await state.clear()
        await message.answer(
            "⚠️ This UTR has already been submitted.\n"
            f"Status: <b>{existing['status'].upper()}</b>",
            parse_mode="HTML"
        )
        return

    db.execute("""
        INSERT INTO recharge_requests
        (user_id, amount, utr, screenshot_file_id, status, created_at)
        VALUES (?, ?, ?, ?, 'pending', ?)
    """, (
        message.from_user.id,
        amount,
        utr,
        screenshot_file_id,
        now()
    ))
    db.commit()

    request_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    await state.clear()

    await message.answer(
        "✅ <b>PAYMENT SUBMITTED</b>\n\n"
        f"🆔 Request: <code>#{request_id}</code>\n"
        f"💰 Amount: <b>₹{amount:.2f}</b>\n"
        f"🧾 UTR: <code>{utr_display}</code>\n\n"
        "⏳ Your payment is waiting for admin verification.\n"
        "Your wallet will be credited after approval.",
        reply_markup=back_home_keyboard(),
        parse_mode="HTML"
    )

    user = message.from_user
    username = f"@{user.username}" if user.username else "No username"

    admin_text = (
        "💳 <b>NEW RECHARGE REQUEST</b>\n\n"
        f"🆔 Request: <code>#{request_id}</code>\n"
        f"👤 User: <code>{user.id}</code>\n"
        f"📛 Name: {user.first_name or '-'}\n"
        f"🔗 Username: {username}\n"
        f"💰 Amount: <b>₹{amount:.2f}</b>\n"
        f"🧾 UTR: <code>{utr_display}</code>\n"
        f"🕐 Time: {now()}"
    )

    admin_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ APPROVE", callback_data=f"approve_recharge:{request_id}", style="success"),
         InlineKeyboardButton(text="❌ REJECT", callback_data=f"reject_recharge:{request_id}", style="danger")],
    ])

    await message.bot.send_photo(
        chat_id=ADMIN_ID,
        photo=screenshot_file_id,
        caption=admin_text,
        reply_markup=admin_keyboard,
        parse_mode="HTML"
    )


@dp.message(RechargeStates.waiting_screenshot)
async def recharge_screenshot_invalid(message: Message):
    await message.answer("📸 Please send the payment screenshot as a photo.")


# =========================================================
# TRANSACTIONS
# =========================================================

@dp.callback_query(F.data == "transactions")
async def transactions_handler(callback: CallbackQuery):
    rows = db.execute("""
        SELECT * FROM wallet_transactions
        WHERE user_id=?
        ORDER BY id DESC LIMIT 10
    """, (callback.from_user.id,)).fetchall()

    if not rows:
        text = "📜 <b>TRANSACTIONS</b>\n\nNo transactions yet."
    else:
        lines = ["📜 <b>RECENT TRANSACTIONS</b>\n"]
        for row in rows:
            sign = "+" if row["amount"] >= 0 else ""
            lines.append(
                f"• {sign}₹{row['amount']:.2f} — {row['type']}\n"
                f"  {row['description'] or ''}\n"
                f"  <i>{row['created_at']}</i>\n"
            )
        text = "\n".join(lines)

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ BACK", callback_data="wallet", style="primary")],
            [InlineKeyboardButton(text="🏠 HOME", callback_data="home", style="primary")]
        ]),
        parse_mode="HTML"
    )
    await callback.answer()


# =========================================================
# ADMIN PANEL
# =========================================================

def admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 DASHBOARD", callback_data="admin_dashboard", style="primary")],
        [InlineKeyboardButton(text="💳 PENDING PAYMENTS", callback_data="admin_payments", style="primary")],
        [InlineKeyboardButton(text="🛍️ PRODUCTS", callback_data="admin_products", style="success")],
        [InlineKeyboardButton(text="📦 ADD STOCK", callback_data="admin_stock", style="success")],
        [InlineKeyboardButton(text="👥 USERS", callback_data="admin_users", style="primary")],
        [InlineKeyboardButton(text="💰 WALLET ADJUST", callback_data="admin_wallet", style="success")],
        [InlineKeyboardButton(text="📢 BROADCAST", callback_data="admin_broadcast", style="success")],
        [InlineKeyboardButton(text="🖼️ PAYMENT QR", callback_data="admin_qr", style="primary")],
        [InlineKeyboardButton(text="👑 ADMINS", callback_data="admin_admins", style="primary")],
    ])


def is_super_admin(user_id):
    return user_id == ADMIN_ID


def is_admin(user_id):
    if user_id == ADMIN_ID:
        return True
    row = db.execute("SELECT user_id FROM admins WHERE user_id=?", (user_id,)).fetchone()
    return row is not None


def list_admins():
    return db.execute(
        """
        SELECT a.*, u.first_name, u.username
        FROM admins a
        LEFT JOIN users u ON u.user_id=a.user_id
        ORDER BY CASE WHEN a.role='owner' THEN 0 ELSE 1 END, a.created_at ASC
        """
    ).fetchall()


@dp.message(Command("admin"))
async def admin_command(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Admin access denied.")
        return

    await message.answer(
        "🛠️ <b>APNASTORE ADMIN PANEL</b>\n\n"
        "Manage payments, products, stock, users, wallet and QR.",
        reply_markup=admin_keyboard(),
        parse_mode="HTML"
    )



@dp.callback_query(F.data == "admin_admins")
async def admin_admins(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Admin only.", show_alert=True)
        return

    admins = list_admins()
    lines = ["👑 <b>ADMIN MANAGEMENT</b>\n"]
    buttons = []

    for admin in admins:
        name = admin["first_name"] or "User"
        username = f"@{admin['username']}" if admin["username"] else "No username"
        role = "👑 OWNER" if admin["role"] == "owner" else "🛡️ ADMIN"
        lines.append(
            f"{role}\n"
            f"👤 {html.escape(name)} ({html.escape(username)})\n"
            f"🆔 <code>{admin['user_id']}</code>\n"
            f"🕐 {html.escape(admin['created_at'])}\n"
        )
        if admin["role"] != "owner" and is_super_admin(callback.from_user.id):
            buttons.append([InlineKeyboardButton(
                text=f"🗑️ REMOVE {admin['user_id']}",
                callback_data=f"remove_admin:{admin['user_id']}",
                style="danger",
            )])

    if is_super_admin(callback.from_user.id):
        buttons.append([InlineKeyboardButton(
            text="➕ ADD ADMIN", callback_data="add_admin", style="success"
        )])
    else:
        lines.append("\n🔒 Only the owner can add or remove administrators.")

    buttons.append([InlineKeyboardButton(
        text="⬅️ ADMIN PANEL", callback_data="admin_back", style="primary"
    )])

    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML",
    )
    await callback.answer()


@dp.callback_query(F.data == "add_admin")
async def add_admin_start(callback: CallbackQuery, state: FSMContext):
    if not is_super_admin(callback.from_user.id):
        await callback.answer("❌ Owner only.", show_alert=True)
        return

    await state.set_state(AdminStates.waiting_add_admin_id)
    await callback.message.edit_text(
        "➕ <b>ADD NEW ADMIN</b>\n\n"
        "Send the Telegram <b>User ID</b> of the person you want to make an admin.\n\n"
        "The person should start the bot first so their name/username can be shown here.\n\n"
        "Example:\n<code>123456789</code>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ CANCEL", callback_data="add_admin_cancel", style="danger")]
        ]),
        parse_mode="HTML",
    )
    await callback.answer()


@dp.callback_query(F.data == "add_admin_cancel")
async def add_admin_cancel(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Admin only.", show_alert=True)
        return
    await state.clear()
    await callback.message.edit_text(
        "🛠️ <b>APNASTORE ADMIN PANEL</b>",
        reply_markup=admin_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer("Cancelled.")


@dp.message(AdminStates.waiting_add_admin_id)
async def add_admin_received(message: Message, state: FSMContext):
    if not is_super_admin(message.from_user.id):
        await state.clear()
        return

    try:
        new_admin_id = int((message.text or "").strip())
    except ValueError:
        await message.answer("❌ Please send a numeric Telegram User ID.")
        return

    if new_admin_id <= 0:
        await message.answer("❌ Invalid Telegram User ID.")
        return

    if new_admin_id == ADMIN_ID:
        await state.clear()
        await message.answer("👑 This account is already the permanent owner.", reply_markup=admin_keyboard())
        return

    existing = db.execute("SELECT user_id FROM admins WHERE user_id=?", (new_admin_id,)).fetchone()
    if existing:
        await state.clear()
        await message.answer("⚠️ This user is already an administrator.", reply_markup=admin_keyboard())
        return

    target = db.execute(
        "SELECT user_id, first_name, username FROM users WHERE user_id=?",
        (new_admin_id,),
    ).fetchone()
    if not target:
        await message.answer(
            "❌ User not found in ApnaStore database.\n\n"
            "Ask this person to open the bot and send /start first, then try again."
        )
        return

    db.execute(
        "INSERT INTO admins(user_id, role, added_by, created_at) VALUES (?, 'admin', ?, ?)",
        (new_admin_id, message.from_user.id, now()),
    )
    db.commit()
    await state.clear()

    username = f"@{target['username']}" if target['username'] else "No username"
    await message.answer(
        "✅ <b>ADMIN ADDED</b>\n\n"
        f"👤 {html.escape(target['first_name'] or 'User')}\n"
        f"🔗 {html.escape(username)}\n"
        f"🆔 <code>{new_admin_id}</code>\n\n"
        "This user can now open <code>/admin</code> and manage the store.",
        reply_markup=admin_keyboard(),
        parse_mode="HTML",
    )
    try:
        await message.bot.send_message(
            new_admin_id,
            "👑 <b>APNASTORE ADMIN ACCESS</b>\n\n"
            "You have been added as an administrator.\n\n"
            "Use /admin to open the Admin Panel.",
            parse_mode="HTML",
        )
    except Exception as error:
        logger.warning("Could not notify new admin %s: %s", new_admin_id, error)


@dp.callback_query(F.data.startswith("remove_admin:"))
async def remove_admin(callback: CallbackQuery):
    if not is_super_admin(callback.from_user.id):
        await callback.answer("❌ Owner only.", show_alert=True)
        return

    try:
        admin_id = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("❌ Invalid admin ID.", show_alert=True)
        return

    if admin_id == ADMIN_ID:
        await callback.answer("❌ The permanent owner cannot be removed.", show_alert=True)
        return

    changed = db.execute(
        "DELETE FROM admins WHERE user_id=? AND role!='owner'",
        (admin_id,),
    ).rowcount
    db.commit()

    if changed:
        await callback.answer("✅ Admin access removed.")
    else:
        await callback.answer("⚠️ Admin not found.", show_alert=True)

    await admin_admins(callback)


@dp.callback_query(F.data == "admin_dashboard")
async def admin_dashboard(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Admin only.", show_alert=True)
        return

    users = db.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
    products = db.execute("SELECT COUNT(*) c FROM products WHERE active=1").fetchone()["c"]
    pending = db.execute(
        "SELECT COUNT(*) c FROM recharge_requests WHERE status='pending'"
    ).fetchone()["c"]
    sold = db.execute("SELECT COUNT(*) c FROM stock WHERE sold=1").fetchone()["c"]
    stock_count = db.execute("SELECT COUNT(*) c FROM stock WHERE sold=0").fetchone()["c"]

    await callback.message.edit_text(
        "📊 <b>ADMIN DASHBOARD</b>\n\n"
        f"👥 Users: <b>{users}</b>\n"
        f"🛍️ Active Products: <b>{products}</b>\n"
        f"📦 Available Stock: <b>{stock_count}</b>\n"
        f"✅ Sold Items: <b>{sold}</b>\n"
        f"💳 Pending Payments: <b>{pending}</b>",
        reply_markup=admin_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()


# =========================================================
# ADMIN PAYMENTS
# =========================================================

@dp.callback_query(F.data == "admin_payments")
async def admin_payments(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Admin only.", show_alert=True)
        return

    rows = db.execute("""
        SELECT r.*, u.first_name, u.username
        FROM recharge_requests r
        LEFT JOIN users u ON u.user_id=r.user_id
        WHERE r.status='pending'
        ORDER BY r.id ASC
        LIMIT 20
    """).fetchall()

    if not rows:
        text = "💳 <b>PENDING PAYMENTS</b>\n\n✅ No pending payment requests."
        keyboard = admin_keyboard()
    else:
        lines = ["💳 <b>PENDING PAYMENTS</b>\n"]
        buttons = []

        for r in rows:
            username = f"@{r['username']}" if r["username"] else "No username"
            lines.append(
                f"🆔 <b>#{r['id']}</b> • ₹{r['amount']:.2f}\n"
                f"👤 {r['first_name'] or '-'} ({username})\n"
                f"🧾 <code>{r['utr']}</code>\n"
                f"🕐 {r['created_at']}\n"
            )
            buttons.append([
                InlineKeyboardButton(
                    text=f"👁️ VIEW #{r['id']}",
                    callback_data=f"view_recharge:{r['id']}",
                    style="primary"
                )
            ])

        buttons.append([InlineKeyboardButton(text="⬅️ ADMIN", callback_data="admin_back", style="primary")])
        text = "\n".join(lines)
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")


@dp.callback_query(F.data == "admin_back")
async def admin_back(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Admin only.", show_alert=True)
        return

    await callback.message.edit_text(
        "🛠️ <b>APNASTORE ADMIN PANEL</b>",
        reply_markup=admin_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("view_recharge:"))
async def view_recharge(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Admin only.", show_alert=True)
        return

    request_id = int(callback.data.split(":")[1])
    row = db.execute("""
        SELECT r.*, u.first_name, u.username
        FROM recharge_requests r
        LEFT JOIN users u ON u.user_id=r.user_id
        WHERE r.id=?
    """, (request_id,)).fetchone()

    if not row:
        await callback.answer("❌ Request not found.", show_alert=True)
        return

    username = f"@{row['username']}" if row["username"] else "No username"

    caption = (
        "💳 <b>RECHARGE REQUEST</b>\n\n"
        f"🆔 Request: <code>#{row['id']}</code>\n"
        f"👤 User ID: <code>{row['user_id']}</code>\n"
        f"📛 Name: {row['first_name'] or '-'}\n"
        f"🔗 Username: {username}\n"
        f"💰 Amount: <b>₹{row['amount']:.2f}</b>\n"
        f"🧾 UTR: <code>{html.escape(row['utr'])}</code>\n"
        f"📌 Status: <b>{row['status'].upper()}</b>\n"
        f"🕐 Created: {row['created_at']}"
    )

    buttons = []
    if row["status"] == "pending":
        buttons.append([
            InlineKeyboardButton(text="✅ APPROVE", callback_data=f"approve_recharge:{request_id}", style="success"),
            InlineKeyboardButton(text="❌ REJECT", callback_data=f"reject_recharge:{request_id}", style="danger")
        ])
    buttons.append([InlineKeyboardButton(text="⬅️ PENDING", callback_data="admin_payments", style="primary")])

    await callback.message.answer_photo(
        photo=row["screenshot_file_id"],
        caption=caption,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML"
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("approve_recharge:"))
async def approve_recharge(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Admin only.", show_alert=True)
        return

    request_id = int(callback.data.split(":")[1])

    # Atomic-ish protection: only the first admin action can change pending -> approved.
    db.execute("BEGIN IMMEDIATE")
    row = db.execute(
        "SELECT * FROM recharge_requests WHERE id=?",
        (request_id,)
    ).fetchone()

    if not row:
        db.rollback()
        await callback.answer("❌ Request not found.", show_alert=True)
        return

    if row["status"] != "pending":
        db.rollback()
        await callback.answer(
            f"⚠️ Already {row['status'].upper()}.",
            show_alert=True
        )
        return

    db.execute(
        "UPDATE users SET balance=balance+? WHERE user_id=?",
        (row["amount"], row["user_id"])
    )
    db.execute("""
        INSERT INTO wallet_transactions
        (user_id, amount, type, description, created_at)
        VALUES (?, ?, 'RECHARGE', ?, ?)
    """, (
        row["user_id"],
        row["amount"],
        f"Manual recharge #{request_id}",
        now()
    ))
    db.execute("""
        UPDATE recharge_requests
        SET status='approved', reviewed_at=?
        WHERE id=?
    """, (now(), request_id))
    db.commit()

    new_balance = get_balance(row["user_id"])

    await callback.answer("✅ Payment approved and wallet credited.")
    await callback.message.edit_caption(
        caption=(
            f"✅ <b>APPROVED</b>\n\n"
            f"🆔 Request: <code>#{request_id}</code>\n"
            f"👤 User: <code>{row['user_id']}</code>\n"
            f"💰 Credited: <b>₹{row['amount']:.2f}</b>\n"
            f"💳 New Balance: <b>₹{new_balance:.2f}</b>\n"
            f"🕐 {now()}"
        ),
        reply_markup=None,
        parse_mode="HTML"
    )

    try:
        await callback.bot.send_message(
            row["user_id"],
            "🎉 <b>PAYMENT APPROVED</b>\n\n"
            f"💰 Amount: <b>₹{row['amount']:.2f}</b>\n"
            f"🧾 Request: <code>#{request_id}</code>\n"
            f"💳 New Wallet Balance: <b>₹{new_balance:.2f}</b>\n\n"
            "Your wallet has been credited successfully. ✅",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.exception("User notification error")


@dp.callback_query(F.data.startswith("reject_recharge:"))
async def reject_recharge(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Admin only.", show_alert=True)
        return

    request_id = int(callback.data.split(":")[1])
    row = db.execute(
        "SELECT * FROM recharge_requests WHERE id=?",
        (request_id,)
    ).fetchone()

    if not row:
        await callback.answer("❌ Request not found.", show_alert=True)
        return

    if row["status"] != "pending":
        await callback.answer(
            f"⚠️ Already {row['status'].upper()}.",
            show_alert=True
        )
        return

    db.execute("""
        UPDATE recharge_requests
        SET status='rejected', reviewed_at=?
        WHERE id=? AND status='pending'
    """, (now(), request_id))
    changed = db.execute("SELECT changes()").fetchone()[0]
    db.commit()

    if changed != 1:
        await callback.answer("⚠️ Request was already reviewed.", show_alert=True)
        return

    await callback.answer("❌ Payment rejected.")
    await callback.message.edit_caption(
        caption=(
            "❌ <b>PAYMENT REJECTED</b>\n\n"
            f"🆔 Request: <code>#{request_id}</code>\n"
            f"💰 Amount: ₹{row['amount']:.2f}\n"
            f"🧾 UTR: <code>{html.escape(row['utr'])}</code>\n"
            f"🕐 {now()}"
        ),
        reply_markup=None,
        parse_mode="HTML"
    )

    try:
        await callback.bot.send_message(
            row["user_id"],
            "❌ <b>PAYMENT REJECTED</b>\n\n"
            f"🧾 Request: <code>#{request_id}</code>\n"
            f"💰 Amount: <b>₹{row['amount']:.2f}</b>\n\n"
            "Please contact support if you believe this was rejected by mistake.",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.exception("User notification error")


# =========================================================
# ADMIN QR MANAGEMENT
# =========================================================

@dp.callback_query(F.data == "admin_qr")
async def admin_qr(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Admin only.", show_alert=True)
        return

    qr = get_setting("upi_qr_file_id")

    text = (
        "🖼️ <b>PAYMENT QR MANAGEMENT</b>\n\n"
        f"UPI ID:\n<code>{UPI_ID}</code>\n\n"
        f"Current QR: {'✅ SET' if qr else '❌ NOT SET'}\n\n"
        "You can add a new QR, replace the current QR, or remove it."
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ ADD / CHANGE QR", callback_data="qr_change", style="success")],
        [InlineKeyboardButton(text="🗑️ REMOVE QR", callback_data="qr_remove", style="danger")],
        [InlineKeyboardButton(text="⬅️ ADMIN", callback_data="admin_back", style="primary")]
    ])

    if qr:
        await callback.message.answer_photo(
            photo=qr,
            caption=text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    else:
        await callback.message.edit_text(
            text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )

    await callback.answer()


@dp.callback_query(F.data == "qr_change")
async def qr_change_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Admin only.", show_alert=True)
        return

    await state.update_data(waiting_qr=True)
    await callback.message.answer(
        "🖼️ <b>SEND NEW PAYMENT QR</b>\n\n"
        "Send the QR image as a photo.\n"
        "The new QR will automatically replace the old one.",
        parse_mode="HTML"
    )
    await state.set_state("waiting_qr")
    await callback.answer()


@dp.message(F.photo)
async def generic_photo_handler(message: Message, state: FSMContext):
    current = await state.get_state()

    if current != "waiting_qr":
        return

    if not is_admin(message.from_user.id):
        return

    file_id = message.photo[-1].file_id
    set_setting("upi_qr_file_id", file_id)
    await state.clear()

    await message.answer(
        "✅ <b>PAYMENT QR UPDATED</b>\n\n"
        "The new QR is now active for customer payments.",
        reply_markup=admin_keyboard(),
        parse_mode="HTML"
    )


@dp.callback_query(F.data == "qr_remove")
async def qr_remove(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Admin only.", show_alert=True)
        return

    set_setting("upi_qr_file_id", "")
    await callback.answer("🗑️ QR removed.")
    await callback.message.edit_text(
        "🖼️ <b>PAYMENT QR</b>\n\n"
        "❌ QR removed successfully.\n\n"
        "Customers will now see the UPI ID without a QR.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ ADD / CHANGE QR", callback_data="qr_change", style="success")],
            [InlineKeyboardButton(text="⬅️ ADMIN", callback_data="admin_back", style="primary")]
        ]),
        parse_mode="HTML"
    )


# =========================================================
# PRODUCTS
# =========================================================

def product_categories():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎬 ENTERTAINMENT", callback_data="cat:Entertainment", style="success")],
        [InlineKeyboardButton(text="🎟️ COUPONS & VOUCHERS", callback_data="cat:Coupons", style="primary")],
        [InlineKeyboardButton(text="💎 DIGITAL PRODUCTS", callback_data="cat:Digital Products", style="success")],
        [InlineKeyboardButton(text="🏠 HOME", callback_data="home", style="primary")]
    ])


@dp.callback_query(F.data == "shop")
async def shop_handler(callback: CallbackQuery):
    await callback.message.edit_text(
        "🛍️ <b>APNASTORE SHOP</b>  •  <i>STORE</i>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "Find what you need and checkout in a few taps. ⚡\n\n"
        "🎬 <b>Entertainment</b>\n"
        "Subscriptions & digital access\n\n"
        "🎟️ <b>Coupons & Vouchers</b>\n"
        "Deals to help you save more\n\n"
        "💎 <b>Digital Products</b>\n"
        "Useful digital items with quick delivery\n\n"
        "👇 <b>SELECT A CATEGORY</b>",
        reply_markup=product_categories(),
        parse_mode="HTML"
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("cat:"))
async def category_handler(callback: CallbackQuery):
    category = callback.data.split(":", 1)[1]
    rows = db.execute("""
        SELECT p.*,
               (SELECT COUNT(*) FROM stock s WHERE s.product_id=p.id AND s.sold=0) AS available
        FROM products p
        WHERE p.active=1 AND p.category=?
          AND (SELECT COUNT(*) FROM stock s2 WHERE s2.product_id=p.id AND s2.sold=0) > 0
        ORDER BY p.id DESC
    """, (category,)).fetchall()

    buttons = []
    for p in rows:
        effective = p["sale_price"] if p["sale_price"] is not None and p["sale_price"] > 0 else p["price"]
        price_text = f"🏷️ ₹{effective:.0f}" if effective < p["price"] else f"₹{p['price']:.0f}"
        buttons.append([
            InlineKeyboardButton(
                text=f"🛍️ {html.escape(p['name'])} • {price_text} • {p['available']} left",
                callback_data=f"product:{p['id']}",
                style="success"
            )
        ])

    buttons.append([InlineKeyboardButton(text="⬅️ CATEGORIES", callback_data="shop", style="primary")])

    if not rows:
        text = (
            f"📂 <b>{html.escape(category.upper())}</b>\n\n"
            "😕 Nothing is available here right now.\n"
            "Please check another category or come back soon. 💙"
        )
    else:
        text = (
            f"📂 <b>{html.escape(category.upper())}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🛍️ <b>{len(rows)}</b> product(s) available\n"
            "Choose a product below to view its price, stock and details. 👇"
        )

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML"
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("product:"))
async def product_details(callback: CallbackQuery):
    product_id = int(callback.data.split(":")[1])
    p = db.execute("""
        SELECT p.*,
               (SELECT COUNT(*) FROM stock s WHERE s.product_id=p.id AND s.sold=0) AS available
        FROM products p WHERE p.id=? AND p.active=1
    """, (product_id,)).fetchone()

    if not p:
        await callback.answer("❌ Product unavailable.", show_alert=True)
        return

    avg_row=db.execute("SELECT AVG(rating) avg, COUNT(*) cnt FROM reviews WHERE product_id=?",(product_id,)).fetchone()
    rating_text=f"⭐ {avg_row['avg']:.1f}/5 ({avg_row['cnt']} reviews)" if avg_row['avg'] else "⭐ No reviews yet"
    text = (
        f"🛍️ <b>{html.escape(p['name'])}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"💰 <b>Price:</b> ₹{(p['sale_price'] if p['sale_price'] and p['sale_price'] > 0 else p['price']):.2f}" + (f"  <s>₹{p['price']:.2f}</s>" if p['sale_price'] and p['sale_price'] > 0 else "") + "\n"
        f"📦 <b>Available:</b> {p['available']}\n"
        f"📂 <b>Category:</b> {html.escape(p['category'])}\n"
        f"{rating_text}\n\n"
        "📋 <b>PRODUCT DETAILS</b>\n"
        f"{html.escape(p['description'] or 'Premium digital product.')}\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "⚡ <b>Instant delivery</b> after successful purchase\n"
        "🔐 <b>Simple checkout</b> through your wallet"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 BUY NOW", callback_data=f"checkout:{product_id}", style="success")],
        [InlineKeyboardButton(text="❤️ SAVE FOR LATER", callback_data=f"wishlist_add:{product_id}", style="primary")],
        [InlineKeyboardButton(text="⬅️ BACK", callback_data=f"cat:{p['category']}", style="primary")]
    ])

    if p["image_file_id"]:
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer_photo(
            photo=p["image_file_id"],
            caption=text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    else:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data.startswith("buy:"))
async def buy_product(callback: CallbackQuery):
    if not is_verified(callback.from_user.id):
        await callback.answer("❌ Please verify membership first.", show_alert=True)
        return

    user_id = callback.from_user.id
    product_id = int(callback.data.split(":")[1])

    p = db.execute("""
        SELECT p.*,
               (SELECT COUNT(*) FROM stock s WHERE s.product_id=p.id AND s.sold=0) AS available
        FROM products p WHERE p.id=? AND p.active=1
    """, (product_id,)).fetchone()

    if not p or p["available"] <= 0:
        await callback.answer("❌ Out of stock.", show_alert=True)
        return

    sale_price = p["sale_price"] if p["sale_price"] is not None and p["sale_price"] > 0 else p["price"]
    balance = get_balance(user_id)
    if balance < sale_price:
        await callback.answer(
            f"❌ Insufficient balance. Need ₹{sale_price:.2f}.",
            show_alert=True
        )
        return

    stock_item = db.execute("""
        SELECT * FROM stock
        WHERE product_id=? AND sold=0
        ORDER BY id ASC LIMIT 1
    """, (product_id,)).fetchone()

    if not stock_item:
        await callback.answer("❌ Out of stock.", show_alert=True)
        return

    db.execute("BEGIN IMMEDIATE")

    try:
        db.execute(
            "UPDATE users SET balance=balance-? WHERE user_id=? AND balance>=?",
            (p["price"], user_id, p["price"])
        )

        changed = db.execute("SELECT changes()").fetchone()[0]
        if changed != 1:
            db.rollback()
            await callback.answer("❌ Insufficient balance.", show_alert=True)
            return

        db.execute("""
            UPDATE stock
            SET sold=1, sold_to=?, sold_at=?
            WHERE id=? AND sold=0
        """, (user_id, now(), stock_item["id"]))

        if db.execute("SELECT changes()").fetchone()[0] != 1:
            db.rollback()
            await callback.answer("❌ Stock just sold out.", show_alert=True)
            return

        db.execute("""
            INSERT INTO orders(user_id, product_id, stock_id, amount, item, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            user_id, product_id, stock_item["id"], p["price"],
            stock_item["item"], now()
        ))

        db.execute("""
            INSERT INTO wallet_transactions
            (user_id, amount, type, description, created_at)
            VALUES (?, ?, 'PURCHASE', ?, ?)
        """, (
            user_id, -p["price"], f"Purchase: {p['name']}", now()
        ))

        db.commit()

    except Exception as e:
        db.rollback()
        logger.exception("Purchase error")
        await callback.answer("⚠️ Purchase failed. Try again.", show_alert=True)
        return

    new_balance = get_balance(user_id)

    await callback.message.edit_text(
        "🎉 <b>ORDER CONFIRMED!</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🛍️ <b>Product:</b> {html.escape(p['name'])}\n"
        f"💰 <b>Paid:</b> ₹{p['price']:.2f}\n"
        f"💳 <b>New Balance:</b> ₹{new_balance:.2f}\n\n"
        "📦 <b>YOUR DIGITAL ITEM</b>\n\n"
        f"<code>{html.escape(stock_item['item'])}</code>\n\n"
        "⚠️ <i>Keep your delivered item private and secure.</i>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "✅ <b>Thank you for shopping with ApnaStore!</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📦 MY ORDERS", callback_data="orders", style="primary")],
            [InlineKeyboardButton(text="🏠 HOME", callback_data="home", style="primary")]
        ]),
        parse_mode="HTML"
    )
    await callback.answer("✅ Delivered!")


# =========================================================
# ADMIN PRODUCT MANAGEMENT
# =========================================================

@dp.callback_query(F.data == "admin_products")
async def admin_products(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Admin only.", show_alert=True)
        return

    rows = db.execute("""
        SELECT p.*,
               (SELECT COUNT(*) FROM stock s WHERE s.product_id=p.id AND s.sold=0) AS available
        FROM products p ORDER BY p.id DESC LIMIT 30
    """).fetchall()

    lines = ["🛍️ <b>PRODUCT MANAGEMENT</b>\n",
             "Use a product button to edit price, description, image, discount, status or delete it.\n"]
    buttons = []
    for p in rows:
        effective = p["sale_price"] if p["sale_price"] is not None and p["sale_price"] > 0 else p["price"]
        status = "🟢 ON" if p["active"] else "🔴 OFF"
        sale = f" • 🏷️ ₹{effective:.2f}" if effective < p["price"] else f" • ₹{p['price']:.2f}"
        lines.append(f"#{p['id']} • <b>{html.escape(p['name'])}</b> • {status} • 📦 {p['available']}{sale}")
        buttons.append([InlineKeyboardButton(text=f"⚙️ #{p['id']} {p['name']}", callback_data=f"admin_product:{p['id']}", style="primary")])

    buttons += [
        [InlineKeyboardButton(text="➕ ADD PRODUCT", callback_data="add_product", style="success")],
        [InlineKeyboardButton(text="⬅️ ADMIN", callback_data="admin_back", style="primary")]
    ]
    await callback.message.edit_text("\n".join(lines) if rows else "🛍️ <b>PRODUCT MANAGEMENT</b>\n\nNo products yet.", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data.startswith("admin_product:"))
async def admin_product_manage(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Admin only.", show_alert=True)
        return
    product_id = int(callback.data.split(":", 1)[1])
    p = db.execute("""
        SELECT p.*, (SELECT COUNT(*) FROM stock s WHERE s.product_id=p.id AND s.sold=0) AS available,
               (SELECT COUNT(*) FROM orders o WHERE o.product_id=p.id) AS order_count
        FROM products p WHERE p.id=?
    """, (product_id,)).fetchone()
    if not p:
        await callback.answer("❌ Product not found.", show_alert=True)
        return
    effective = p["sale_price"] if p["sale_price"] is not None and p["sale_price"] > 0 else p["price"]
    discount = max(0, p["price"] - effective)
    text = (f"🛍️ <b>{html.escape(p['name'])}</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🆔 ID: <code>{p['id']}</code>\n📂 Category: {html.escape(p['category'])}\n"
            f"💰 MRP: ₹{p['price']:.2f}\n🏷️ Sale: ₹{effective:.2f}\n🎯 Discount: ₹{discount:.2f}\n"
            f"📦 Available: {p['available']}\n{'🟢 Active' if p['active'] else '🔴 Disabled'}\n"
            f"🖼️ Image: {'Added' if p['image_file_id'] else 'Not added'}\n\n"
            f"📝 {html.escape(p['description'] or 'No description')}\n")
    buttons = [
        [InlineKeyboardButton(text="✏️ NAME", callback_data=f"pedit_name:{product_id}", style="primary"), InlineKeyboardButton(text="📝 DESCRIPTION", callback_data=f"pedit_desc:{product_id}", style="primary")],
        [InlineKeyboardButton(text="💰 PRICE", callback_data=f"pedit_price:{product_id}", style="success"), InlineKeyboardButton(text="🏷️ DISCOUNT", callback_data=f"pedit_sale:{product_id}", style="success")],
        [InlineKeyboardButton(text="🖼️ ADD / CHANGE IMAGE", callback_data=f"pedit_image:{product_id}", style="primary")],
        [InlineKeyboardButton(text="📦 ADD STOCK", callback_data=f"pstock_add:{product_id}", style="success"), InlineKeyboardButton(text="➖ REMOVE STOCK", callback_data=f"pstock_remove:{product_id}", style="danger")],
        [InlineKeyboardButton(
                    text="🔴 DISABLE" if p['active'] else "🟢 ENABLE",
                    callback_data=f"p_toggle:{product_id}",
                    style="danger" if p['active'] else "success"
                )],
        [InlineKeyboardButton(text="🗑️ DELETE", callback_data=f"p_delete:{product_id}", style="danger")],
        [InlineKeyboardButton(text="⬅️ PRODUCTS", callback_data="admin_products", style="primary")],
    ]
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data.startswith("p_toggle:"))
async def product_toggle(callback: CallbackQuery):
    if not is_admin(callback.from_user.id): return await callback.answer("❌ Admin only.", show_alert=True)
    pid=int(callback.data.split(":",1)[1])
    db.execute("UPDATE products SET active=CASE active WHEN 1 THEN 0 ELSE 1 END WHERE id=?", (pid,)); db.commit()
    await callback.answer("✅ Product status updated.")
    await admin_product_manage(CallbackQuery.model_validate(callback.model_dump(update={"data":f"admin_product:{pid}"})))


@dp.callback_query(F.data.startswith("p_delete:"))
async def product_delete(callback: CallbackQuery):
    if not is_admin(callback.from_user.id): return await callback.answer("❌ Admin only.", show_alert=True)
    pid=int(callback.data.split(":",1)[1])
    orders=db.execute("SELECT COUNT(*) c FROM orders WHERE product_id=?",(pid,)).fetchone()["c"]
    if orders:
        await callback.answer("⚠️ This product has orders. Disable it instead of deleting.", show_alert=True); return
    db.execute("DELETE FROM products WHERE id=?",(pid,)); db.commit()
    await callback.answer("🗑️ Product deleted.")
    await callback.message.edit_text("✅ <b>PRODUCT DELETED</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ PRODUCTS", callback_data="admin_products", style="primary")]]), parse_mode="HTML")


@dp.callback_query(F.data == "add_product")
async def add_product_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Admin only.", show_alert=True)
        return

    await state.set_state(ProductStates.waiting_name)
    await callback.message.answer(
        "➕ <b>ADD PRODUCT</b>\n\nSend product name:",
        parse_mode="HTML"
    )
    await callback.answer()


@dp.message(ProductStates.waiting_name)
async def product_name_received(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await state.set_state(ProductStates.waiting_category)
    await message.answer(
        "📂 Send category exactly as one of:\n\n"
        "<code>Entertainment</code>\n"
        "<code>Coupons</code>\n"
        "<code>Digital Products</code>",
        parse_mode="HTML"
    )


@dp.message(ProductStates.waiting_category)
async def product_category_received(message: Message, state: FSMContext):
    category = message.text.strip()
    allowed = {"Entertainment", "Coupons", "Digital Products"}

    if category not in allowed:
        await message.answer("❌ Please use one of the listed categories.")
        return

    await state.update_data(category=category)
    await state.set_state(ProductStates.waiting_price)
    await message.answer("💰 Send product price (example: 129):")


@dp.message(ProductStates.waiting_price)
async def product_price_received(message: Message, state: FSMContext):
    try:
        price = float(message.text.strip())
        if price <= 0:
            raise ValueError
    except (ValueError, AttributeError):
        await message.answer("❌ Enter a valid positive price.")
        return

    await state.update_data(price=round(price, 2))
    await state.set_state(ProductStates.waiting_description)
    await message.answer(
        "📝 Send product description.\n"
        "Or send <code>-</code> for no description.",
        parse_mode="HTML"
    )


@dp.message(ProductStates.waiting_description)
async def product_description_received(message: Message, state: FSMContext):
    data = await state.get_data()
    description = message.text.strip()
    if description == "-":
        description = ""

    await state.update_data(description=description)
    await state.set_state(ProductStates.waiting_image)
    await message.answer(
        "🖼️ <b>PRODUCT IMAGE</b>\n\nSend a product image/photo.\n"
        "Or send <code>-</code> to skip it.", parse_mode="HTML"
    )


@dp.message(ProductStates.waiting_image, F.photo)
async def product_image_received(message: Message, state: FSMContext):
    data = await state.get_data()
    image_file_id = message.photo[-1].file_id
    if data.get("product_id") and not data.get("name"):
        db.execute("UPDATE products SET image_file_id=? WHERE id=?", (image_file_id, data["product_id"]))
        db.commit(); pid=data["product_id"]; await state.clear()
        await message.answer("✅ <b>PRODUCT IMAGE UPDATED</b>", reply_markup=admin_keyboard(), parse_mode="HTML")
        return
    db.execute("""INSERT INTO products(name, category, price, description, image_file_id, sale_price, created_at) VALUES (?, ?, ?, ?, ?, NULL, ?)""",               (data["name"], data["category"], data["price"], data["description"], image_file_id, now()))
    db.commit(); product_id=db.execute("SELECT last_insert_rowid()").fetchone()[0]
    await state.clear()
    await message.answer("✅ <b>PRODUCT ADDED</b>\n\n" f"🆔 ID: <code>{product_id}</code>\n" f"🛍️ {html.escape(data['name'])}\n💰 ₹{data['price']:.2f}\n🖼️ Image added.\n\nUse <b>ADD STOCK</b> to add inventory.", reply_markup=admin_keyboard(), parse_mode="HTML")


@dp.message(ProductStates.waiting_image)
async def product_image_skip(message: Message, state: FSMContext):
    if (message.text or "").strip() != "-":
        await message.answer("❌ Send a photo or use - to skip.")
        return
    data=await state.get_data()
    if data.get("product_id") and not data.get("name"):
        db.execute("UPDATE products SET image_file_id='' WHERE id=?", (data["product_id"],))
        db.commit(); await state.clear()
        await message.answer("✅ <b>PRODUCT IMAGE REMOVED</b>", reply_markup=admin_keyboard(), parse_mode="HTML")
        return
    db.execute("""INSERT INTO products(name, category, price, description, image_file_id, sale_price, created_at) VALUES (?, ?, ?, ?, '', NULL, ?)""",
               (data["name"], data["category"], data["price"], data["description"], now()))
    db.commit(); product_id=db.execute("SELECT last_insert_rowid()").fetchone()[0]
    await state.clear()
    await message.answer("✅ <b>PRODUCT ADDED</b>\n\n" f"🆔 ID: <code>{product_id}</code>\n" f"🛍️ {html.escape(data['name'])}\n💰 ₹{data['price']:.2f}\n\nUse <b>ADD STOCK</b> to add inventory.", reply_markup=admin_keyboard(), parse_mode="HTML")


# =========================================================
# PRODUCT EDITING
# =========================================================

async def show_admin_product(callback: CallbackQuery, product_id: int):
    callback.data=f"admin_product:{product_id}"
    await admin_product_manage(callback)


@dp.callback_query(F.data.startswith("pedit_name:"))
async def edit_product_name_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id): return await callback.answer("❌ Admin only.", show_alert=True)
    pid=int(callback.data.split(":",1)[1]); await state.update_data(product_id=pid); await state.set_state(ProductStates.waiting_edit_value)
    await state.update_data(edit_field="name")
    await callback.message.answer("✏️ Send the new product name:"); await callback.answer()

@dp.callback_query(F.data.startswith("pedit_desc:"))
async def edit_product_desc_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id): return await callback.answer("❌ Admin only.", show_alert=True)
    pid=int(callback.data.split(":",1)[1]); await state.update_data(product_id=pid, edit_field="description"); await state.set_state(ProductStates.waiting_edit_value)
    await callback.message.answer("📝 Send the new description, or - to clear it:"); await callback.answer()

@dp.callback_query(F.data.startswith("pedit_price:"))
async def edit_product_price_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id): return await callback.answer("❌ Admin only.", show_alert=True)
    pid=int(callback.data.split(":",1)[1]); await state.update_data(product_id=pid, edit_field="price"); await state.set_state(ProductStates.waiting_edit_value)
    await callback.message.answer("💰 Send the new regular price:"); await callback.answer()

@dp.callback_query(F.data.startswith("pedit_sale:"))
async def edit_product_sale_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id): return await callback.answer("❌ Admin only.", show_alert=True)
    pid=int(callback.data.split(":",1)[1]); await state.update_data(product_id=pid); await state.set_state(ProductStates.waiting_sale_price)
    await callback.message.answer("🏷️ Send sale price. Send <code>0</code> to remove discount.", parse_mode="HTML"); await callback.answer()

@dp.message(ProductStates.waiting_edit_value)
async def edit_product_value_received(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    data=await state.get_data(); field=data["edit_field"]; pid=data["product_id"]; value=(message.text or "").strip()
    if field=="name":
        if not value: return await message.answer("❌ Name cannot be empty.")
        db.execute("UPDATE products SET name=? WHERE id=?",(value,pid))
    elif field=="description":
        db.execute("UPDATE products SET description=? WHERE id=?",("" if value=="-" else value,pid))
    else:
        try: price=round(float(value),2)
        except: return await message.answer("❌ Enter a valid price.")
        if price<=0: return await message.answer("❌ Price must be greater than 0.")
        db.execute("UPDATE products SET price=? WHERE id=?",(price,pid))
    db.commit(); await state.clear(); await message.answer("✅ Product updated.", reply_markup=admin_keyboard(), parse_mode="HTML")

@dp.message(ProductStates.waiting_sale_price)
async def edit_product_sale_received(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    try: sale=round(float((message.text or "").strip()),2)
    except: return await message.answer("❌ Enter a valid sale price or 0.")
    data=await state.get_data(); pid=data["product_id"]; p=db.execute("SELECT price FROM products WHERE id=?",(pid,)).fetchone()
    if not p: await state.clear(); return await message.answer("❌ Product not found.")
    if sale==0: db.execute("UPDATE products SET sale_price=NULL WHERE id=?",(pid,))
    elif sale<=0 or sale>=p["price"]: return await message.answer(f"❌ Sale price must be between ₹0 and less than ₹{p['price']:.2f}.")
    else: db.execute("UPDATE products SET sale_price=? WHERE id=?",(sale,pid))
    db.commit(); await state.clear(); await message.answer("✅ Discount updated.", reply_markup=admin_keyboard())

@dp.callback_query(F.data.startswith("pedit_image:"))
async def edit_product_image_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id): return await callback.answer("❌ Admin only.", show_alert=True)
    pid=int(callback.data.split(":",1)[1]); await state.update_data(product_id=pid); await state.set_state(ProductStates.waiting_image)
    await callback.message.answer("🖼️ Send the new product image/photo."); await callback.answer()

# =========================================================
# ADMIN STOCK
# =========================================================

@dp.callback_query(F.data == "admin_stock")
async def admin_stock_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Admin only.", show_alert=True)
        return

    products = db.execute(
        "SELECT id, name FROM products WHERE active=1 ORDER BY id DESC"
    ).fetchall()

    if not products:
        await callback.answer("❌ Add a product first.", show_alert=True)
        return

    buttons = [
        [InlineKeyboardButton(
            text=f"#{p['id']} {p['name']}",
            callback_data=f"stock_product:{p['id']}",
            style="success"
        )]
        for p in products
    ]
    buttons.append([InlineKeyboardButton(text="⬅️ ADMIN", callback_data="admin_back", style="primary")])

    await callback.message.edit_text(
        "📦 <b>ADD STOCK</b>\n\nSelect product:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML"
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("pstock_add:"))
async def product_stock_add(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id): return await callback.answer("❌ Admin only.", show_alert=True)
    pid=int(callback.data.split(":",1)[1]); p=db.execute("SELECT * FROM products WHERE id=?",(pid,)).fetchone()
    if not p: return await callback.answer("❌ Product not found.", show_alert=True)
    await state.update_data(product_id=pid); await state.set_state(StockStates.waiting_items)
    await callback.message.answer(f"📦 <b>ADD STOCK: {html.escape(p['name'])}</b>\n\nSend one stock item per line.", parse_mode="HTML"); await callback.answer()

@dp.callback_query(F.data.startswith("pstock_remove:"))
async def product_stock_remove_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id): return await callback.answer("❌ Admin only.", show_alert=True)
    pid=int(callback.data.split(":",1)[1]); rows=db.execute("SELECT id,item FROM stock WHERE product_id=? AND sold=0 ORDER BY id LIMIT 50",(pid,)).fetchall()
    if not rows: return await callback.answer("❌ No available stock to remove.", show_alert=True)
    buttons=[[InlineKeyboardButton(text=f"🗑️ #{r['id']} • {r['item'][:35]}", callback_data=f"remove_stock:{r['id']}", style="danger")] for r in rows]
    buttons.append([InlineKeyboardButton(text="⬅️ PRODUCT", callback_data=f"admin_product:{pid}", style="primary")])
    await callback.message.edit_text("➖ <b>REMOVE STOCK</b>\n\nSelect an unsold stock item to remove:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML"); await callback.answer()

@dp.callback_query(F.data.startswith("remove_stock:"))
async def remove_stock_item(callback: CallbackQuery):
    if not is_admin(callback.from_user.id): return await callback.answer("❌ Admin only.", show_alert=True)
    sid=int(callback.data.split(":",1)[1]); row=db.execute("SELECT product_id,sold FROM stock WHERE id=?",(sid,)).fetchone()
    if not row: return await callback.answer("❌ Stock item not found.", show_alert=True)
    if row["sold"]: return await callback.answer("❌ Already sold; cannot remove.", show_alert=True)
    db.execute("DELETE FROM stock WHERE id=?",(sid,)); db.commit(); await callback.answer("🗑️ Stock removed.")
    await callback.message.edit_text("✅ <b>STOCK REMOVED</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ PRODUCT", callback_data=f"admin_product:{row['product_id']}", style="primary")]]), parse_mode="HTML")

@dp.callback_query(F.data.startswith("stock_product:"))
async def stock_product_selected(callback: CallbackQuery, state: FSMContext):
    product_id = int(callback.data.split(":")[1])
    p = db.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()

    if not p:
        await callback.answer("❌ Product not found.", show_alert=True)
        return

    await state.update_data(product_id=product_id)
    await state.set_state(StockStates.waiting_items)

    await callback.message.answer(
        f"📦 <b>STOCK FOR: {p['name']}</b>\n\n"
        "Send stock items, <b>one per line</b>.\n\n"
        "Example:\n"
        "<code>email1@example.com:password1\n"
        "email2@example.com:password2</code>",
        parse_mode="HTML"
    )
    await callback.answer()


@dp.message(StockStates.waiting_items)
async def stock_items_received(message: Message, state: FSMContext):
    data = await state.get_data()
    raw = message.text or ""

    items = [x.strip() for x in raw.splitlines() if x.strip()]
    if not items:
        await message.answer("❌ No stock items detected.")
        return

    for item in items:
        db.execute(
            "INSERT INTO stock(product_id, item) VALUES (?, ?)",
            (data["product_id"], item)
        )
    db.commit()
    await state.clear()

    await message.answer(
        f"✅ <b>{len(items)} STOCK ITEM(S) ADDED</b>",
        reply_markup=admin_keyboard(),
        parse_mode="HTML"
    )


# =========================================================
# ADMIN USERS / WALLET
# =========================================================

@dp.callback_query(F.data == "admin_users")
async def admin_users(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Admin only.", show_alert=True)
        return

    rows = db.execute("""
        SELECT * FROM users ORDER BY created_at DESC LIMIT 20
    """).fetchall()

    if not rows:
        text = "👥 <b>USERS</b>\n\nNo users yet."
    else:
        lines = ["👥 <b>RECENT USERS</b>\n"]
        for u in rows:
            uname = f"@{u['username']}" if u["username"] else "-"
            lines.append(
                f"🆔 <code>{u['user_id']}</code> • {u['first_name'] or '-'}\n"
                f"🔗 {uname} • 💰 ₹{u['balance']:.2f}\n"
            )
        text = "\n".join(lines)

    await callback.message.edit_text(
        text,
        reply_markup=admin_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()


@dp.callback_query(F.data == "admin_wallet")
async def admin_wallet_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Admin only.", show_alert=True)
        return

    await state.set_state(WalletStates.waiting_user_id)
    await callback.message.answer(
        "💰 <b>WALLET ADJUSTMENT</b>\n\n"
        "Send Telegram User ID:",
        parse_mode="HTML"
    )
    await callback.answer()


@dp.message(WalletStates.waiting_user_id)
async def wallet_user_id_received(message: Message, state: FSMContext):
    try:
        user_id = int(message.text.strip())
    except (ValueError, AttributeError):
        await message.answer("❌ Enter a numeric Telegram User ID.")
        return

    await state.update_data(user_id=user_id)
    await state.set_state(WalletStates.waiting_amount)

    await message.answer(
        "Send amount to add/subtract.\n\n"
        "Example:\n"
        "<code>500</code> = add ₹500\n"
        "<code>-100</code> = subtract ₹100",
        parse_mode="HTML"
    )


@dp.message(WalletStates.waiting_amount)
async def wallet_amount_received(message: Message, state: FSMContext):
    try:
        amount = round(float(message.text.strip()), 2)
    except (ValueError, AttributeError):
        await message.answer("❌ Enter a valid amount.")
        return

    if amount == 0 or abs(amount) > 1000000:
        await message.answer("❌ Amount must be non-zero and within ₹10,00,000.")
        return

    data = await state.get_data()
    user_id = data["user_id"]

    existing = db.execute(
        "SELECT user_id, balance FROM users WHERE user_id=?",
        (user_id,)
    ).fetchone()

    if not existing:
        await message.answer("❌ User not found in database.")
        await state.clear()
        return

    if existing["balance"] + amount < 0:
        await message.answer(
            f"❌ This adjustment would make the wallet negative. Current balance: ₹{existing['balance']:.2f}"
        )
        await state.clear()
        return

    db.execute("BEGIN IMMEDIATE")
    try:
        db.execute(
            "UPDATE users SET balance=balance+? WHERE user_id=? AND balance+? >= 0",
            (amount, user_id, amount)
        )
        if db.execute("SELECT changes()").fetchone()[0] != 1:
            db.rollback()
            await message.answer("❌ Wallet update failed safely. Please retry.")
            await state.clear()
            return

        db.execute("""
            INSERT INTO wallet_transactions
            (user_id, amount, type, description, created_at)
            VALUES (?, ?, 'ADMIN_ADJUSTMENT', ?, ?)
        """, (user_id, amount, "Admin wallet adjustment", now()))
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Admin wallet adjustment failed")
        await message.answer("⚠️ Wallet update failed. Nothing was changed.")
        await state.clear()
        return

    new_balance = get_balance(user_id)
    await state.clear()

    await message.answer(
        "✅ <b>WALLET UPDATED</b>\n\n"
        f"👤 User: <code>{user_id}</code>\n"
        f"💰 Adjustment: <b>₹{amount:.2f}</b>\n"
        f"💳 New Balance: <b>₹{new_balance:.2f}</b>",
        reply_markup=admin_keyboard(),
        parse_mode="HTML"
    )


# =========================================================
# BROADCAST
# =========================================================

@dp.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Admin only.", show_alert=True)
        return

    await state.set_state(BroadcastStates.waiting_message)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ CANCEL", callback_data="admin_broadcast_cancel", style="danger")]
    ])
    await callback.message.edit_text(
        "📢 <b>BROADCAST TO ALL USERS</b>\n\n"
        "Send the message you want to broadcast.\n\n"
        "✅ Text, photo, video, document and other Telegram messages are supported.\n"
        "📨 The bot will copy your message to all registered users.\n"
        "⏱️ Sending is rate-limited to reduce Telegram errors.\n\n"
        "<i>Only send legitimate store updates, offers and announcements.</i>",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()


@dp.callback_query(F.data == "admin_broadcast_cancel")
async def admin_broadcast_cancel(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Admin only.", show_alert=True)
        return

    await state.clear()
    await callback.message.edit_text(
        "🛠️ <b>APNASTORE ADMIN PANEL</b>\n\n"
        "Choose an option below.",
        reply_markup=admin_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer("Broadcast cancelled.")


@dp.message(BroadcastStates.waiting_message)
async def admin_broadcast_message(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return

    users = db.execute("SELECT user_id FROM users ORDER BY user_id ASC").fetchall()
    total = len(users)

    if total == 0:
        await state.clear()
        await message.answer(
            "📢 <b>BROADCAST</b>\n\n❌ No registered users found.",
            reply_markup=admin_keyboard(),
            parse_mode="HTML"
        )
        return

    await message.answer(
        f"📢 <b>BROADCAST STARTED</b>\n\n"
        f"👥 Recipients: <b>{total}</b>\n"
        "⏳ Please wait while messages are sent...",
        parse_mode="HTML"
    )

    sent = 0
    failed = 0

    for row in users:
        user_id = row["user_id"]
        try:
            await message.bot.copy_message(
                chat_id=user_id,
                from_chat_id=message.chat.id,
                message_id=message.message_id
            )
            sent += 1
        except Exception as error:
            failed += 1
            logger.warning("Broadcast failed for user %s: %s", user_id, error)

        # Stay comfortably below Telegram's broadcast rate limits.
        await asyncio.sleep(0.05)

    await state.clear()

    await message.answer(
        "✅ <b>BROADCAST COMPLETED</b>\n\n"
        f"👥 Total users: <b>{total}</b>\n"
        f"📨 Sent successfully: <b>{sent}</b>\n"
        f"⚠️ Failed: <b>{failed}</b>",
        reply_markup=admin_keyboard(),
        parse_mode="HTML"
    )


# =========================================================
# CUSTOMER ORDERS / OTHER
# =========================================================

@dp.callback_query(F.data == "legacy_orders")
async def legacy_orders_handler(callback: CallbackQuery):
    rows = db.execute("""
        SELECT o.*, p.name
        FROM orders o
        JOIN products p ON p.id=o.product_id
        WHERE o.user_id=?
        ORDER BY o.id DESC LIMIT 10
    """, (callback.from_user.id,)).fetchall()

    if not rows:
        text = (
            "📦 <b>MY ORDERS</b>  •  <i>PURCHASE HISTORY</i>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "🛍️ <b>No orders yet</b>\n\n"
            "Your completed purchases will appear here automatically.\n"
            "Ready to find your first deal? 🚀"
        )
    else:
        lines = ["📦 <b>MY ORDERS</b>  •  <i>PURCHASE HISTORY</i>\n", "✨ <i>Your latest purchases</i>\n━━━━━━━━━━━━━━━━━━━━\n"]
        for o in rows:
            lines.append(
                f"🆔 Order #{o['id']}\n"
                f"🛍️ {o['name']}\n"
                f"💰 ₹{o['amount']:.2f}\n"
                f"🕐 {o['created_at']}\n"
            )
        text = "\n".join(lines)

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏠 HOME", callback_data="home", style="primary")]
        ]),
        parse_mode="HTML"
    )
    await callback.answer()


@dp.callback_query(F.data == "deals")
async def deals_handler(callback: CallbackQuery):
    await callback.message.edit_text(
        "🔥 <b>TODAY'S DEALS</b>  •  <i>HOT OFFERS</i>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "🎯 Special prices, limited-time offers and exclusive bundles will appear here.\n\n"
        "💙 We keep this section fresh — check back regularly for the next deal.\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "⏳ <i>No active deals right now. Something good may be next!</i>",
        reply_markup=back_home_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()


@dp.callback_query(F.data == "legacy_refer")
async def legacy_refer_handler(callback: CallbackQuery):
    await callback.message.edit_text(
        "🎁 <b>REFER & EARN</b>  •  <i>REWARDS</i>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "👥 Invite your friends to ApnaStore and earn rewards when the referral program is active. 🚀\n\n"
        "💎 <b>Referral Rewards</b>\n"
        "🎉 <b>Special Bonuses</b>\n"
        "📊 <b>Easy Tracking</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "⏳ <i>Referral rewards are coming soon.</i>",
        reply_markup=back_home_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()


@dp.callback_query(F.data == "legacy_support")
async def legacy_support_handler(callback: CallbackQuery):
    await callback.message.edit_text(
        "💬 <b>APNASTORE SUPPORT</b>  •  <i>HELP CENTER</i>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "Need help with an order, payment or anything else? 🤝\n"
        "We're here to help you get it sorted.\n\n"
        "🆘 <b>Support:</b> @CR5PT\n\n"
        "📌 <b>For faster help</b>\n"
        "Please include your Order ID or relevant payment details when contacting support.\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "💙 <i>ApnaStore Support Team</i>",
        reply_markup=back_home_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()



# =========================================================
# FINAL ADMIN MENU
# =========================================================

def admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 DASHBOARD",callback_data="admin_dashboard",style="primary"),InlineKeyboardButton(text="📈 ANALYTICS",callback_data="admin_analytics",style="primary")],
        [InlineKeyboardButton(text="🛍️ PRODUCTS",callback_data="admin_products",style="success"),InlineKeyboardButton(text="📦 STOCK",callback_data="admin_stock",style="success")],
        [InlineKeyboardButton(text="💳 PAYMENTS",callback_data="admin_payments",style="primary"),InlineKeyboardButton(text="🧾 ORDERS",callback_data="admin_orders",style="primary")],
        [InlineKeyboardButton(text="👥 USERS",callback_data="admin_users",style="primary"),InlineKeyboardButton(text="💰 WALLET",callback_data="admin_wallet",style="success")],
        [InlineKeyboardButton(text="📢 BROADCAST",callback_data="admin_broadcast",style="success"),InlineKeyboardButton(text="🎟️ COUPONS",callback_data="admin_coupons",style="success")],
        [InlineKeyboardButton(text="🆘 SUPPORT TICKETS",callback_data="admin_tickets",style="primary")],
        [InlineKeyboardButton(text="🖼️ QR",callback_data="admin_qr",style="primary"),InlineKeyboardButton(text="💳 UPI",callback_data="admin_upi",style="primary")],
        [InlineKeyboardButton(text="👑 ADMINS",callback_data="admin_admins",style="primary"),InlineKeyboardButton(text="⚙️ SETTINGS",callback_data="admin_settings_plus",style="primary")],
    ])




# =========================================================
# CUSTOMER: ORDERS + DIGITAL LOCKER
# =========================================================

@dp.callback_query(F.data == "orders")
async def orders_handler(callback: CallbackQuery):
    rows=db.execute("SELECT o.*,p.name FROM orders o JOIN products p ON p.id=o.product_id WHERE o.user_id=? ORDER BY o.id DESC LIMIT 20",(callback.from_user.id,)).fetchall()
    buttons=[]
    lines=["📦 <b>MY ORDERS</b>\n━━━━━━━━━━━━━━━━━━━━\n"]
    if not rows:
        lines.append("🛍️ No orders yet. Start shopping to see your purchases here.")
    else:
        for o in rows:
            lines.append(f"🧾 <b>#{o['id']}</b> • {esc(o['name'])}\n💰 {money(o['amount'])} • 📌 {esc(o['status'])}\n")
            buttons.append([InlineKeyboardButton(text=f"🔐 ORDER #{o['id']}",callback_data=f"delivery:{o['id']}",style="primary")])
    buttons.append([InlineKeyboardButton(text="🏠 HOME",callback_data="home",style="primary")])
    await callback.message.edit_text("\n".join(lines),reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),parse_mode="HTML"); await callback.answer()

# =========================================================
# CUSTOMER: SEARCH / HOT / NEW / WISHLIST / REWARDS / APNAPASS
# =========================================================

def money(v):
    return f"₹{float(v):.2f}"

def esc(v):
    return html.escape(str(v or ""))

def effective_price(p):
    sale=p["sale_price"] if "sale_price" in p.keys() else None
    if sale is not None and float(sale)>0 and float(sale)<float(p["price"]):
        return float(sale)
    return float(p["price"])

def ensure_points(user_id):
    row=db.execute("SELECT * FROM loyalty_points WHERE user_id=?",(user_id,)).fetchone()
    if row: return row
    db.execute("INSERT INTO loyalty_points(user_id,points,lifetime_points,updated_at) VALUES (?,?,?,?)",(user_id,0,0,now()))
    db.commit()
    return db.execute("SELECT * FROM loyalty_points WHERE user_id=?",(user_id,)).fetchone()

def pass_level(points):
    return db.execute("SELECT * FROM pass_levels WHERE min_points<=? ORDER BY min_points DESC LIMIT 1",(points,)).fetchone()

def list_products(rows, back="shop"):
    buttons=[]
    for p in rows:
        available=int(p["available"])
        if available<=0: continue
        price=effective_price(p)
        buttons.append([InlineKeyboardButton(text=f"🛍️ {p['name']} • ₹{price:.0f} • {available} left",callback_data=f"product:{p['id']}",style="success")])
    buttons.append([InlineKeyboardButton(text="⬅️ BACK",callback_data=back,style="primary")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

@dp.callback_query(F.data == "search")
async def search_start(callback: CallbackQuery,state:FSMContext):
    await state.set_state(SearchStates.waiting_query)
    await callback.message.edit_text("🔎 <b>SEARCH PRODUCTS</b>\n\nType a product name, category or keyword:",reply_markup=back_home_keyboard(),parse_mode="HTML")
    await callback.answer()

@dp.message(SearchStates.waiting_query)
async def search_received(message: Message,state:FSMContext):
    q=(message.text or "").strip()
    if len(q)<2:
        await message.answer("❌ Enter at least 2 characters."); return
    rows=db.execute("""SELECT p.*,(SELECT COUNT(*) FROM stock s WHERE s.product_id=p.id AND s.sold=0) available FROM products p WHERE p.active=1 AND (LOWER(p.name) LIKE LOWER(?) OR LOWER(p.category) LIKE LOWER(?) OR LOWER(p.description) LIKE LOWER(?)) ORDER BY p.featured DESC,p.id DESC LIMIT 20""",(f"%{q}%",f"%{q}%",f"%{q}%")).fetchall()
    await state.clear()
    await message.answer("🔎 <b>SEARCH RESULTS</b>\n\n"+("No matching products found." if not rows else "Select a product:"),reply_markup=list_products(rows),parse_mode="HTML")

@dp.callback_query(F.data == "whats_hot")
async def whats_hot(callback: CallbackQuery):
    rows=db.execute("""SELECT p.*,(SELECT COUNT(*) FROM stock s WHERE s.product_id=p.id AND s.sold=0) available FROM products p WHERE p.active=1 ORDER BY p.featured DESC,p.id DESC LIMIT 15""").fetchall()
    await callback.message.edit_text("🔥 <b>WHAT'S HOT</b>\n\nTrending products, featured items and current deals:",reply_markup=list_products(rows),parse_mode="HTML"); await callback.answer()

@dp.callback_query(F.data == "new_arrivals")
async def new_arrivals(callback: CallbackQuery):
    rows=db.execute("""SELECT p.*,(SELECT COUNT(*) FROM stock s WHERE s.product_id=p.id AND s.sold=0) available FROM products p WHERE p.active=1 ORDER BY p.id DESC LIMIT 15""").fetchall()
    await callback.message.edit_text("🆕 <b>NEW ARRIVALS</b>\n\nFreshly added products:",reply_markup=list_products(rows),parse_mode="HTML"); await callback.answer()

@dp.callback_query(F.data == "wishlist")
async def wishlist_handler(callback: CallbackQuery):
    rows=db.execute("""SELECT p.*,(SELECT COUNT(*) FROM stock s WHERE s.product_id=p.id AND s.sold=0) available FROM wishlist w JOIN products p ON p.id=w.product_id WHERE w.user_id=? ORDER BY w.created_at DESC""",(callback.from_user.id,)).fetchall()
    buttons=[]
    for p in rows:
        buttons.append([InlineKeyboardButton(text=f"❤️ {p['name']} • ₹{effective_price(p):.0f}",callback_data=f"product:{p['id']}",style="primary")])
    buttons.append([InlineKeyboardButton(text="🏠 HOME",callback_data="home",style="primary")])
    await callback.message.edit_text("❤️ <b>MY SAVED PRODUCTS</b>\n\n"+("Your wishlist is empty." if not rows else "Select a saved product:"),reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),parse_mode="HTML"); await callback.answer()

@dp.callback_query(F.data.startswith("wishlist_add:"))
async def wishlist_add(callback: CallbackQuery):
    pid=int(callback.data.split(":",1)[1]); db.execute("INSERT OR IGNORE INTO wishlist(user_id,product_id,created_at) VALUES (?,?,?)",(callback.from_user.id,pid,now())); db.commit(); await callback.answer("❤️ Saved to wishlist!")

@dp.callback_query(F.data.startswith("wishlist_remove:"))
async def wishlist_remove(callback: CallbackQuery):
    pid=int(callback.data.split(":",1)[1]); db.execute("DELETE FROM wishlist WHERE user_id=? AND product_id=?",(callback.from_user.id,pid)); db.commit(); await callback.answer("Removed from wishlist."); await wishlist_handler(callback)

@dp.callback_query(F.data == "rewards")
async def rewards_handler(callback: CallbackQuery):
    lp=ensure_points(callback.from_user.id); lvl=pass_level(lp["lifetime_points"])
    count=db.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id=?",(callback.from_user.id,)).fetchone()[0]
    earned=db.execute("SELECT COALESCE(SUM(reward),0) FROM referrals WHERE referrer_id=?",(callback.from_user.id,)).fetchone()[0]
    await callback.message.edit_text(f"🎁 <b>MY REWARDS</b>\n━━━━━━━━━━━━━━━━━━━━\n\n⭐ Points: <b>{lp['points']}</b>\n🏆 ApnaPass: <b>{lvl['name'] if lvl else 'Basic'}</b>\n👥 Referrals: <b>{count}</b>\n💰 Referral earnings: <b>{money(earned)}</b>",reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏆 APNAPASS",callback_data="apnapass",style="primary")],[InlineKeyboardButton(text="🏠 HOME",callback_data="home",style="primary")]]),parse_mode="HTML"); await callback.answer()

@dp.callback_query(F.data == "apnapass")
async def apnapass_handler(callback: CallbackQuery):
    lp=ensure_points(callback.from_user.id); current=pass_level(lp["lifetime_points"]); levels=db.execute("SELECT * FROM pass_levels ORDER BY min_points ASC").fetchall(); lines=["🏆 <b>APNAPASS</b>\n","Your loyalty level unlocks better offers.\n"]
    for level in levels:
        mark="✅" if current and level['id']==current['id'] else "▫️"
        lines.append(f"{mark} <b>{level['name']}</b> — {level['min_points']} pts • {level['discount_percent']:.0f}% member discount")
    await callback.message.edit_text("\n".join(lines),reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🎁 REWARDS",callback_data="rewards",style="success")],[InlineKeyboardButton(text="🏠 HOME",callback_data="home",style="primary")]]),parse_mode="HTML"); await callback.answer()

@dp.callback_query(F.data == "notifications")
async def notifications_handler(callback: CallbackQuery):
    rows=db.execute("SELECT * FROM notifications WHERE user_id=? ORDER BY id DESC LIMIT 20",(callback.from_user.id,)).fetchall(); lines=["🔔 <b>NOTIFICATIONS</b>\n"]
    if not rows: lines.append("You're all caught up. ✅")
    for n in rows: lines.append(f"{'🔵' if not n['is_read'] else '⚪'} <b>{esc(n['title'])}</b>\n{esc(n['body'])}\n")
    db.execute("UPDATE notifications SET is_read=1 WHERE user_id=?",(callback.from_user.id,)); db.commit(); await callback.message.edit_text("\n".join(lines),reply_markup=back_home_keyboard(),parse_mode="HTML"); await callback.answer()

@dp.callback_query(F.data == "my_reviews")
async def my_reviews(callback: CallbackQuery):
    rows=db.execute("SELECT r.*,p.name FROM reviews r JOIN products p ON p.id=r.product_id WHERE r.user_id=? ORDER BY r.id DESC LIMIT 15",(callback.from_user.id,)).fetchall(); lines=["⭐ <b>MY REVIEWS</b>\n"]
    if not rows: lines.append("No reviews submitted yet.")
    for r in rows: lines.append(f"⭐ {r['rating']}/5 • <b>{esc(r['name'])}</b>\n{esc(r['comment'])}\n")
    await callback.message.edit_text("\n".join(lines),reply_markup=back_home_keyboard(),parse_mode="HTML"); await callback.answer()

# =========================================================
# CUSTOMER: PROFESSIONAL HELP CENTER
# =========================================================

@dp.callback_query(F.data == "support")
async def support_handler_final(callback: CallbackQuery):
    from urllib.parse import quote
    templates={
        "order":"Hello ApnaStore Support Team,\n\nI need assistance regarding my order/delivery.\n\nOrder ID: ______\nUser ID: {uid}\n\nPlease review my order and assist me.\n\nThank you,\nApnaStore Customer",
        "payment":"Hello ApnaStore Support Team,\n\nI’m facing an issue with my wallet recharge.\n\nRequest ID: ______\nUTR / Transaction ID: ______\nUser ID: {uid}\n\nKindly review my payment and assist me.\n\nThank you,\nApnaStore Customer",
        "wallet":"Hello ApnaStore Support Team,\n\nI need help with my wallet balance or transaction.\n\nUser ID: {uid}\nTransaction ID: ______\n\nPlease review and assist me.\n\nThank you,\nApnaStore Customer",
        "product":"Hello ApnaStore Support Team,\n\nI’m facing an issue with a purchased product.\n\nProduct: ______\nOrder ID: ______\nUser ID: {uid}\n\nPlease review my order and assist me.\n\nThank you,\nApnaStore Customer",
        "coupon":"Hello ApnaStore Support Team,\n\nI’m facing an issue while applying a coupon.\n\nCoupon Code: ______\nUser ID: {uid}\n\nKindly check and assist me.\n\nThank you,\nApnaStore Customer",
        "referral":"Hello ApnaStore Support Team,\n\nI’m facing an issue regarding my referral or rewards.\n\nUser ID: {uid}\n\nKindly review my referral activity and assist me.\n\nThank you,\nApnaStore Customer",
        "verification":"Hello ApnaStore Support Team,\n\nI’m unable to complete ApnaStore membership verification.\n\nUser ID: {uid}\n\nKindly assist me with the verification process.\n\nThank you,\nApnaStore Customer",
        "account":"Hello ApnaStore Support Team,\n\nI need assistance with my ApnaStore account.\n\nUser ID: {uid}\n\nKindly review my account and assist me.\n\nThank you,\nApnaStore Customer",
    }
    def link(key): return "https://t.me/CR5PT?text="+quote(templates[key].format(uid=callback.from_user.id))
    kb=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 ORDER / DELIVERY",url=link("order"),style="primary")],
        [InlineKeyboardButton(text="💳 PAYMENT / RECHARGE",url=link("payment"),style="success")],
        [InlineKeyboardButton(text="💰 WALLET / BALANCE",url=link("wallet"),style="success")],
        [InlineKeyboardButton(text="🛍️ PRODUCT PROBLEM",url=link("product"),style="primary")],
        [InlineKeyboardButton(text="🎟️ COUPON PROBLEM",url=link("coupon"),style="primary")],
        [InlineKeyboardButton(text="🎁 REFERRAL / REWARDS",url=link("referral"),style="success")],
        [InlineKeyboardButton(text="🔐 VERIFICATION",url=link("verification"),style="primary")],
        [InlineKeyboardButton(text="👤 ACCOUNT PROBLEM",url=link("account"),style="primary")],
        [InlineKeyboardButton(text="🏠 HOME",callback_data="home",style="primary")]
    ])
    await callback.message.edit_text("🆘 <b>APNASTORE HELP CENTER</b>\n━━━━━━━━━━━━━━━━━━━━\n\nChoose your issue. A professional ready-to-send message will open for @CR5PT.",reply_markup=kb,parse_mode="HTML"); await callback.answer()

# =========================================================
# CUSTOMER: ACCOUNT
# =========================================================

@dp.callback_query(F.data == "account")
async def account_handler_final(callback: CallbackQuery):
    ensure_user(callback.from_user); lp=ensure_points(callback.from_user.id); lvl=pass_level(lp['lifetime_points']); orders=db.execute("SELECT COUNT(*) FROM orders WHERE user_id=?",(callback.from_user.id,)).fetchone()[0]; saved=db.execute("SELECT COUNT(*) FROM wishlist WHERE user_id=?",(callback.from_user.id,)).fetchone()[0]
    await callback.message.edit_text(f"👤 <b>MY ACCOUNT</b>\n━━━━━━━━━━━━━━━━━━━━\n\n🆔 User ID: <code>{callback.from_user.id}</code>\n💰 Wallet: <b>{money(get_balance(callback.from_user.id))}</b>\n📦 Orders: <b>{orders}</b>\n❤️ Saved: <b>{saved}</b>\n⭐ Points: <b>{lp['points']}</b>\n🏆 ApnaPass: <b>{lvl['name'] if lvl else 'Basic'}</b>",reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔔 NOTIFICATION SETTINGS",callback_data="notif_settings",style="primary")],[InlineKeyboardButton(text="🏠 HOME",callback_data="home",style="primary")]]),parse_mode="HTML"); await callback.answer()

@dp.callback_query(F.data == "notif_settings")
async def notif_settings(callback: CallbackQuery):
    row=db.execute("SELECT notification_enabled FROM users WHERE user_id=?",(callback.from_user.id,)).fetchone(); on=bool(row and row['notification_enabled'])
    await callback.message.edit_text(f"🔔 <b>NOTIFICATIONS</b>\n\nStatus: <b>{'ON' if on else 'OFF'}</b>",reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔄 TOGGLE",callback_data="notif_toggle",style="primary")],[InlineKeyboardButton(text="⬅️ ACCOUNT",callback_data="account",style="primary")]]),parse_mode="HTML"); await callback.answer()

@dp.callback_query(F.data == "notif_toggle")
async def notif_toggle(callback: CallbackQuery):
    row=db.execute("SELECT notification_enabled FROM users WHERE user_id=?",(callback.from_user.id,)).fetchone(); val=0 if row and row['notification_enabled'] else 1; db.execute("UPDATE users SET notification_enabled=? WHERE user_id=?",(val,callback.from_user.id)); db.commit(); await callback.answer("Notifications updated"); await notif_settings(callback)

# =========================================================
# CUSTOMER: CHECKOUT + COUPONS + DELIVERY LOCKER + REVIEWS
# =========================================================

@dp.callback_query(F.data.startswith("checkout:"))
async def checkout_handler(callback: CallbackQuery):
    pid=int(callback.data.split(":",1)[1]); p=db.execute("SELECT p.*,(SELECT COUNT(*) FROM stock s WHERE s.product_id=p.id AND s.sold=0) available FROM products p WHERE p.id=? AND p.active=1",(pid,)).fetchone()
    if not p or int(p['available'])<=0: return await callback.answer("❌ Out of stock.",show_alert=True)
    price=effective_price(p); await callback.message.edit_text(f"🛒 <b>CHECKOUT</b>\n━━━━━━━━━━━━━━━━━━━━\n\n🛍️ <b>{esc(p['name'])}</b>\n💰 Price: <b>{money(price)}</b>\n💳 Wallet: <b>{money(get_balance(callback.from_user.id))}</b>\n📦 Stock: <b>{p['available']}</b>",reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🎟️ APPLY COUPON",callback_data=f"coupon_apply:{pid}",style="primary")],[InlineKeyboardButton(text="✅ CONFIRM PURCHASE",callback_data=f"confirm_buy:{pid}",style="success")],[InlineKeyboardButton(text="❤️ SAVE",callback_data=f"wishlist_add:{pid}",style="primary")],[InlineKeyboardButton(text="⬅️ BACK",callback_data=f"product:{pid}",style="primary")]]),parse_mode="HTML"); await callback.answer()

@dp.callback_query(F.data.startswith("coupon_apply:"))
async def coupon_apply_start(callback: CallbackQuery,state:FSMContext):
    await state.set_state(CouponApplyStates.waiting_code); await state.update_data(product_id=int(callback.data.split(":",1)[1])); await callback.message.answer("🎟️ <b>APPLY COUPON</b>\n\nSend coupon code:",parse_mode="HTML"); await callback.answer()

@dp.message(CouponApplyStates.waiting_code)
async def coupon_apply_received(message: Message,state:FSMContext):
    code=(message.text or '').strip().upper(); c=db.execute("SELECT * FROM coupons WHERE code=? AND active=1",(code,)).fetchone(); data=await state.get_data()
    if not c: await message.answer("❌ Invalid or inactive coupon."); return
    if c['max_uses'] and c['used_count']>=c['max_uses']: await message.answer("❌ Coupon usage limit reached."); await state.clear(); return
    if db.execute("SELECT 1 FROM coupon_uses WHERE coupon_id=? AND user_id=?",(c['id'],message.from_user.id)).fetchone(): await message.answer("⚠️ You have already used this coupon."); await state.clear(); return
    p=db.execute("SELECT * FROM products WHERE id=?",(data['product_id'],)).fetchone(); price=effective_price(p)
    if price < c['min_order']: await message.answer(f"❌ Minimum order is {money(c['min_order'])}."); await state.clear(); return
    saved=min(price*(c['value']/100) if c['kind']=='percent' else c['value'],price); final=price-saved
    set_setting(f"pending_coupon:{message.from_user.id}",f"{code}|{data['product_id']}|{saved:.2f}|{final:.2f}"); await state.clear()
    await message.answer(f"✅ <b>COUPON APPLIED</b>\n\n🎟️ <code>{esc(code)}</code>\n💰 Original: <s>{money(price)}</s>\n🏷️ Saved: <b>{money(saved)}</b>\n✅ Final: <b>{money(final)}</b>",reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ CONFIRM PURCHASE",callback_data=f"confirm_buy:{data['product_id']}",style="success")],[InlineKeyboardButton(text="🏠 HOME",callback_data="home",style="primary")]]),parse_mode="HTML")

async def purchase_core(bot,user_id,pid):
    p=db.execute("SELECT p.*,(SELECT COUNT(*) FROM stock s WHERE s.product_id=p.id AND s.sold=0) available FROM products p WHERE p.id=? AND p.active=1",(pid,)).fetchone()
    if not p or int(p['available'])<=0: return None,"❌ Out of stock."
    base=effective_price(p); final=base; saved=0.0; coupon=None
    pending=get_setting(f"pending_coupon:{user_id}")
    if pending:
        try:
            code,spid,ss,sf=pending.split('|',3)
            if int(spid)==pid: coupon=code; saved=float(ss); final=float(sf)
        except Exception: pass
    if get_balance(user_id)<final: return None,f"❌ Insufficient balance. Need {money(final)}."
    db.execute("BEGIN IMMEDIATE")
    try:
        stock=db.execute("SELECT * FROM stock WHERE product_id=? AND sold=0 ORDER BY id LIMIT 1",(pid,)).fetchone()
        if not stock: db.rollback(); return None,"❌ Stock just sold out."
        if db.execute("UPDATE users SET balance=balance-? WHERE user_id=? AND balance>=?",(final,user_id,final)).rowcount!=1: db.rollback(); return None,"❌ Insufficient balance."
        if db.execute("UPDATE stock SET sold=1,sold_to=?,sold_at=? WHERE id=? AND sold=0",(user_id,now(),stock['id'])).rowcount!=1: db.rollback(); return None,"❌ Stock changed. Try again."
        db.execute("INSERT INTO orders(user_id,product_id,stock_id,amount,item,created_at) VALUES (?,?,?,?,?,?)",(user_id,pid,stock['id'],final,stock['item'],now())); order_id=db.execute("SELECT last_insert_rowid() id").fetchone()['id']
        db.execute("INSERT INTO wallet_transactions(user_id,amount,type,description,created_at) VALUES (?,?,?,?,?)",(user_id,-final,'PURCHASE',f"Purchase: {p['name']}",now()))
        points=max(1,int(final//10)); ensure_points(user_id); db.execute("UPDATE loyalty_points SET points=points+?,lifetime_points=lifetime_points+?,updated_at=? WHERE user_id=?",(points,points,now(),user_id))
        if coupon:
            c=db.execute("SELECT id FROM coupons WHERE code=?",(coupon,)).fetchone()
            if c:
                db.execute("UPDATE coupons SET used_count=used_count+1 WHERE id=?",(c['id'],)); db.execute("INSERT OR IGNORE INTO coupon_uses(coupon_id,user_id,order_id,amount_saved,created_at) VALUES (?,?,?,?,?)",(c['id'],user_id,order_id,saved,now()))
            db.execute("DELETE FROM settings WHERE key=?",(f"pending_coupon:{user_id}",))
        db.commit()
    except Exception:
        db.rollback(); logger.exception('purchase_core failed'); return None,"⚠️ Purchase failed. Try again."
    return (order_id,p,final,saved,stock['item']),None

@dp.callback_query(F.data.startswith("confirm_buy:"))
async def confirm_buy_handler(callback: CallbackQuery):
    pid=int(callback.data.split(":",1)[1]); result,error=await purchase_core(callback.bot,callback.from_user.id,pid)
    if error: return await callback.answer(error,show_alert=True)
    oid,p,final,saved,item=result; await callback.message.edit_text(f"🎉 <b>PURCHASE SUCCESSFUL</b>\n━━━━━━━━━━━━━━━━━━━━\n\n🧾 Order: <code>#{oid}</code>\n🛍️ <b>{esc(p['name'])}</b>\n💰 Paid: <b>{money(final)}</b>\n🏷️ Saved: <b>{money(saved)}</b>\n💳 Balance: <b>{money(get_balance(callback.from_user.id))}</b>\n\n🔐 <b>DIGITAL LOCKER</b>\n<code>{esc(item)}</code>",reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📦 VIEW DELIVERY",callback_data=f"delivery:{oid}",style="success")],[InlineKeyboardButton(text="🏠 HOME",callback_data="home",style="primary")]]),parse_mode="HTML"); await callback.answer("✅ Purchase successful!")

@dp.callback_query(F.data.startswith("delivery:"))
async def delivery_handler(callback: CallbackQuery):
    oid=int(callback.data.split(":",1)[1]); o=db.execute("SELECT o.*,p.name FROM orders o JOIN products p ON p.id=o.product_id WHERE o.id=? AND o.user_id=?",(oid,callback.from_user.id)).fetchone()
    if not o: return await callback.answer("❌ Order not found.",show_alert=True)
    await callback.message.edit_text(f"🔐 <b>DIGITAL LOCKER</b>\n━━━━━━━━━━━━━━━━━━━━\n\n🧾 Order: <code>#{oid}</code>\n🛍️ {esc(o['name'])}\n💰 {money(o['amount'])}\n📦 <code>{esc(o['item'])}</code>",reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⭐ WRITE REVIEW",callback_data=f"review:{oid}",style="primary")],[InlineKeyboardButton(text="🆘 REPORT ISSUE",url="https://t.me/CR5PT",style="danger")],[InlineKeyboardButton(text="⬅️ ORDERS",callback_data="orders",style="primary")]]),parse_mode="HTML"); await callback.answer()

@dp.callback_query(F.data.startswith("review:"))
async def review_start(callback: CallbackQuery,state:FSMContext):
    oid=int(callback.data.split(":",1)[1]); o=db.execute("SELECT * FROM orders WHERE id=? AND user_id=?",(oid,callback.from_user.id)).fetchone()
    if not o: return await callback.answer("❌ Order not found.",show_alert=True)
    if db.execute("SELECT 1 FROM reviews WHERE order_id=?",(oid,)).fetchone(): return await callback.answer("⚠️ Already reviewed.",show_alert=True)
    await state.update_data(order_id=oid,product_id=o['product_id']); await state.set_state(ReviewStates.waiting_rating); await callback.message.answer("⭐ <b>RATE YOUR ORDER</b>\n\nSend a rating from 1 to 5:",parse_mode="HTML"); await callback.answer()

@dp.message(ReviewStates.waiting_rating)
async def review_rating_received(message: Message,state:FSMContext):
    try: rating=int((message.text or '').strip())
    except ValueError: rating=0
    if rating<1 or rating>5: await message.answer("❌ Send a number from 1 to 5."); return
    await state.update_data(rating=rating); await state.set_state(ReviewStates.waiting_comment); await message.answer("📝 Send your review, or type <code>skip</code>.",parse_mode="HTML")

@dp.message(ReviewStates.waiting_comment)
async def review_comment_received(message: Message,state:FSMContext):
    d=await state.get_data(); comment=(message.text or '').strip(); comment='' if comment.lower()=='skip' else comment; db.execute("INSERT INTO reviews(product_id,user_id,order_id,rating,comment,created_at) VALUES (?,?,?,?,?,?)",(d['product_id'],message.from_user.id,d['order_id'],d['rating'],comment,now())); db.commit(); await state.clear(); await message.answer("✅ <b>REVIEW SUBMITTED</b>",reply_markup=home_button(),parse_mode="HTML")

# =========================================================
# CUSTOMER: ORDERS UPGRADE
# =========================================================

@dp.callback_query(F.data == "orders_plus")
async def orders_plus(callback: CallbackQuery):
    await orders_handler(callback)

# =========================================================
# ADMIN: ANALYTICS / COUPONS / TICKETS / SETTINGS PLUS
# =========================================================

@dp.callback_query(F.data == "admin_analytics")
async def admin_analytics_final(callback: CallbackQuery):
    if not is_admin(callback.from_user.id): return await callback.answer("❌ Admin only.",show_alert=True)
    sales=db.execute("SELECT COALESCE(SUM(amount),0) FROM orders").fetchone()[0]; recharge=db.execute("SELECT COALESCE(SUM(amount),0) FROM recharge_requests WHERE status='approved'").fetchone()[0]; orders=db.execute("SELECT COUNT(*) FROM orders").fetchone()[0]; users=db.execute("SELECT COUNT(*) FROM users").fetchone()[0]; stock=db.execute("SELECT COUNT(*) FROM stock WHERE sold=0").fetchone()[0]
    await callback.message.edit_text(f"📈 <b>SALES ANALYTICS</b>\n━━━━━━━━━━━━━━━━━━━━\n\n💰 Sales: <b>{money(sales)}</b>\n💳 Approved Recharge: <b>{money(recharge)}</b>\n🧾 Orders: <b>{orders}</b>\n👥 Users: <b>{users}</b>\n📦 Available Stock: <b>{stock}</b>",reply_markup=admin_back_keyboard(),parse_mode="HTML"); await callback.answer()

@dp.callback_query(F.data == "admin_tickets")
async def admin_tickets_final(callback: CallbackQuery):
    if not is_admin(callback.from_user.id): return await callback.answer("❌ Admin only.",show_alert=True)
    rows=db.execute("SELECT * FROM support_tickets WHERE status!='closed' ORDER BY id DESC LIMIT 30").fetchall(); lines=["🆘 <b>SUPPORT TICKETS</b>\n"]; buttons=[]
    if not rows: lines.append("No open tickets.")
    for t in rows:
        lines.append(f"🎫 <b>#{t['id']}</b> • {esc(t['category'])}\n👤 <code>{t['user_id']}</code>\n{esc(t['subject'])}\n")
        buttons.append([InlineKeyboardButton(text=f"👁️ VIEW #{t['id']}",callback_data=f"ticket:{t['id']}",style="primary")])
    buttons.append([InlineKeyboardButton(text="⬅️ ADMIN",callback_data="admin_back",style="primary")]); await callback.message.edit_text("\n".join(lines),reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),parse_mode="HTML"); await callback.answer()

@dp.callback_query(F.data.startswith("ticket:"))
async def ticket_view_final(callback: CallbackQuery):
    if not is_admin(callback.from_user.id): return await callback.answer("❌ Admin only.",show_alert=True)
    tid=int(callback.data.split(":",1)[1]); t=db.execute("SELECT * FROM support_tickets WHERE id=?",(tid,)).fetchone();
    if not t: return await callback.answer("❌ Ticket not found.",show_alert=True)
    msgs=db.execute("SELECT * FROM support_messages WHERE ticket_id=? ORDER BY id ASC",(tid,)).fetchall(); lines=[f"🎫 <b>TICKET #{tid}</b>",f"👤 User: <code>{t['user_id']}</code>",f"📂 {esc(t['category'])}",f"📌 {esc(t['subject'])}",f"📝 {esc(t['message'])}","","<b>Conversation</b>"]
    for m in msgs: lines.append(f"• <code>{m['sender_id']}</code>: {esc(m['message'])}")
    await callback.message.edit_text("\n".join(lines),reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ CLOSE TICKET",callback_data=f"close_ticket:{tid}",style="danger")],[InlineKeyboardButton(text="⬅️ TICKETS",callback_data="admin_tickets",style="primary")]]),parse_mode="HTML"); await callback.answer()

@dp.callback_query(F.data.startswith("close_ticket:"))
async def close_ticket_final(callback: CallbackQuery):
    if not is_admin(callback.from_user.id): return await callback.answer("❌ Admin only.",show_alert=True)
    tid=int(callback.data.split(":",1)[1]); row=db.execute("SELECT user_id FROM support_tickets WHERE id=?",(tid,)).fetchone(); db.execute("UPDATE support_tickets SET status='closed',updated_at=? WHERE id=?",(now(),tid)); db.commit()
    if row:
        try: await callback.bot.send_message(row['user_id'],f"✅ <b>SUPPORT TICKET #{tid} CLOSED</b>\n\nYour issue has been marked resolved.",parse_mode="HTML")
        except Exception: pass
    await callback.answer("✅ Ticket closed"); await admin_tickets_final(callback)

@dp.callback_query(F.data == "admin_coupons")
async def admin_coupons_final(callback: CallbackQuery):
    if not is_admin(callback.from_user.id): return await callback.answer("❌ Admin only.",show_alert=True)
    rows=db.execute("SELECT * FROM coupons ORDER BY id DESC LIMIT 30").fetchall(); lines=["🎟️ <b>COUPON MANAGER</b>\n"]; buttons=[]
    if not rows: lines.append("No coupons yet.")
    for c in rows:
        value=f"{c['value']:.0f}% OFF" if c['kind']=='percent' else f"₹{c['value']:.0f} OFF"; state="🟢" if c['active'] else "🔴"; lines.append(f"{state} <code>{esc(c['code'])}</code> • {value} • Used {c['used_count']}/{c['max_uses'] or '∞'}")
    buttons.append([InlineKeyboardButton(text="➕ ADD COUPON",callback_data="coupon_add",style="success")]); buttons.append([InlineKeyboardButton(text="⬅️ ADMIN",callback_data="admin_back",style="primary")]); await callback.message.edit_text("\n".join(lines),reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),parse_mode="HTML"); await callback.answer()

@dp.callback_query(F.data == "coupon_add")
async def coupon_add_start(callback: CallbackQuery,state:FSMContext):
    if not is_admin(callback.from_user.id): return await callback.answer("❌ Admin only.",show_alert=True)
    await state.set_state(CouponCreateStates.waiting_code); await callback.message.answer("🎟️ <b>CREATE COUPON</b>\n\nSend code, e.g. <code>SAVE20</code>.",parse_mode="HTML"); await callback.answer()

@dp.message(CouponCreateStates.waiting_code)
async def coupon_code_step(message: Message,state:FSMContext):
    code=(message.text or '').strip().upper()
    if not re.fullmatch(r'[A-Z0-9_-]{3,30}',code): await message.answer("❌ Invalid code."); return
    if db.execute("SELECT 1 FROM coupons WHERE code=?",(code,)).fetchone(): await message.answer("❌ Coupon exists."); return
    await state.update_data(code=code); await state.set_state(CouponCreateStates.waiting_kind); await message.answer("Send <code>percent</code> or <code>flat</code>.",parse_mode="HTML")

@dp.message(CouponCreateStates.waiting_kind)
async def coupon_kind_step(message: Message,state:FSMContext):
    kind=(message.text or '').strip().lower()
    if kind not in ('percent','flat'): await message.answer("❌ Type percent or flat."); return
    await state.update_data(kind=kind); await state.set_state(CouponCreateStates.waiting_value); await message.answer("Send discount value, e.g. <code>20</code>.",parse_mode="HTML")

@dp.message(CouponCreateStates.waiting_value)
async def coupon_value_step(message: Message,state:FSMContext):
    try: value=float((message.text or '').strip())
    except ValueError: await message.answer("❌ Invalid value."); return
    d=await state.get_data()
    if value<=0 or (d['kind']=='percent' and value>100): await message.answer("❌ Invalid discount."); return
    await state.update_data(value=value); await state.set_state(CouponCreateStates.waiting_min_order); await message.answer("Minimum order? Send <code>0</code> for none.",parse_mode="HTML")

@dp.message(CouponCreateStates.waiting_min_order)
async def coupon_min_step(message: Message,state:FSMContext):
    try: minimum=max(0,float((message.text or '').strip()))
    except ValueError: await message.answer("❌ Invalid amount."); return
    await state.update_data(minimum=minimum); await state.set_state(CouponCreateStates.waiting_max_uses); await message.answer("Maximum total uses? Send <code>0</code> for unlimited.",parse_mode="HTML")

@dp.message(CouponCreateStates.waiting_max_uses)
async def coupon_max_step(message: Message,state:FSMContext):
    try: max_uses=int((message.text or '').strip())
    except ValueError: await message.answer("❌ Invalid number."); return
    if max_uses<0: await message.answer("❌ Use 0 or a positive number."); return
    d=await state.get_data(); db.execute("INSERT INTO coupons(code,kind,value,max_uses,min_order,active,created_at) VALUES (?,?,?,?,?,1,?)",(d['code'],d['kind'],d['value'],max_uses,d['minimum'],now())); db.commit(); await state.clear(); await message.answer(f"✅ <b>COUPON CREATED</b>\n\n🎟️ <code>{esc(d['code'])}</code>",reply_markup=admin_keyboard(),parse_mode="HTML")

@dp.callback_query(F.data == "admin_settings_plus")
async def admin_settings_plus(callback: CallbackQuery):
    if not is_admin(callback.from_user.id): return await callback.answer("❌ Admin only.",show_alert=True)
    await callback.message.edit_text(f"⚙️ <b>STORE SETTINGS</b>\n\n💳 UPI: <code>{esc(get_setting('upi_id') or '')}</code>\n💬 Support: @CR5PT\n🎁 Referral Reward: <b>{money(float(get_setting('referral_reward') or 10))}</b>\n🛠️ Maintenance: <b>{'ON' if get_setting('maintenance')=='1' else 'OFF'}</b>",reply_markup=admin_back_keyboard(),parse_mode="HTML"); await callback.answer()

# =========================================================
# ID COMMAND
# =========================================================

@dp.message(Command("id"))
async def get_chat_id(message: Message):
    await message.answer(
        f"🆔 <b>Chat ID:</b>\n\n<code>{message.chat.id}</code>",
        parse_mode="HTML"
    )


# =========================================================
# START BOT
# =========================================================

async def health_handler(request: web.Request):
    return web.Response(text="ApnaStore Bot is running")


async def start_health_server():
    """Small HTTP server for Koyeb/Web Service health checks."""
    app = web.Application()
    app.router.add_get("/", health_handler)
    app.router.add_get("/health", health_handler)

    runner = web.AppRunner(app)
    await runner.setup()

    # Koyeb provides PORT automatically for Web Services.
    port = int(os.getenv("PORT", "8000"))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    logger.info("Health server listening on 0.0.0.0:%s", port)
    return runner


async def main():
    init_db()

    if not BOT_TOKEN:
        print("❌ BOT_TOKEN not found in environment variables")
        return

    bot = Bot(token=BOT_TOKEN)

    logger.info("ApnaStore Bot is running")
    logger.info("UPI configured")
    logger.info("Admin configured")

    health_runner = await start_health_server()

    try:
        # Run Telegram polling and the HTTP health endpoint together.
        await dp.start_polling(bot)
    finally:
        await health_runner.cleanup()
        await bot.session.close()
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
