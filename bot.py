import os
import psycopg
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Update,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    PreCheckoutQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
DATABASE_URL = os.getenv("DATABASE_URL")

PREMIUM1_LOGIN = os.getenv("PREMIUM1_LOGIN")
PREMIUM1_PASSWORD = os.getenv("PREMIUM1_PASSWORD")

PREMIUM_PRICE = 500
RESOURCES_PRICE = 200


# =========================
# DATABASE
# =========================

def get_connection():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set.")
    return psycopg.connect(DATABASE_URL)


def init_database():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS premium_accounts (
                    id SERIAL PRIMARY KEY,
                    login TEXT NOT NULL,
                    password TEXT NOT NULL,
                    sold BOOLEAN NOT NULL DEFAULT FALSE,
                    sold_to BIGINT,
                    sold_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cur.execute("""
                SELECT COUNT(*)
                FROM premium_accounts
            """)

            count = cur.fetchone()[0]

            if count == 0 and PREMIUM1_LOGIN and PREMIUM1_PASSWORD:
                cur.execute(
                    """
                    INSERT INTO premium_accounts
                    (login, password)
                    VALUES (%s, %s)
                    """,
                    (PREMIUM1_LOGIN, PREMIUM1_PASSWORD),
                )

        conn.commit()


def get_available_account():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, login, password
                FROM premium_accounts
                WHERE sold = FALSE
                ORDER BY id
                LIMIT 1
            """)
            return cur.fetchone()


def get_account_by_id(account_id):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, login, password, sold
                FROM premium_accounts
                WHERE id = %s
            """, (account_id,))
            return cur.fetchone()


def mark_account_sold(account_id, user_id):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE premium_accounts
                SET sold = TRUE,
                    sold_to = %s,
                    sold_at = CURRENT_TIMESTAMP
                WHERE id = %s
                  AND sold = FALSE
                RETURNING login, password
            """, (user_id, account_id))

            result = cur.fetchone()
            conn.commit()
            return result


def get_stock_count():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*)
                FROM premium_accounts
                WHERE sold = FALSE
            """)
            return cur.fetchone()[0]


def get_sold_count():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*)
                FROM premium_accounts
                WHERE sold = TRUE
            """)
            return cur.fetchone()[0]


def get_total_count():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*)
                FROM premium_accounts
            """)
            return cur.fetchone()[0]


def get_stock_accounts():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, login
                FROM premium_accounts
                WHERE sold = FALSE
                ORDER BY id
            """)
            return cur.fetchall()


def get_recent_sales():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, login, sold_to, sold_at
                FROM premium_accounts
                WHERE sold = TRUE
                ORDER BY sold_at DESC
                LIMIT 10
            """)
            return cur.fetchall()


def add_account(login, password):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO premium_accounts
                (login, password)
                VALUES (%s, %s)
                RETURNING id
            """, (login, password))

            account_id = cur.fetchone()[0]

        conn.commit()
        return account_id


def delete_account(account_id):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                DELETE FROM premium_accounts
                WHERE id = %s
                  AND sold = FALSE
                RETURNING id
            """, (account_id,))

            result = cur.fetchone()

        conn.commit()
        return result


# =========================
# OWNER
# =========================

def is_owner(update):
    return (
        update.effective_user
        and update.effective_user.id == OWNER_ID
    )


def owner_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "➕ ADD ACCOUNT",
                callback_data="owner_add"
            )
        ],
        [
            InlineKeyboardButton(
                "📦 STOCK",
                callback_data="owner_stock"
            ),
            InlineKeyboardButton(
                "📊 STATISTICS",
                callback_data="owner_stats"
            )
        ],
        [
            InlineKeyboardButton(
                "📈 SALES",
                callback_data="owner_sales"
            )
        ],
        [
            InlineKeyboardButton(
                "🗑️ DELETE ACCOUNT",
                callback_data="owner_delete"
            )
        ],
        [
            InlineKeyboardButton(
                "🔄 REFRESH",
                callback_data="owner_refresh"
            )
        ],
    ])


async def owner(update, context):
    if not is_owner(update):
        await update.message.reply_text(
            "❌ You are not authorized."
        )
        return

    await update.message.reply_text(
        "👑 OWNER PANEL\n\n"
        f"📦 Stock: {get_stock_count()}\n"
        f"✅ Sold: {get_sold_count()}\n"
        f"📊 Total: {get_total_count()}",
        reply_markup=owner_keyboard(),
    )


async def owner_panel_callback(update, context):
    query = update.callback_query
    await query.answer()

    if not is_owner(update):
        return

    data = query.data

    if data == "owner_refresh":
        await query.edit_message_text(
            "👑 OWNER PANEL\n\n"
            f"📦 Stock: {get_stock_count()}\n"
            f"✅ Sold: {get_sold_count()}\n"
            f"📊 Total: {get_total_count()}",
            reply_markup=owner_keyboard(),
        )

    elif data == "owner_stock":
        accounts = get_stock_accounts()

        if not accounts:
            await query.message.reply_text(
                "📦 STOCK\n\n❌ Stock is empty."
            )
            return

        text = "📦 STOCK\n\n"

        for account_id, login in accounts:
            text += f"🟢 #{account_id} — `{login}`\n"

        await query.message.reply_text(
            text,
            parse_mode="Markdown"
        )

    elif data == "owner_stats":
        stock = get_stock_count()
        sold = get_sold_count()
        total = get_total_count()

        percentage = 0

        if total:
            percentage = round(
                (sold / total) * 100,
                1
            )

        await query.message.reply_text(
            "📊 STATISTICS\n\n"
            f"📦 Available: {stock}\n"
            f"✅ Sold: {sold}\n"
            f"📊 Total: {total}\n"
            f"📈 Sold percentage: {percentage}%"
        )

    elif data == "owner_sales":
        sales = get_recent_sales()

        if not sales:
            await query.message.reply_text(
                "📈 SALES\n\nNo sales yet."
            )
            return

        text = "📈 LAST 10 SALES\n\n"

        for account_id, login, sold_to, sold_at in sales:
            text += (
                f"💎 #{account_id}\n"
                f"👤 Login: `{login}`\n"
                f"🆔 User: `{sold_to}`\n"
                f"🕐 {sold_at}\n\n"
            )

        await query.message.reply_text(
            text,
            parse_mode="Markdown"
        )

    elif data == "owner_add":
        context.user_data.clear()
        context.user_data["adding_account"] = True
        context.user_data["add_step"] = "login"

        await query.message.reply_text(
            "➕ ADD PREMIUM ACCOUNT\n\n"
            "👤 Send the account LOGIN:"
        )

    elif data == "owner_delete":
        accounts = get_stock_accounts()

        if not accounts:
            await query.message.reply_text(
                "🗑️ DELETE ACCOUNT\n\n"
                "❌ Stock is empty."
            )
            return

        text = (
            "🗑️ DELETE ACCOUNT\n\n"
            "Send the ID of the account you want to delete.\n\n"
        )

        for account_id, login in accounts:
            text += f"#{account_id} — `{login}`\n"

        context.user_data.clear()
        context.user_data["deleting_account"] = True

        await query.message.reply_text(
            text,
            parse_mode="Markdown"
        )


# =========================
# OWNER TEXT INPUT
# =========================

async def owner_text_handler(update, context):
    if not is_owner(update):
        return

    text = update.message.text.strip()

    if context.user_data.get("adding_account"):

        step = context.user_data.get("add_step")

        if step == "login":
            context.user_data["new_login"] = text
            context.user_data["add_step"] = "password"

            await update.message.reply_text(
                "🔐 Send the account PASSWORD:"
            )
            return

        if step == "password":
            login = context.user_data["new_login"]
            password = text

            account_id = add_account(
                login,
                password
            )

            context.user_data.clear()

            await update.message.reply_text(
                "✅ ACCOUNT ADDED!\n\n"
                f"🆔 ID: #{account_id}\n"
                f"👤 Login: `{login}`\n"
                f"📦 Current stock: {get_stock_count()}",
                parse_mode="Markdown"
            )
            return

    if context.user_data.get("deleting_account"):

        try:
            account_id = int(text)
        except ValueError:
            await update.message.reply_text(
                "❌ Invalid ID. Send a number."
            )
            return

        result = delete_account(account_id)
        context.user_data.clear()

        if result is None:
            await update.message.reply_text(
                "❌ Account not found or already sold."
            )
            return

        await update.message.reply_text(
            f"🗑️ Account #{account_id} deleted successfully.\n\n"
            f"📦 Current stock: {get_stock_count()}"
        )


# =========================
# USER MENU
# =========================

async def start(update, context):

    keyboard = [
        [
            InlineKeyboardButton(
                "💎 PREMIUM — 500 ⭐",
                callback_data="premium"
            )
        ],
        [
            InlineKeyboardButton(
                "⭐ PREMIUM RESOURCES — 200 ⭐",
                callback_data="resources"
            )
        ],
        [
            InlineKeyboardButton(
                "❤️ SUPPORT",
                callback_data="support"
            )
        ],
    ]

    await update.message.reply_text(
        "👋 WELCOME TO PREMIUM CPM SHOP 🏎️\n\n"
        "Choose the product you want to purchase:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def button_handler(update, context):

    query = update.callback_query
    await query.answer()

    if query.data == "premium":

        stock = get_stock_count()

        if stock <= 0:
            await query.message.reply_text(
                "❌ PREMIUM ACCOUNT\n\n"
                "📦 Currently out of stock."
            )
            return

        await query.message.reply_text(
            "💎 PREMIUM ACCOUNT\n\n"
            "Price: 500 ⭐\n\n"
            f"📦 Available: {stock}\n\n"
            "Press the button below to purchase.",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "💳 BUY FOR 500 ⭐",
                        callback_data="buy_premium"
                    )
                ]
            ]),
        )

    elif query.data == "resources":

        await query.message.reply_text(
            "⭐ PREMIUM RESOURCES\n\n"
            "Price: 200 ⭐\n\n"
            "📦 Available: 0"
        )

    elif query.data == "support":

        await query.message.reply_text(
            "❤️ SUPPORT\n\n"
            "Need help with your order?\n\n"
            "👤 @OTTOCPM"
        )

    elif query.data == "buy_premium":

        account = get_available_account()

        if account is None:
            await query.message.reply_text(
                "❌ This product is currently out of stock."
            )
            return

        await context.bot.send_invoice(
            chat_id=query.from_user.id,
            title="💎 Premium CPM Account",
            description="Premium CPM Account",
            payload=f"premium_{account[0]}",
            currency="XTR",
            prices=[
                LabeledPrice(
                    "Premium Account",
                    PREMIUM_PRICE
                )
            ],
        )


# =========================
# PAYMENT
# =========================

async def precheckout_callback(update, context):

    query = update.pre_checkout_query

    if not query.invoice_payload.startswith("premium_"):
        await query.answer(ok=False)
        return

    try:
        account_id = int(
            query.invoice_payload.split("_")[1]
        )
    except (IndexError, ValueError):
        await query.answer(
            ok=False,
            error_message="Invalid account."
        )
        return

    account = get_account_by_id(account_id)

    if account is None or account[3]:
        await query.answer(
            ok=False,
            error_message="This account is no longer available."
        )
        return

    await query.answer(ok=True)


async def successful_payment(update, context):

    payment = update.message.successful_payment

    if not payment.invoice_payload.startswith("premium_"):
        return

    try:
        account_id = int(
            payment.invoice_payload.split("_")[1]
        )
    except (IndexError, ValueError):

        await update.message.reply_text(
            "⚠️ Payment received, but order ID is invalid.\n"
            "Please contact support."
        )
        return

    result = mark_account_sold(
        account_id,
        update.effective_user.id
    )

    if result is None:

        await update.message.reply_text(
            "⚠️ Payment received, but this account "
            "was already sold.\n\n"
            "Please contact support."
        )
        return

    login, password = result

    await update.message.reply_text(
        "✅ PAYMENT SUCCESSFUL!\n\n"
        "💎 PREMIUM ACCOUNT\n\n"
        f"👤 Login: `{login}`\n"
        f"🔐 Password: `{password}`\n\n"
        "❤️ Thank you for your purchase!",
        parse_mode="Markdown",
    )


# =========================
# MAIN
# =========================

def main():

    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is not set.")

    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set.")

    init_database()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(
        CommandHandler("start", start)
    )

    app.add_handler(
        CommandHandler("owner", owner)
    )

    app.add_handler(
        CallbackQueryHandler(
            owner_panel_callback,
            pattern=r"^owner_"
        )
    )

    app.add_handler(
        CallbackQueryHandler(button_handler)
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            owner_text_handler
        )
    )

    app.add_handler(
        PreCheckoutQueryHandler(
            precheckout_callback
        )
    )

    app.add_handler(
        MessageHandler(
            filters.SUCCESSFUL_PAYMENT,
            successful_payment
        )
    )

    print("Bot is running...")

    app.run_polling()


if __name__ == "__main__":
    main()
