import os
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

CHANNEL_USERNAME = "@cpmpremium"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("💎 PREMIUM — 500 ⭐", callback_data="premium")],
        [InlineKeyboardButton("⭐ PREMIUM RESOURCES — 200 ⭐", callback_data="resources")],
        [InlineKeyboardButton("❤️ SUPPORT", callback_data="support")],
    ]

    text = (
        "👋 WELCOME TO PREMIUM CPM SHOP 🏎️\n\n"
        "Choose the product you want to purchase:\n\n"
        "💎 Premium Account — 500 ⭐\n"
        "⭐ Premium Resources — 200 ⭐\n"
        "❤️ Support\n\n"
        "⚡ Fast Delivery\n"
        "🔐 Secure Payment\n"
        "🌍 Worldwide Service"
    )

    await update.message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "premium":
        await query.message.reply_text(
            "💎 PREMIUM ACCOUNT\n\n"
            "Price: 500 ⭐\n\n"
            "📦 Available accounts: 0\n\n"
            "The account will be delivered automatically after payment."
        )

    elif query.data == "resources":
        await query.message.reply_text(
            "⭐ PREMIUM RESOURCES\n\n"
            "Price: 200 ⭐\n\n"
            "📦 Available: 0\n\n"
            "The resources will be delivered after payment."
        )

    elif query.data == "support":
        await query.message.reply_text(
            "❤️ SUPPORT\n\n"
            "Need help with your order?\n"
            "Contact our support:\n\n"
            "👤 @OTTOCPM"
        )


async def owner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ You are not authorized.")
        return

    await update.message.reply_text(
        "👑 Owner access confirmed."
    )


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is not set.")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("owner", owner))
    app.add_handler(CallbackQueryHandler(button_handler))

    print("Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
