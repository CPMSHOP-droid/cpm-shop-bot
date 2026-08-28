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

RESERVATION_MINUTES = 30


# =========================================================
# DATABASE CONNECTION
# =========================================================

def get_connection():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set.")

    return psycopg.connect(DATABASE_URL)


# =========================================================
# DATABASE INIT
# =========================================================

def init_database():

    with get_connection() as conn:

        with conn.cursor() as cur:

            # -------------------------------------------------
            # ACCOUNTS
            # -------------------------------------------------

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

            # Product type.
            cur.execute("""
                ALTER TABLE premium_accounts
                ADD COLUMN IF NOT EXISTS product_type TEXT
                DEFAULT 'premium'
            """)

            # Reservation system.
            cur.execute("""
                ALTER TABLE premium_accounts
                ADD COLUMN IF NOT EXISTS reserved_by BIGINT
            """)

            cur.execute("""
                ALTER TABLE premium_accounts
                ADD COLUMN IF NOT EXISTS reserved_until TIMESTAMP
            """)

            # Existing accounts are Premium.
            cur.execute("""
                UPDATE premium_accounts
                SET product_type = 'premium'
                WHERE product_type IS NULL
            """)

            # -------------------------------------------------
            # ORDERS
            # -------------------------------------------------

            cur.execute("""
                CREATE TABLE IF NOT EXISTS orders (
                    id SERIAL PRIMARY KEY,
                    order_type TEXT NOT NULL,
                    account_id INTEGER,
                    user_id BIGINT NOT NULL,
                    amount INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    telegram_payment_charge_id TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    paid_at TIMESTAMP
                )
            """)

            # -------------------------------------------------
            # ONE-TIME TEST TABLE
            # -------------------------------------------------

            cur.execute("""
                CREATE TABLE IF NOT EXISTS test_purchases (
                    user_id BIGINT PRIMARY KEY,
                    account_id INTEGER,
                    used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # -------------------------------------------------
            # FIRST ACCOUNT FROM ENVIRONMENT
            # -------------------------------------------------

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
# OWNER CHECK
# =========================================================

def is_owner(update):

    return (
        update.effective_user
        and update.effective_user.id == OWNER_ID
    )


# =========================================================
# CLEAR EXPIRED RESERVATIONS
# =========================================================

def clear_expired_reservations():

    with get_connection() as conn:

        with conn.cursor() as cur:

            cur.execute("""
                UPDATE premium_accounts
                SET
                    reserved_by = NULL,
                    reserved_until = NULL
                WHERE
                    sold = FALSE
                    AND reserved_until IS NOT NULL
                    AND reserved_until < CURRENT_TIMESTAMP
            """)

        conn.commit()


# =========================================================
# GET STOCK COUNT
# =========================================================

def get_stock_count(product_type):

    clear_expired_reservations()

    with get_connection() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT COUNT(*)
                FROM premium_accounts
                WHERE
                    sold = FALSE
                    AND product_type = %s
                    AND (
                        reserved_until IS NULL
                        OR reserved_until < CURRENT_TIMESTAMP
                    )
                """,
                (product_type,),
            )

            return cur.fetchone()[0]


# =========================================================
# GET SOLD COUNT
# =========================================================

def get_sold_count(product_type=None):

    with get_connection() as conn:

        with conn.cursor() as cur:

            if product_type:

                cur.execute(
                    """
                    SELECT COUNT(*)
                    FROM premium_accounts
                    WHERE
                        sold = TRUE
                        AND product_type = %s
                    """,
                    (product_type,),
                )

            else:

                cur.execute("""
                    SELECT COUNT(*)
                    FROM premium_accounts
                    WHERE sold = TRUE
                """)

            return cur.fetchone()[0]


# =========================================================
# GET TOTAL COUNT
# =========================================================

def get_total_count(product_type=None):

    with get_connection() as conn:

        with conn.cursor() as cur:

            if product_type:

                cur.execute(
                    """
                    SELECT COUNT(*)
                    FROM premium_accounts
                    WHERE product_type = %s
                    """,
                    (product_type,),
                )

            else:

                cur.execute("""
                    SELECT COUNT(*)
                    FROM premium_accounts
                """)

            return cur.fetchone()[0]


# =========================================================
# GET ACCOUNT BY ID
# =========================================================

def get_account_by_id(account_id):

    with get_connection() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT
                    id,
                    login,
                    password,
                    sold,
                    product_type,
                    reserved_by,
                    reserved_until
                FROM premium_accounts
                WHERE id = %s
                """,
                (account_id,),
            )

            return cur.fetchone()


# =========================================================
# GET AVAILABLE ACCOUNT FOR TEST
# =========================================================

def get_test_account():

    clear_expired_reservations()

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
                    AND product_type = 'premium'
                    AND (
                        reserved_until IS NULL
                        OR reserved_until < CURRENT_TIMESTAMP
                    )
                ORDER BY id
                LIMIT 1
            """)

            return cur.fetchone()


# =========================================================
# CHECK TEST STATUS
# =========================================================

def test_already_used(user_id):

    with get_connection() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT 1
                FROM test_purchases
                WHERE user_id = %s
                """,
                (user_id,),
            )

            return cur.fetchone() is not None


# =========================================================
# MARK TEST USED
# =========================================================

def mark_test_used(user_id, account_id):

    with get_connection() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                INSERT INTO test_purchases
                (
                    user_id,
                    account_id
                )
                VALUES (%s, %s)
                ON CONFLICT (user_id)
                DO NOTHING
                RETURNING user_id
                """,
                (
                    user_id,
                    account_id,
                ),
            )

            result = cur.fetchone()

        conn.commit()

        return result is not None


# =========================================================
# RESERVE ACCOUNT
# =========================================================

def reserve_account(product_type, user_id):

    clear_expired_reservations()

    with get_connection() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT
                    id,
                    login,
                    password
                FROM premium_accounts
                WHERE
                    sold = FALSE
                    AND product_type = %s
                    AND (
                        reserved_until IS NULL
                        OR reserved_until < CURRENT_TIMESTAMP
                        OR reserved_by = %s
                    )
                ORDER BY id
                LIMIT 1
                FOR UPDATE SKIP LOCKED
                """,
                (
                    product_type,
                    user_id,
                ),
            )

            account = cur.fetchone()

            if account is None:

                conn.rollback()

                return None

            account_id = account[0]

            cur.execute(
                """
                UPDATE premium_accounts
                SET
                    reserved_by = %s,
                    reserved_until =
                        CURRENT_TIMESTAMP
                        + (%s * INTERVAL '1 minute')
                WHERE id = %s
                """,
                (
                    user_id,
                    RESERVATION_MINUTES,
                    account_id,
                ),
            )

        conn.commit()

        return account


# =========================================================
# CREATE ORDER
# =========================================================

def create_order(
    order_type,
    account_id,
    user_id,
    amount
):

    with get_connection() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                INSERT INTO orders
                (
                    order_type,
                    account_id,
                    user_id,
                    amount,
                    status
                )
                VALUES (%s, %s, %s, %s, 'pending')
                RETURNING id
                """,
                (
                    order_type,
                    account_id,
                    user_id,
                    amount,
                ),
            )

            order_id = cur.fetchone()[0]

        conn.commit()

        return order_id


# =========================================================
# GET ORDER
# =========================================================

def get_order(order_id):

    with get_connection() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT
                    id,
                    order_type,
                    account_id,
                    user_id,
                    amount,
                    status
                FROM orders
                WHERE id = %s
                """,
                (order_id,),
            )

            return cur.fetchone()


# =========================================================
# COMPLETE ACCOUNT ORDER
# =========================================================

def complete_account_order(
    order_id,
    user_id,
    charge_id
):

    with get_connection() as conn:

        with conn.cursor() as cur:

            # Lock order.
            cur.execute(
                """
                SELECT
                    id,
                    order_type,
                    account_id,
                    user_id,
                    amount,
                    status
                FROM orders
                WHERE id = %s
                FOR UPDATE
                """,
                (order_id,),
            )

            order = cur.fetchone()

            if order is None:

                conn.rollback()

                return None, "order_not_found"

            (
                _order_id,
                order_type,
                account_id,
                order_user_id,
                amount,
                status,
            ) = order

            if status == "paid":

                conn.rollback()

                return None, "already_paid"

            if order_user_id != user_id:

                conn.rollback()

                return None, "wrong_user"

            # Lock account.
            cur.execute(
                """
                SELECT
                    login,
                    password,
                    sold,
                    product_type,
                    reserved_by
                FROM premium_accounts
                WHERE id = %s
                FOR UPDATE
                """,
                (account_id,),
            )

            account = cur.fetchone()

            if account is None:

                conn.rollback()

                return None, "account_not_found"

            (
                login,
                password,
                sold,
                product_type,
                reserved_by,
            ) = account

            if sold:

                conn.rollback()

                return None, "already_sold"

            if product_type != order_type:

                conn.rollback()

                return None, "wrong_product"

            if reserved_by != user_id:

                conn.rollback()

                return None, "reservation_lost"

            # Mark account sold.
            cur.execute(
                """
                UPDATE premium_accounts
                SET
                    sold = TRUE,
                    sold_to = %s,
                    sold_at = CURRENT_TIMESTAMP,
                    reserved_by = NULL,
                    reserved_until = NULL
                WHERE id = %s
                """,
                (
                    user_id,
                    account_id,
                ),
            )

            # Mark order paid.
            cur.execute(
                """
                UPDATE orders
                SET
                    status = 'paid',
                    telegram_payment_charge_id = %s,
                    paid_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (
                    charge_id,
                    order_id,
                ),
            )

        conn.commit()

        return {
            "order_id": order_id,
            "login": login,
            "password": password,
            "product_type": product_type,
            "amount": amount,
        }, "success"


# =========================================================
# ADD ACCOUNT
# =========================================================

def add_account(
    login,
    password,
    product_type
):

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


# =========================================================
# DELETE ACCOUNT
# =========================================================

def delete_account(account_id):

    with get_connection() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                DELETE FROM premium_accounts
                WHERE
                    id = %s
                    AND sold = FALSE
                RETURNING id
                """,
                (account_id,),
            )

            result = cur.fetchone()

        conn.commit()

        return result


# =========================================================
# GET STOCK ACCOUNTS
# =========================================================

def get_stock_accounts(product_type):

    clear_expired_reservations()

    with get_connection() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT
                    id,
                    login
                FROM premium_accounts
                WHERE
                    sold = FALSE
                    AND product_type = %s
                ORDER BY id
                """,
                (product_type,),
            )

            return cur.fetchall()


# =========================================================
# RECENT SALES
# =========================================================

def get_recent_sales():

    with get_connection() as conn:

        with conn.cursor() as cur:

            cur.execute("""
                SELECT
                    o.id,
                    o.order_type,
                    o.amount,
                    o.user_id,
                    o.paid_at,
                    a.login
                FROM orders o
                LEFT JOIN premium_accounts a
                    ON a.id = o.account_id
                WHERE
                    o.status = 'paid'
                ORDER BY
                    o.paid_at DESC
                LIMIT 10
            """)

            return cur.fetchall()


# =========================================================
# REVENUE
# =========================================================

def get_revenue():

    with get_connection() as conn:

        with conn.cursor() as cur:

            cur.execute("""
                SELECT
                    COALESCE(SUM(amount), 0)
                FROM orders
                WHERE status = 'paid'
            """)

            total = cur.fetchone()[0]

            cur.execute("""
                SELECT
                    COALESCE(SUM(amount), 0)
                FROM orders
                WHERE
                    status = 'paid'
                    AND order_type = 'premium'
            """)

            premium = cur.fetchone()[0]

            cur.execute("""
                SELECT
                    COALESCE(SUM(amount), 0)
                FROM orders
                WHERE
                    status = 'paid'
                    AND order_type = 'resources'
            """)

            resources = cur.fetchone()[0]

            cur.execute("""
                SELECT
                    COALESCE(SUM(amount), 0)
                FROM orders
                WHERE
                    status = 'paid'
                    AND order_type = 'support'
            """)

            support = cur.fetchone()[0]

            return (
                total,
                premium,
                resources,
                support,
            )


# =========================================================
# OWNER KEYBOARD
# =========================================================

def owner_keyboard():

    return InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "🧪 TEST PURCHASE",
                callback_data="owner_test"
            )
        ],

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

    total_sold = (
        premium_sold
        + resources_sold
    )

    total_revenue, _, _, support_revenue = (
        get_revenue()
    )

    await update.message.reply_text(

        "👑 OWNER PANEL\n\n"

        "💎 PREMIUM ACCOUNT\n"
        f"📦 Stock: {premium_stock}\n"
        f"✅ Sold: {premium_sold}\n\n"

        "⭐ PREMIUM RESOURCES\n"
        f"📦 Stock: {resources_stock}\n"
        f"✅ Sold: {resources_sold}\n\n"

        f"📊 Total sold: {total_sold}\n"
        f"💰 Total revenue: {total_revenue} ⭐\n"
        f"❤️ Support: {support_revenue} ⭐",

        reply_markup=owner_keyboard(),

    )


# =========================================================
# OWNER CALLBACK
# =========================================================

async def owner_panel_callback(
    update,
    context
):

    query = update.callback_query

    await query.answer()

    if not is_owner(update):
        return

    data = query.data


    # =====================================================
    # ONE-TIME TEST PURCHASE
    # =====================================================

    if data == "owner_test":

        user_id = query.from_user.id

        # Already used?
        if test_already_used(user_id):

            await query.message.reply_text(

                "🧪 TEST PURCHASE\n\n"

                "❌ Your one-time test has "
                "already been used.\n\n"

                "The test function cannot be "
                "used again."

            )

            return


        # Find an available Premium account.
        account = get_test_account()

        if account is None:

            await query.message.reply_text(

                "🧪 TEST PURCHASE\n\n"

                "❌ No available Premium account "
                "was found for testing."

            )

            return


        account_id = account[0]
        login = account[1]
        password = account[2]


        # Mark test as used.
        # This does NOT sell the account.
        marked = mark_test_used(
            user_id,
            account_id
        )


        if not marked:

            await query.message.reply_text(

                "❌ Your test has already been used."

            )

            return


        await query.message.reply_text(

            "🧪 TEST PURCHASE SUCCESSFUL!\n\n"

            "💎 TEST PREMIUM ACCOUNT\n\n"

            f"🧾 Test Order: TEST-{account_id}\n\n"

            f"👤 Login: `{login}`\n"
            f"🔐 Password: `{password}`\n\n"

            "⚡ Delivery simulation successful.\n\n"

            "ℹ️ This account was NOT sold.\n"
            "📦 It remains in stock.\n"
            "👤 A real customer can still "
            "purchase this account for 500 ⭐.\n\n"

            "🚫 Your one-time test is now finished.",

            parse_mode="Markdown",

        )

        return


    # =====================================================
    # REFRESH
    # =====================================================

    if data == "owner_refresh":

        premium_stock = get_stock_count("premium")
        resources_stock = get_stock_count("resources")

        premium_sold = get_sold_count("premium")
        resources_sold = get_sold_count("resources")

        total_sold = (
            premium_sold
            + resources_sold
        )

        total_revenue, _, _, support_revenue = (
            get_revenue()
        )

        await query.edit_message_text(

            "👑 OWNER PANEL\n\n"

            "💎 PREMIUM ACCOUNT\n"
            f"📦 Stock: {premium_stock}\n"
            f"✅ Sold: {premium_sold}\n\n"

            "⭐ PREMIUM RESOURCES\n"
            f"📦 Stock: {resources_stock}\n"
            f"✅ Sold: {resources_sold}\n\n"

            f"📊 Total sold: {total_sold}\n"
            f"💰 Total revenue: {total_revenue} ⭐\n"
            f"❤️ Support: {support_revenue} ⭐",

            reply_markup=owner_keyboard(),

        )

        return


    # =====================================================
    # STOCK
    # =====================================================

    if data == "owner_stock":

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

        return


    # =====================================================
    # STATISTICS
    # =====================================================

    if data == "owner_stats":

        premium_stock = get_stock_count("premium")
        resources_stock = get_stock_count("resources")

        premium_sold = get_sold_count("premium")
        resources_sold = get_sold_count("resources")

        premium_total = get_total_count("premium")
        resources_total = get_total_count("resources")

        total_accounts = (
            premium_total
            + resources_total
        )

        total_sold = (
            premium_sold
            + resources_sold
        )

        percentage = 0

        if total_accounts:

            percentage = round(
                (total_sold / total_accounts) * 100,
                1
            )

        (
            revenue,
            premium_revenue,
            resources_revenue,
            support_revenue,
        ) = get_revenue()

        await query.message.reply_text(

            "📊 STATISTICS\n\n"

            "💎 PREMIUM ACCOUNT\n"
            f"📦 Available: {premium_stock}\n"
            f"✅ Sold: {premium_sold}\n"
            f"📊 Total: {premium_total}\n"
            f"💰 Revenue: {premium_revenue} ⭐\n\n"

            "⭐ PREMIUM RESOURCES\n"
            f"📦 Available: {resources_stock}\n"
            f"✅ Sold: {resources_sold}\n"
            f"📊 Total: {resources_total}\n"
            f"💰 Revenue: {resources_revenue} ⭐\n\n"

            "❤️ SUPPORT\n"
            f"💰 Revenue: {support_revenue} ⭐\n\n"

            f"📦 Total accounts: {total_accounts}\n"
            f"✅ Total sold: {total_sold}\n"
            f"📈 Sold percentage: {percentage}%\n"
            f"💰 TOTAL REVENUE: {revenue} ⭐"

        )

        return


    # =====================================================
    # SALES
    # =====================================================

    if data == "owner_sales":

        sales = get_recent_sales()

        if not sales:

            await query.message.reply_text(
                "📈 SALES\n\nNo sales yet."
            )

            return

        text = "📈 LAST 10 SALES\n\n"

        for (
            order_id,
            order_type,
            amount,
            user_id,
            paid_at,
            login,
        ) in sales:

            if order_type == "premium":

                product_name = (
                    "💎 Premium Account"
                )

            elif order_type == "resources":

                product_name = (
                    "⭐ Premium Resources"
                )

            else:

                product_name = (
                    "❤️ Support"
                )

            text += (

                f"{product_name}\n"
                f"🧾 Order: #{order_id}\n"
                f"💰 Amount: {amount} ⭐\n"
                f"👤 User: `{user_id}`\n"

            )

            if login:

                text += (
                    f"🔐 Login: `{login}`\n"
                )

            text += (
                f"🕐 {paid_at}\n\n"
            )


        await query.message.reply_text(
            text,
            parse_mode="Markdown"
        )

        return


    # =====================================================
    # ADD ACCOUNT
    # =====================================================

    if data == "owner_add":

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
                        callback_data=
                        "add_product_premium"
                    )

                ],

                [

                    InlineKeyboardButton(
                        "⭐ RESOURCES — 200 ⭐",
                        callback_data=
                        "add_product_resources"
                    )

                ],

            ])

        )

        return


    # =====================================================
    # DELETE ACCOUNT
    # =====================================================

    if data == "owner_delete":

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

        return


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
# OWNER TEXT HANDLER
# =========================================================

async def owner_text_handler(
    update,
    context
):

    if not is_owner(update):
        return

    text = update.message.text.strip()


    # =====================================================
    # ADD ACCOUNT
    # =====================================================

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

                product_name = (
                    "💎 Premium Account"
                )

            else:

                product_name = (
                    "⭐ Premium Resources"
                )


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


    # =====================================================
    # DELETE ACCOUNT
    # =====================================================

    if context.user_data.get(
        "deleting_account"
    ):

        try:

            account_id = int(text)

        except ValueError:

            await update.message.reply_text(
                "❌ Invalid ID. Send a number."
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
# USER BUTTON HANDLER
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

        stock = get_stock_count("premium")


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

        return


    # =====================================================
    # PREMIUM OVERVIEW
    # =====================================================

    if query.data == "premium_overview":

        stock = get_stock_count("premium")


        await query.message.reply_text(

            "👀 PREMIUM ACCOUNT OVERVIEW\n\n"

            "🚗 All real-money cars\n"
            "🎯 Cars obtained from special missions\n"
            "🏠 All houses UNLOCKED\n"
            "👕 All Premium & Clan outfits UNLOCKED\n"
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

        return


    # =====================================================
    # RESOURCES
    # =====================================================

    if query.data == "resources":

        stock = get_stock_count("resources")


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

        return


    # =====================================================
    # SUPPORT
    # =====================================================

    if query.data == "support":

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

        return


    # =====================================================
    # BUY PREMIUM
    # =====================================================

    if query.data == "buy_premium":

        user_id = query.from_user.id


        account = reserve_account(
            "premium",
            user_id
        )


        if account is None:

            await query.message.reply_text(

                "❌ Premium accounts "
                "are currently out of stock."

            )

            return


        account_id = account[0]


        order_id = create_order(

            "premium",
            account_id,
            user_id,
            PREMIUM_PRICE

        )


        await context.bot.send_invoice(

            chat_id=user_id,

            title="💎 Premium CPM Account",

            description=(
                "Premium CPM Account"
            ),

            payload=(
                f"order_{order_id}"
            ),

            currency="XTR",

            prices=[

                LabeledPrice(
                    "Premium Account",
                    PREMIUM_PRICE
                )

            ],

        )

        return


    # =====================================================
    # BUY RESOURCES
    # =====================================================

    if query.data == "buy_resources":

        user_id = query.from_user.id


        account = reserve_account(
            "resources",
            user_id
        )


        if account is None:

            await query.message.reply_text(

                "❌ Premium Resources "
                "are currently out of stock."

            )

            return


        account_id = account[0]


        order_id = create_order(

            "resources",
            account_id,
            user_id,
            RESOURCES_PRICE

        )


        await context.bot.send_invoice(

            chat_id=user_id,

            title="⭐ Premium Resources",

            description=(
                "Premium Resources"
            ),

            payload=(
                f"order_{order_id}"
            ),

            currency="XTR",

            prices=[

                LabeledPrice(
                    "Premium Resources",
                    RESOURCES_PRICE
                )

            ],

        )

        return


    # =====================================================
    # BUY SUPPORT
    # =====================================================

    if query.data == "buy_support":

        user_id = query.from_user.id


        order_id = create_order(

            "support",
            None,
            user_id,
            SUPPORT_PRICE

        )


        await context.bot.send_invoice(

            chat_id=user_id,

            title="❤️ Support",

            description=(
                "Support the Premium CPM Shop"
            ),

            payload=(
                f"order_{order_id}"
            ),

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


    if not payload.startswith("order_"):

        await query.answer(

            ok=False,

            error_message="Invalid order."

        )

        return


    try:

        order_id = int(
            payload.split("_")[1]
        )

    except (
        IndexError,
        ValueError
    ):

        await query.answer(

            ok=False,

            error_message="Invalid order."

        )

        return


    order = get_order(order_id)


    if order is None:

        await query.answer(

            ok=False,

            error_message="Order not found."

        )

        return


    (
        _id,
        order_type,
        account_id,
        user_id,
        amount,
        status,
    ) = order


    if status == "paid":

        await query.answer(

            ok=False,

            error_message="Order already paid."

        )

        return


    if user_id != query.from_user.id:

        await query.answer(

            ok=False,

            error_message="This order belongs to another user."

        )

        return


    # =====================================================
    # SUPPORT
    # =====================================================

    if order_type == "support":

        if amount != SUPPORT_PRICE:

            await query.answer(

                ok=False,

                error_message="Invalid payment amount."

            )

            return


        await query.answer(ok=True)

        return


    # =====================================================
    # ACCOUNT
    # =====================================================

    account = get_account_by_id(
        account_id
    )


    if account is None:

        await query.answer(

            ok=False,

            error_message="Account not found."

        )

        return


    (
        _account_id,
        login,
        password,
        sold,
        product_type,
        reserved_by,
        reserved_until,
    ) = account


    if sold:

        await query.answer(

            ok=False,

            error_message="This account is already sold."

        )

        return


    if product_type != order_type:

        await query.answer(

            ok=False,

            error_message="Invalid product."

        )

        return


    if reserved_by != query.from_user.id:

        await query.answer(

            ok=False,

            error_message="This account is no longer reserved for you."

        )

        return


    if order_type == "premium":

        expected_price = PREMIUM_PRICE

    else:

        expected_price = RESOURCES_PRICE


    if amount != expected_price:

        await query.answer(

            ok=False,

            error_message="Invalid payment amount."

        )

        return


    await query.answer(ok=True)


# =========================================================
# SUCCESSFUL PAYMENT
# =========================================================

async def successful_payment(
    update,
    context
):

    payment = update.message.successful_payment

    payload = payment.invoice_payload


    if not payload.startswith("order_"):
        return


    try:

        order_id = int(
            payload.split("_")[1]
        )

    except (
        IndexError,
        ValueError
    ):

        await update.message.reply_text(

            "⚠️ Payment received, "
            "but the order ID is invalid.\n\n"
            "Please contact support."

        )

        return


    order = get_order(order_id)


    if order is None:

        await update.message.reply_text(

            "⚠️ Payment received, "
            "but the order could not be found.\n\n"
            "Please contact support."

        )

        return


    order_type = order[1]


    # =====================================================
    # SUPPORT
    # =====================================================

    if order_type == "support":

        with get_connection() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    UPDATE orders
                    SET
                        status = 'paid',
                        telegram_payment_charge_id = %s,
                        paid_at = CURRENT_TIMESTAMP
                    WHERE
                        id = %s
                        AND status != 'paid'
                    """,
                    (
                        payment.telegram_payment_charge_id,
                        order_id,
                    ),
                )

            conn.commit()


        await update.message.reply_text(

            "✅ SUPPORT PAYMENT SUCCESSFUL!\n\n"

            "❤️ Thank you for supporting us!\n\n"

            "Your support is greatly appreciated. 🙏"

        )


        # Owner notification.

        try:

            await context.bot.send_message(

                chat_id=OWNER_ID,

                text=(

                    "❤️ NEW SUPPORT PAYMENT\n\n"

                    f"🧾 Order: #{order_id}\n"
                    f"💰 Amount: {SUPPORT_PRICE} ⭐\n"
                    f"👤 User ID: {update.effective_user.id}\n\n"

                    "✅ Payment successful."

                )

            )

        except Exception:
            pass


        return


    # =====================================================
    # ACCOUNT PAYMENT
    # =====================================================

    result, status = complete_account_order(

        order_id,

        update.effective_user.id,

        payment.telegram_payment_charge_id

    )


    if result is None:

        if status == "already_paid":

            await update.message.reply_text(

                "⚠️ This order has already been completed."

            )

        else:

            await update.message.reply_text(

                "⚠️ Payment received, "
                "but the account could not be delivered.\n\n"

                "Please contact support."

            )

        return


    login = result["login"]
    password = result["password"]
    product_type = result["product_type"]
    amount = result["amount"]


    if product_type == "premium":

        product_name = (
            "💎 PREMIUM ACCOUNT"
        )

    else:

        product_name = (
            "⭐ PREMIUM RESOURCES"
        )


    # =====================================================
    # CUSTOMER DELIVERY
    # =====================================================

    await update.message.reply_text(

        "✅ PAYMENT SUCCESSFUL!\n\n"

        f"{product_name}\n\n"

        f"🧾 Order ID: #{order_id}\n\n"

        f"👤 Login: `{login}`\n"
        f"🔐 Password: `{password}`\n\n"

        "⚡ Your account has been "
        "delivered automatically.\n\n"

        "❤️ Thank you for your purchase!",

        parse_mode="Markdown",

    )


    # =====================================================
    # OWNER SALE NOTIFICATION
    # =====================================================

    try:

        await context.bot.send_message(

            chat_id=OWNER_ID,

            text=(

                "💰 NEW SALE!\n\n"

                f"{product_name}\n"

                f"🧾 Order: #{order_id}\n"

                f"💰 Amount: {amount} ⭐\n"

                f"👤 User ID: {update.effective_user.id}\n"

                f"👤 Login: `{login}`\n\n"

                "✅ Payment successful."

            ),

            parse_mode="Markdown"

        )

    except Exception:
        pass


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


    # Database automatically creates/migrates tables.
    init_database()


    app = (
        Application
        .builder()
        .token(BOT_TOKEN)
        .build()
    )


    # -----------------------------------------------------
    # START
    # -----------------------------------------------------

    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )


    # -----------------------------------------------------
    # OWNER
    # -----------------------------------------------------

    app.add_handler(
        CommandHandler(
            "owner",
            owner
        )
    )


    # -----------------------------------------------------
    # OWNER PRODUCT SELECTION
    # -----------------------------------------------------

    app.add_handler(
        CallbackQueryHandler(
            owner_product_callback,
            pattern=r"^add_product_"
        )
    )


    # -----------------------------------------------------
    # OWNER CALLBACKS
    # -----------------------------------------------------

    app.add_handler(
        CallbackQueryHandler(
            owner_panel_callback,
            pattern=r"^owner_"
        )
    )


    # -----------------------------------------------------
    # USER CALLBACKS
    # -----------------------------------------------------

    app.add_handler(
        CallbackQueryHandler(
            button_handler
        )
    )


    # -----------------------------------------------------
    # OWNER TEXT INPUT
    # -----------------------------------------------------

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            owner_text_handler
        )
    )


    # -----------------------------------------------------
    # PRE-CHECKOUT
    # -----------------------------------------------------

    app.add_handler(
        PreCheckoutQueryHandler(
            precheckout_callback
        )
    )


    # -----------------------------------------------------
    # SUCCESSFUL PAYMENT
    # -----------------------------------------------------

    app.add_handler(
        MessageHandler(
            filters.SUCCESSFUL_PAYMENT,
            successful_payment
        )
    )


    print("Bot is running...")


    app.run_polling()


# =========================================================
# START APPLICATION
# =========================================================

if __name__ == "__main__":
    main()
