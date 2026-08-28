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


# =========================================================
# SETTINGS
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
DATABASE_URL = os.getenv("DATABASE_URL")

PREMIUM1_LOGIN = os.getenv("PREMIUM1_LOGIN")
PREMIUM1_PASSWORD = os.getenv("PREMIUM1_PASSWORD")

PREMIUM_PRICE = 500
RESOURCES_PRICE = 200
SUPPORT_PRICE = 10


# =========================================================
# DATABASE
# =========================================================

def get_connection():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set.")

    return psycopg.connect(DATABASE_URL)


def init_database():

    with get_connection() as conn:

        with conn.cursor() as cur:

            # Existing table is preserved.
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

            # Add product type if it doesn't exist.
            cur.execute("""
                ALTER TABLE premium_accounts
                ADD COLUMN IF NOT EXISTS product_type TEXT
                DEFAULT 'premium'
            """)

            # Existing accounts remain Premium accounts.
            cur.execute("""
                UPDATE premium_accounts
                SET product_type = 'premium'
                WHERE product_type IS NULL
            """)

            # Add the first account only if the database is empty.
            cur.execute("""
                SELECT COUNT(*)
                FROM premium_accounts
            """)

            count = cur.fetchone()[0]

            if (
                count == 0
                and PREMIUM1_LOGIN
                and PREMIUM1_PASSWORD
            ):

                cur.execute(
                    """
                    INSERT INTO premium_accounts
                    (
                        login,
                        password,
                        product_type
                    )
                    VALUES (%s, %s, 'premium')
                    """,
                    (
                        PREMIUM1_LOGIN,
                        PREMIUM1_PASSWORD,
                    ),
                )

        conn.commit()


# =========================================================
# ACCOUNT FUNCTIONS
# =========================================================

def get_available_account(product_type):

    with get_connection() as conn:

        with conn.cursor() as cur:

            cur.execute("""
                SELECT
                    id,
                    login,
                    password
                FROM premium_accounts
                WHERE
                    sold = FALSE
                    AND product_type = %s
                ORDER BY id
                LIMIT 1
            """, (product_type,))

            return cur.fetchone()


def get_account_by_id(account_id):

    with get_connection() as conn:

        with conn.cursor() as cur:

            cur.execute("""
                SELECT
                    id,
                    login,
                    password,
                    sold,
                    product_type
                FROM premium_accounts
                WHERE id = %s
            """, (account_id,))

            return cur.fetchone()


def mark_account_sold(account_id, user_id):

    with get_connection() as conn:

        with conn.cursor() as cur:

            cur.execute("""
                UPDATE premium_accounts

                SET
                    sold = TRUE,
                    sold_to = %s,
                    sold_at = CURRENT_TIMESTAMP

                WHERE
                    id = %s
                    AND sold = FALSE

                RETURNING
                    login,
                    password,
                    product_type
            """, (
                user_id,
                account_id,
            ))

            result = cur.fetchone()

        conn.commit()

        return result


def get_stock_count(product_type):

    with get_connection() as conn:

        with conn.cursor() as cur:

            cur.execute("""
                SELECT COUNT(*)
                FROM premium_accounts
                WHERE
                    sold = FALSE
                    AND product_type = %s
            """, (product_type,))

            return cur.fetchone()[0]


def get_sold_count(product_type=None):

    with get_connection() as conn:

        with conn.cursor() as cur:

            if product_type:

                cur.execute("""
                    SELECT COUNT(*)
                    FROM premium_accounts
                    WHERE
                        sold = TRUE
                        AND product_type = %s
                """, (product_type,))

            else:

                cur.execute("""
                    SELECT COUNT(*)
                    FROM premium_accounts
                    WHERE sold = TRUE
                """)

            return cur.fetchone()[0]


def get_total_count(product_type=None):

    with get_connection() as conn:

        with conn.cursor() as cur:

            if product_type:

                cur.execute("""
                    SELECT COUNT(*)
                    FROM premium_accounts
                    WHERE product_type = %s
                """, (product_type,))

            else:

                cur.execute("""
                    SELECT COUNT(*)
                    FROM premium_accounts
                """)

            return cur.fetchone()[0]


def get_stock_accounts(product_type):

    with get_connection() as conn:

        with conn.cursor() as cur:

            cur.execute("""
                SELECT
                    id,
                    login
                FROM premium_accounts
                WHERE
                    sold = FALSE
                    AND product_type = %s
                ORDER BY id
            """, (product_type,))

            return cur.fetchall()


def get_recent_sales():

    with get_connection() as conn:

        with conn.cursor() as cur:

            cur.execute("""
                SELECT
                    id,
                    login,
                    sold_to,
                    sold_at,
                    product_type
                FROM premium_accounts
                WHERE sold = TRUE
                ORDER BY sold_at DESC
                LIMIT 10
            """)

            return cur.fetchall()


def add_account(login, password, product_type):

    with get_connection() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                INSERT INTO premium_accounts
                (
                    login,
                    password,
                    product_type
                )
                VALUES (%s, %s, %s)
                RETURNING id
                """,
                (
                    login,
                    password,
                    product_type,
                ),
            )

            account_id = cur.fetchone()[0]

        conn.commit()

        return account_id


def delete_account(account_id):

    with get_connection() as conn:

        with conn.cursor() as cur:

            cur.execute("""
                DELETE FROM premium_accounts

                WHERE
                    id = %s
                    AND sold = FALSE

                RETURNING id
            """, (account_id,))

            result = cur.fetchone()

        conn.commit()

        return result


# =========================================================
# OWNER SECURITY
# =========================================================

def is_owner(update):

    return (
        update.effective_user
        and update.effective_user.id == OWNER_ID
    )


# =========================================================
# OWNER KEYBOARD
# =========================================================

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


# =========================================================
# OWNER PANEL
# =========================================================

async def owner(update, context):

    if not is_owner(update):

        await update.message.reply_text(
            "❌ You are not authorized."
        )

        return

    premium_stock = get_stock_count("premium")
    resources_stock = get_stock_count("resources")

    premium_sold = get_sold_count("premium")
    resources_sold = get_sold_count("resources")

    total_sold = premium_sold + resources_sold

    await update.message.reply_text(

        "👑 OWNER PANEL\n\n"

        "💎 PREMIUM ACCOUNT\n"
        f"📦 Stock: {premium_stock}\n"
        f"✅ Sold: {premium_sold}\n\n"

        "⭐ PREMIUM RESOURCES\n"
        f"📦 Stock: {resources_stock}\n"
        f"✅ Sold: {resources_sold}\n\n"

        f"📊 TOTAL SOLD: {total_sold}",

        reply_markup=owner_keyboard(),

    )


# =========================================================
# OWNER BUTTONS
# =========================================================

async def owner_panel_callback(update, context):

    query = update.callback_query

    await query.answer()

    if not is_owner(update):
        return

    data = query.data


    # -----------------------------------------------------
    # REFRESH
    # -----------------------------------------------------

    if data == "owner_refresh":

        premium_stock = get_stock_count("premium")
        resources_stock = get_stock_count("resources")

        premium_sold = get_sold_count("premium")
        resources_sold = get_sold_count("resources")

        total_sold = premium_sold + resources_sold

        await query.edit_message_text(

            "👑 OWNER PANEL\n\n"

            "💎 PREMIUM ACCOUNT\n"
            f"📦 Stock: {premium_stock}\n"
            f"✅ Sold: {premium_sold}\n\n"

            "⭐ PREMIUM RESOURCES\n"
            f"📦 Stock: {resources_stock}\n"
            f"✅ Sold: {resources_sold}\n\n"

            f"📊 TOTAL SOLD: {total_sold}",

            reply_markup=owner_keyboard(),

        )


    # -----------------------------------------------------
    # STOCK
    # -----------------------------------------------------

    elif data == "owner_stock":

        premium = get_stock_accounts("premium")
        resources = get_stock_accounts("resources")

        text = "📦 STOCK\n\n"

        text += "💎 PREMIUM ACCOUNT\n"

        if premium:

            for account_id, login in premium:

                text += (
                    f"🟢 #{account_id} — `{login}`\n"
                )

        else:

            text += "❌ Empty\n"


        text += "\n⭐ PREMIUM RESOURCES\n"

        if resources:

            for account_id, login in resources:

                text += (
                    f"🟢 #{account_id} — `{login}`\n"
                )

        else:

            text += "❌ Empty\n"


        await query.message.reply_text(
            text,
            parse_mode="Markdown"
        )


    # -----------------------------------------------------
    # STATISTICS
    # -----------------------------------------------------

    elif data == "owner_stats":

        premium_stock = get_stock_count("premium")
        resources_stock = get_stock_count("resources")

        premium_sold = get_sold_count("premium")
        resources_sold = get_sold_count("resources")

        premium_total = get_total_count("premium")
        resources_total = get_total_count("resources")

        total = premium_total + resources_total
        sold = premium_sold + resources_sold

        percentage = 0

        if total:

            percentage = round(
                (sold / total) * 100,
                1
            )

        await query.message.reply_text(

            "📊 STATISTICS\n\n"

            "💎 PREMIUM ACCOUNT\n"
            f"📦 Available: {premium_stock}\n"
            f"✅ Sold: {premium_sold}\n"
            f"📊 Total: {premium_total}\n\n"

            "⭐ PREMIUM RESOURCES\n"
            f"📦 Available: {resources_stock}\n"
            f"✅ Sold: {resources_sold}\n"
            f"📊 Total: {resources_total}\n\n"

            f"📈 Total sold: {sold}\n"
            f"📊 Total accounts: {total}\n"
            f"📈 Sold percentage: {percentage}%"

        )


    # -----------------------------------------------------
    # SALES
    # -----------------------------------------------------

    elif data == "owner_sales":

        sales = get_recent_sales()

        if not sales:

            await query.message.reply_text(

                "📈 SALES\n\n"
                "No sales yet."

            )

            return

        text = "📈 LAST 10 SALES\n\n"

        for (
            account_id,
            login,
            sold_to,
            sold_at,
            product_type
        ) in sales:

            if product_type == "premium":
                product_name = "💎 Premium Account"
            else:
                product_name = "⭐ Premium Resources"

            text += (

                f"{product_name}\n"

                f"🆔 #{account_id}\n"

                f"👤 Login: `{login}`\n"

                f"🆔 User: `{sold_to}`\n"

                f"🕐 {sold_at}\n\n"

            )

        await query.message.reply_text(
            text,
            parse_mode="Markdown"
        )


    # -----------------------------------------------------
    # ADD ACCOUNT
    # -----------------------------------------------------

    elif data == "owner_add":

        context.user_data.clear()

        context.user_data[
            "adding_account"
        ] = True

        context.user_data[
            "add_step"
        ] = "product"

        await query.message.reply_text(

            "➕ ADD ACCOUNT\n\n"

            "Choose account type:",

            reply_markup=InlineKeyboardMarkup([

                [

                    InlineKeyboardButton(
                        "💎 PREMIUM — 500 ⭐",
                        callback_data="add_product_premium"
                    )

                ],

                [

                    InlineKeyboardButton(
                        "⭐ RESOURCES — 200 ⭐",
                        callback_data="add_product_resources"
                    )

                ],

            ])

        )


    # -----------------------------------------------------
    # DELETE ACCOUNT
    # -----------------------------------------------------

    elif data == "owner_delete":

        premium = get_stock_accounts("premium")
        resources = get_stock_accounts("resources")

        if not premium and not resources:

            await query.message.reply_text(

                "🗑️ DELETE ACCOUNT\n\n"
                "❌ Stock is empty."

            )

            return

        text = (

            "🗑️ DELETE ACCOUNT\n\n"
            "Send the ID of the account to delete.\n\n"

        )

        if premium:

            text += "💎 PREMIUM\n"

            for account_id, login in premium:

                text += (
                    f"#{account_id} — `{login}`\n"
                )

            text += "\n"


        if resources:

            text += "⭐ RESOURCES\n"

            for account_id, login in resources:

                text += (
                    f"#{account_id} — `{login}`\n"
                )


        context.user_data.clear()

        context.user_data[
            "deleting_account"
        ] = True

        await query.message.reply_text(

            text,

            parse_mode="Markdown"

        )


# =========================================================
# OWNER PRODUCT SELECTION
# =========================================================

async def owner_product_callback(
    update,
    context
):

    query = update.callback_query

    await query.answer()

    if not is_owner(update):
        return

    if not context.user_data.get(
        "adding_account"
    ):
        return

    if query.data == "add_product_premium":

        context.user_data[
            "new_product"
        ] = "premium"

    elif query.data == "add_product_resources":

        context.user_data[
            "new_product"
        ] = "resources"

    else:
        return

    context.user_data[
        "add_step"
    ] = "login"

    await query.message.reply_text(

        "👤 Send the account LOGIN:"

    )


# =========================================================
# OWNER TEXT INPUT
# =========================================================

async def owner_text_handler(
    update,
    context
):

    if not is_owner(update):
        return

    text = update.message.text.strip()


    # -----------------------------------------------------
    # ADD ACCOUNT
    # -----------------------------------------------------

    if context.user_data.get(
        "adding_account"
    ):

        step = context.user_data.get(
            "add_step"
        )


        if step == "login":

            context.user_data[
                "new_login"
            ] = text

            context.user_data[
                "add_step"
            ] = "password"

            await update.message.reply_text(

                "🔐 Send the account PASSWORD:"

            )

            return


        if step == "password":

            login = context.user_data[
                "new_login"
            ]

            password = text

            product = context.user_data[
                "new_product"
            ]

            account_id = add_account(
                login,
                password,
                product
            )

            context.user_data.clear()

            if product == "premium":

                product_name = "💎 Premium Account"

            else:

                product_name = "⭐ Premium Resources"


            await update.message.reply_text(

                "✅ ACCOUNT ADDED!\n\n"

                f"{product_name}\n"

                f"🆔 ID: #{account_id}\n"

                f"👤 Login: `{login}`\n"

                f"📦 Current stock: "
                f"{get_stock_count(product)}",

                parse_mode="Markdown"

            )

            return


    # -----------------------------------------------------
    # DELETE ACCOUNT
    # -----------------------------------------------------

    if context.user_data.get(
        "deleting_account"
    ):

        try:

            account_id = int(text)

        except ValueError:

            await update.message.reply_text(

                "❌ Invalid ID.\n"
                "Send a number."

            )

            return


        result = delete_account(
            account_id
        )

        context.user_data.clear()


        if result is None:

            await update.message.reply_text(

                "❌ Account not found "
                "or already sold."

            )

            return


        await update.message.reply_text(

            f"🗑️ Account #{account_id} "
            "deleted successfully."

        )


# =========================================================
# START
# =========================================================

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
                "❤️ SUPPORT — 10 ⭐",
                callback_data="support"
            )

        ],

    ]

    await update.message.reply_text(

        "👋 WELCOME TO PREMIUM CPM SHOP 🏎️\n\n"

        "Choose the product you want to purchase:",

        reply_markup=InlineKeyboardMarkup(
            keyboard
        ),

    )


# =========================================================
# USER BUTTONS
# =========================================================

async def button_handler(
    update,
    context
):

    query = update.callback_query

    await query.answer()


    # =====================================================
    # PREMIUM
    # =====================================================

    if query.data == "premium":

        stock = get_stock_count(
            "premium"
        )

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

            "Tap below to see what's included.",

            reply_markup=InlineKeyboardMarkup([

                [

                    InlineKeyboardButton(

                        "👀 PREMIUM ACCOUNT OVERVIEW",

                        callback_data=
                        "premium_overview"

                    )

                ]

            ]),

        )


    # =====================================================
    # PREMIUM OVERVIEW
    # =====================================================

    elif query.data == "premium_overview":

        stock = get_stock_count(
            "premium"
        )

        await query.message.reply_text(

            "👀 PREMIUM ACCOUNT OVERVIEW\n\n"

            "🚗 All real-money cars\n"

            "🎯 Special mission cars\n"

            "🏠 All houses UNLOCKED\n"

            "👕 All Premium & Clan outfits "
            "UNLOCKED\n"

            "👑 King Rank\n"

            "🔫 W16 UNLOCKED\n"

            "🪙 500K Coins\n"

            "💵 50M Cash\n"

            "💃 Premium Animations\n\n"

            "⚡ Instant automatic delivery\n\n"

            f"📦 Available: {stock}\n"

            "💰 Price: 500 ⭐\n\n"

            "Ready to purchase?",

            reply_markup=InlineKeyboardMarkup([

                [

                    InlineKeyboardButton(

                        "💳 BUY FOR 500 ⭐",

                        callback_data=
                        "buy_premium"

                    )

                ]

            ]),

        )


    # =====================================================
    # RESOURCES
    # =====================================================

    elif query.data == "resources":

        stock = get_stock_count(
            "resources"
        )

        if stock <= 0:

            await query.message.reply_text(

                "❌ PREMIUM RESOURCES\n\n"
                "📦 Currently out of stock."

            )

            return


        await query.message.reply_text(

            "⭐ PREMIUM RESOURCES\n\n"

            "🚗 All real-money cars\n"

            "👕 All Premium outfits\n\n"

            "⚡ Instant automatic delivery\n\n"

            f"📦 Available: {stock}\n"

            "💰 Price: 200 ⭐\n\n"

            "Ready to purchase?",

            reply_markup=InlineKeyboardMarkup([

                [

                    InlineKeyboardButton(

                        "💳 BUY FOR 200 ⭐",

                        callback_data=
                        "buy_resources"

                    )

                ]

            ]),

        )


    # =====================================================
    # SUPPORT
    # =====================================================

    elif query.data == "support":

        await query.message.reply_text(

            "❤️ SUPPORT\n\n"

            "Support payment: 10 ⭐\n\n"

            "Your support is greatly appreciated. 🙏",

            reply_markup=InlineKeyboardMarkup([

                [

                    InlineKeyboardButton(

                        "❤️ SUPPORT FOR 10 ⭐",

                        callback_data=
                        "buy_support"

                    )

                ]

            ]),

        )


    # =====================================================
    # BUY PREMIUM
    # =====================================================

    elif query.data == "buy_premium":

        account = get_available_account(
            "premium"
        )

        if account is None:

            await query.message.reply_text(

                "❌ Premium accounts "
                "are currently out of stock."

            )

            return


        await context.bot.send_invoice(

            chat_id=query.from_user.id,

            title="💎 Premium CPM Account",

            description=(
                "Premium CPM Account"
            ),

            payload=(
                f"premium_{account[0]}"
            ),

            currency="XTR",

            prices=[

                LabeledPrice(
                    "Premium Account",
                    PREMIUM_PRICE
                )

            ],

        )


    # =====================================================
    # BUY RESOURCES
    # =====================================================

    elif query.data == "buy_resources":

        account = get_available_account(
            "resources"
        )

        if account is None:

            await query.message.reply_text(

                "❌ Premium Resources "
                "are currently out of stock."

            )

            return


        await context.bot.send_invoice(

            chat_id=query.from_user.id,

            title="⭐ Premium Resources",

            description=(
                "Premium Resources"
            ),

            payload=(
                f"resources_{account[0]}"
            ),

            currency="XTR",

            prices=[

                LabeledPrice(
                    "Premium Resources",
                    RESOURCES_PRICE
                )

            ],

        )


    # =====================================================
    # BUY SUPPORT
    # =====================================================

    elif query.data == "buy_support":

        await context.bot.send_invoice(

            chat_id=query.from_user.id,

            title="❤️ Support",

            description=(
                "Support the Premium CPM Shop"
            ),

            payload="support_10",

            currency="XTR",

            prices=[

                LabeledPrice(
                    "Support",
                    SUPPORT_PRICE
                )

            ],

        )


# =========================================================
# PRE-CHECKOUT
# =========================================================

async def precheckout_callback(
    update,
    context
):

    query = update.pre_checkout_query

    payload = query.invoice_payload


    # -----------------------------------------------------
    # SUPPORT
    # -----------------------------------------------------

    if payload == "support_10":

        await query.answer(
            ok=True
        )

        return


    # -----------------------------------------------------
    # ACCOUNT PRODUCTS
    # -----------------------------------------------------

    if not (
        payload.startswith("premium_")
        or payload.startswith("resources_")
    ):

        await query.answer(
            ok=False
        )

        return


    try:

        account_id = int(
            payload.split("_")[1]
        )

    except (
        IndexError,
        ValueError
    ):

        await query.answer(

            ok=False,

            error_message=
            "Invalid account."

        )

        return


    account = get_account_by_id(
        account_id
    )


    if account is None:

        await query.answer(

            ok=False,

            error_message=
            "Account not found."

        )

        return


    if account[3]:

        await query.answer(

            ok=False,

            error_message=
            "This account is already sold."

        )

        return


    expected_product = (
        "premium"
        if payload.startswith("premium_")
        else "resources"
    )


    if account[4] != expected_product:

        await query.answer(

            ok=False,

            error_message=
            "This account is not available "
            "for this product."

        )

        return


    await query.answer(
        ok=True
    )


# =========================================================
# SUCCESSFUL PAYMENT
# =========================================================

async def successful_payment(
    update,
    context
):

    payment = update.message.successful_payment

    payload = payment.invoice_payload


    # =====================================================
    # SUPPORT PAYMENT
    # =====================================================

    if payload == "support_10":

        await update.message.reply_text(

            "✅ SUPPORT PAYMENT SUCCESSFUL!\n\n"

            "❤️ Thank you for supporting us!\n"

            "Your support is greatly appreciated. 🙏"

        )

        return


    # =====================================================
    # ACCOUNT PAYMENT
    # =====================================================

    if not (
        payload.startswith("premium_")
        or payload.startswith("resources_")
    ):

        return


    try:

        account_id = int(
            payload.split("_")[1]
        )

    except (
        IndexError,
        ValueError
    ):

        await update.message.reply_text(

            "⚠️ Payment received, "
            "but order ID is invalid.\n\n"

            "Please contact support."

        )

        return


    result = mark_account_sold(

        account_id,

        update.effective_user.id

    )


    if result is None:

        await update.message.reply_text(

            "⚠️ Payment received, "
            "but this account was "
            "already sold.\n\n"

            "Please contact support."

        )

        return


    login, password, product_type = result


    if product_type == "premium":

        product_name = (
            "💎 PREMIUM ACCOUNT"
        )

    else:

        product_name = (
            "⭐ PREMIUM RESOURCES"
        )


    await update.message.reply_text(

        "✅ PAYMENT SUCCESSFUL!\n\n"

        f"{product_name}\n\n"

        f"👤 Login: `{login}`\n"

        f"🔐 Password: `{password}`\n\n"

        "⚡ Your account has been "
        "delivered automatically.\n\n"

        "❤️ Thank you for your purchase!",

        parse_mode="Markdown",

    )


# =========================================================
# MAIN
# =========================================================

def main():

    if not BOT_TOKEN:

        raise RuntimeError(
            "BOT_TOKEN is not set."
        )


    if not DATABASE_URL:

        raise RuntimeError(
            "DATABASE_URL is not set."
        )


    init_database()


    app = (
        Application
        .builder()
        .token(BOT_TOKEN)
        .build()
    )


    # START

    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )


    # OWNER COMMAND

    app.add_handler(
        CommandHandler(
            "owner",
            owner
        )
    )


    # OWNER PANEL BUTTONS

    app.add_handler(
        CallbackQueryHandler(

            owner_product_callback,

            pattern=(
                r"^add_product_"
            )

        )
    )


    app.add_handler(
        CallbackQueryHandler(

            owner_panel_callback,

            pattern=r"^owner_"

        )
    )


    # USER BUTTONS

    app.add_handler(
        CallbackQueryHandler(
            button_handler
        )
    )


    # OWNER TEXT

    app.add_handler(
        MessageHandler(

            filters.TEXT
            & ~filters.COMMAND,

            owner_text_handler

        )
    )


    # PAYMENT

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


    print(
        "Bot is running..."
    )


    app.run_polling()


if __name__ == "__main__":

    main()
