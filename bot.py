import os
import json

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

PREMIUM1_LOGIN = os.getenv("PREMIUM1_LOGIN")
PREMIUM1_PASSWORD = os.getenv("PREMIUM1_PASSWORD")

PREMIUM_PRICE = 500
RESOURCES_PRICE = 200

STOCK_FILE = "stock.json"


def load_stock():
    if not os.path.exists(STOCK_FILE):
        return {"premium1_sold": False}

    try:
        with open(STOCK_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {"premium1_sold": False}


def save_stock(stock):
    with open(STOCK_FILE, "w") as f:
        json.dump(stock, f)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton(
            "💎 PREMIUM — 500 ⭐",
            callback_data="premium"
        )],
        [InlineKeyboardButton(
            "⭐ PREMIUM RESOURCES — 200 ⭐",
            callback_data="resources"
        )],
        [InlineKeyboardButton(
            "❤️ SUPPORT",
            callback_data="support"
        )],
    ]

    await update.message.reply_text(
        "👋 WELCOME TO PREMIUM CPM SHOP 🏎️\n\n"
        "Choose the product you want to purchase:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    stock = load_stock()

    if query.data == "premium":

        if stock["premium1_sold"]:
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
            "📦 Available: 1\n\n"
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

        if stock["premium1_sold"]:
            await query.message.reply_text(
                "❌ This account has already been sold."
            )
            return

        if not PREMIUM1_LOGIN or not PREMIUM1_PASSWORD:
            await query.message.reply_text(
                "❌ Product is temporarily unavailable."
            )
            return

        await context.bot.send_invoice(
            chat_id=query.from_user.id,
            title="💎 Premium CPM Account",
            description="Premium CPM Account",
            payload="premium_1",
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
    stock = load_stock()

    if query.invoice_payload != "premium_1":
        await query.answer(ok=False)
        return

    if stock["premium1_sold"]:
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

    if payment.invoice_payload != "premium_1":
        return

    stock = load_stock()

    if stock["premium1_sold"]:
        await update.message.reply_text(
            "⚠️ This account is already marked as sold. "
            "Please contact support."
        )
        return

    login = PREMIUM1_LOGIN
    password = PREMIUM1_PASSWORD

    # Mark account as sold BEFORE sending the credentials.
    stock["premium1_sold"] = True
    save_stock(stock)

    await update.message.reply_text(
        "✅ PAYMENT SUCCESSFUL!\n\n"
        "💎 PREMIUM ACCOUNT\n\n"
        f"👤 Login: `{login}`\n"
        f"🔐 Password: `{password}`\n\n"
        "❤️ Thank you for your purchase!",
        parse_mode="Markdown",
    )


async def owner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text(
            "❌ You are not authorized."
        )
        return

    stock = load_stock()

    status = "❌ SOLD" if stock["premium1_sold"] else "🟢 AVAILABLE"

    await update.message.reply_text(
        f"👑 OWNER PANEL\n\n"
        f"💎 Premium #1: {status}"
    )


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is not set.")

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
