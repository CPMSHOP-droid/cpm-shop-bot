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
                    sold_at TIMESTAMP
                )
            """)

            cur.execute("""
                SELECT id
                FROM premium_accounts
                LIMIT 1
            """)

            if cur.fetchone() is None:
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


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
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


async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
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

        keyboard = [[
            InlineKeyboardButton(
                "💳 BUY FOR 500 ⭐",
                callback_data="buy_premium"
            )
        ]]

        await query.message.reply_text(
            "💎 PREMIUM ACCOUNT\n\n"
            "Price: 500 ⭐\n\n"
            f"📦 Available: {stock}\n\n"
            "Press the button below to purchase.",
            reply_markup=InlineKeyboardMarkup(keyboard),
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


async def precheckout_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.pre_checkout_query

    if not query.invoice_payload.startswith("premium_"):
        await query.answer(ok=False)
        return

    account = get_available_account()

    if account is None:
        await query.answer(
            ok=False,
            error_message="This account has already been sold."
        )
        return

    await query.answer(ok=True)


async def successful_payment(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    payment = update.message.successful_payment

    if not payment.invoice_payload.startswith("premium_"):
        return

    try:
        account_id = int(
            payment.invoice_payload.split("_")[1]
        )
    except (IndexError, ValueError):
        await update.message.reply_text(
            "⚠️ Payment received, but order ID is invalid. "
            "Please contact support."
        )
        return

    result = mark_account_sold(
        account_id,
        update.effective_user.id
    )

    if result is None:
        await update.message.reply_text(
            "⚠️ Payment received, but this account was "
            "already sold. Please contact support."
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


async def owner(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text(
            "❌ You are not authorized."
        )
        return

    stock = get_stock_count()

    await update.message.reply_text(
        "👑 OWNER PANEL\n\n"
        f"💎 Premium accounts available: {stock}"
    )


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is not set.")

    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set.")

    init_database()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("owner", owner))

    app.add_handler(
        CallbackQueryHandler(button_handler)
    )

    app.add_handler(
        PreCheckoutQueryHandler(precheckout_callback)
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
