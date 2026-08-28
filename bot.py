import os
import psycopg
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice, Update
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    PreCheckoutQueryHandler, MessageHandler, ContextTypes, filters
)

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
# DATABASE
# =========================================================

def db():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set.")
    return psycopg.connect(DATABASE_URL)


def init_database():
    with db() as conn:
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
                ALTER TABLE premium_accounts
                ADD COLUMN IF NOT EXISTS product_type TEXT DEFAULT 'premium'
            """)

            cur.execute("""
                ALTER TABLE premium_accounts
                ADD COLUMN IF NOT EXISTS reserved_by BIGINT
            """)

            cur.execute("""
                ALTER TABLE premium_accounts
                ADD COLUMN IF NOT EXISTS reserved_until TIMESTAMP
            """)

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

            cur.execute("""
                CREATE TABLE IF NOT EXISTS test_purchases (
                    user_id BIGINT PRIMARY KEY,
                    account_id INTEGER,
                    used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cur.execute("""
                UPDATE premium_accounts
                SET product_type = 'premium'
                WHERE product_type IS NULL
            """)

            cur.execute("SELECT COUNT(*) FROM premium_accounts")
            count = cur.fetchone()[0]

            if count == 0 and PREMIUM1_LOGIN and PREMIUM1_PASSWORD:
                cur.execute("""
                    INSERT INTO premium_accounts
                    (login, password, product_type)
                    VALUES (%s, %s, 'premium')
                """, (PREMIUM1_LOGIN, PREMIUM1_PASSWORD))

        conn.commit()


# =========================================================
# OWNER
# =========================================================

def is_owner(update):
    return bool(
        update.effective_user
        and update.effective_user.id == OWNER_ID
    )


# =========================================================
# STOCK
# =========================================================

def clear_expired_reservations():
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE premium_accounts
                SET reserved_by = NULL,
                    reserved_until = NULL
                WHERE sold = FALSE
                  AND reserved_until IS NOT NULL
                  AND reserved_until < CURRENT_TIMESTAMP
            """)
        conn.commit()


def stock(product_type):
    clear_expired_reservations()

    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*)
                FROM premium_accounts
                WHERE sold = FALSE
                  AND product_type = %s
                  AND (
                      reserved_until IS NULL
                      OR reserved_until < CURRENT_TIMESTAMP
                  )
            """, (product_type,))

            return cur.fetchone()[0]


def sold_count(product_type=None):
    with db() as conn:
        with conn.cursor() as cur:

            if product_type:
                cur.execute("""
                    SELECT COUNT(*)
                    FROM premium_accounts
                    WHERE sold = TRUE
                      AND product_type = %s
                """, (product_type,))
            else:
                cur.execute("""
                    SELECT COUNT(*)
                    FROM premium_accounts
                    WHERE sold = TRUE
                """)

            return cur.fetchone()[0]


def total_count(product_type=None):
    with db() as conn:
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


# =========================================================
# ACCOUNT FUNCTIONS
# =========================================================

def get_account(account_id):
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
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
            """, (account_id,))

            return cur.fetchone()


def get_test_account():
    clear_expired_reservations()

    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, login, password
                FROM premium_accounts
                WHERE sold = FALSE
                  AND product_type = 'premium'
                  AND (
                      reserved_until IS NULL
                      OR reserved_until < CURRENT_TIMESTAMP
                  )
                ORDER BY id
                LIMIT 1
            """)

            return cur.fetchone()


def test_used(user_id):
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 1
                FROM test_purchases
                WHERE user_id = %s
            """, (user_id,))

            return cur.fetchone() is not None


def use_test(user_id, account_id):
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO test_purchases
                (user_id, account_id)
                VALUES (%s, %s)
                ON CONFLICT (user_id)
                DO NOTHING
                RETURNING user_id
            """, (user_id, account_id))

            result = cur.fetchone()

        conn.commit()

        return result is not None


def reserve_account(product_type, user_id):
    clear_expired_reservations()

    with db() as conn:
        with conn.cursor() as cur:

            cur.execute("""
                SELECT id, login, password
                FROM premium_accounts
                WHERE sold = FALSE
                  AND product_type = %s
                  AND (
                      reserved_until IS NULL
                      OR reserved_until < CURRENT_TIMESTAMP
                      OR reserved_by = %s
                  )
                ORDER BY id
                LIMIT 1
                FOR UPDATE SKIP LOCKED
            """, (product_type, user_id))

            account = cur.fetchone()

            if not account:
                conn.rollback()
                return None

            cur.execute("""
                UPDATE premium_accounts
                SET reserved_by = %s,
                    reserved_until =
                        CURRENT_TIMESTAMP
                        + (%s * INTERVAL '1 minute')
                WHERE id = %s
            """, (
                user_id,
                RESERVATION_MINUTES,
                account[0]
            ))

        conn.commit()

        return account


# =========================================================
# ORDERS
# =========================================================

def create_order(order_type, account_id, user_id, amount):
    with db() as conn:
        with conn.cursor() as cur:

            cur.execute("""
                INSERT INTO orders
                (
                    order_type,
                    account_id,
                    user_id,
                    amount
                )
                VALUES (%s, %s, %s, %s)
                RETURNING id
            """, (
                order_type,
                account_id,
                user_id,
                amount
            ))

            order_id = cur.fetchone()[0]

        conn.commit()

        return order_id


def get_order(order_id):
    with db() as conn:
        with conn.cursor() as cur:

            cur.execute("""
                SELECT
                    id,
                    order_type,
                    account_id,
                    user_id,
                    amount,
                    status
                FROM orders
                WHERE id = %s
            """, (order_id,))

            return cur.fetchone()


def complete_account_order(
    order_id,
    user_id,
    charge_id
):
    with db() as conn:
        with conn.cursor() as cur:

            cur.execute("""
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
            """, (order_id,))

            order = cur.fetchone()

            if not order:
                conn.rollback()
                return None, "order_not_found"

            (
                _order_id,
                order_type,
                account_id,
                order_user_id,
                amount,
                status
            ) = order

            if status == "paid":
                conn.rollback()
                return None, "already_paid"

            if order_user_id != user_id:
                conn.rollback()
                return None, "wrong_user"

            cur.execute("""
                SELECT
                    login,
                    password,
                    sold,
                    product_type,
                    reserved_by
                FROM premium_accounts
                WHERE id = %s
                FOR UPDATE
            """, (account_id,))

            account = cur.fetchone()

            if not account:
                conn.rollback()
                return None, "account_not_found"

            (
                login,
                password,
                sold,
                product_type,
                reserved_by
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

            expected = (
                PREMIUM_PRICE
                if order_type == "premium"
                else RESOURCES_PRICE
            )

            if amount != expected:
                conn.rollback()
                return None, "wrong_amount"

            cur.execute("""
                UPDATE premium_accounts
                SET sold = TRUE,
                    sold_to = %s,
                    sold_at = CURRENT_TIMESTAMP,
                    reserved_by = NULL,
                    reserved_until = NULL
                WHERE id = %s
            """, (user_id, account_id))

            cur.execute("""
                UPDATE orders
                SET status = 'paid',
                    telegram_payment_charge_id = %s,
                    paid_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (charge_id, order_id))

        conn.commit()

    return {
        "order_id": order_id,
        "login": login,
        "password": password,
        "product_type": product_type,
        "amount": amount
    }, "success"


# =========================================================
# OWNER ACCOUNT MANAGEMENT
# =========================================================

def add_account(login, password, product_type):
    with db() as conn:
        with conn.cursor() as cur:

            cur.execute("""
                INSERT INTO premium_accounts
                (
                    login,
                    password,
                    product_type
                )
                VALUES (%s, %s, %s)
                RETURNING id
            """, (
                login,
                password,
                product_type
            ))

            account_id = cur.fetchone()[0]

        conn.commit()

        return account_id


def delete_account(account_id):
    with db() as conn:
        with conn.cursor() as cur:

            cur.execute("""
                DELETE FROM premium_accounts
                WHERE id = %s
                  AND sold = FALSE
                  AND (
                      reserved_until IS NULL
                      OR reserved_until < CURRENT_TIMESTAMP
                  )
                RETURNING id
            """, (account_id,))

            result = cur.fetchone()

        conn.commit()

        return result


def stock_accounts(product_type):
    clear_expired_reservations()

    with db() as conn:
        with conn.cursor() as cur:

            cur.execute("""
                SELECT id, login
                FROM premium_accounts
                WHERE sold = FALSE
                  AND product_type = %s
                ORDER BY id
            """, (product_type,))

            return cur.fetchall()


# =========================================================
# SALES / REVENUE
# =========================================================

def recent_sales():
    with db() as conn:
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
                WHERE o.status = 'paid'
                ORDER BY o.paid_at DESC
                LIMIT 10
            """)

            return cur.fetchall()


def revenue():
    with db() as conn:
        with conn.cursor() as cur:

            cur.execute("""
                SELECT COALESCE(SUM(amount), 0)
                FROM orders
                WHERE status = 'paid'
            """)
            total = cur.fetchone()[0]

            cur.execute("""
                SELECT COALESCE(SUM(amount), 0)
                FROM orders
                WHERE status = 'paid'
                  AND order_type = 'premium'
            """)
            premium = cur.fetchone()[0]

            cur.execute("""
                SELECT COALESCE(SUM(amount), 0)
                FROM orders
                WHERE status = 'paid'
                  AND order_type = 'resources'
            """)
            resources = cur.fetchone()[0]

            cur.execute("""
                SELECT COALESCE(SUM(amount), 0)
                FROM orders
                WHERE status = 'paid'
                  AND order_type = 'support'
            """)
            support = cur.fetchone()[0]

            return total, premium, resources, support


# =========================================================
# OWNER PANEL
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
            ),
            InlineKeyboardButton(
                "📦 STOCK",
                callback_data="owner_stock"
            )
        ],
        [
            InlineKeyboardButton(
                "📊 STATISTICS",
                callback_data="owner_stats"
            ),
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
        ]
    ])


def owner_text():
    total, _, _, support = revenue()

    return (
        "👑 OWNER PANEL\n\n"
        f"💎 Premium stock: {stock('premium')}\n"
        f"💎 Premium sold: {sold_count('premium')}\n\n"
        f"⭐ Resources stock: {stock('resources')}\n"
        f"⭐ Resources sold: {sold_count('resources')}\n\n"
        f"📊 Total sold: {sold_count()}\n"
        f"💰 Total revenue: {total} ⭐\n"
        f"❤️ Support: {support} ⭐"
    )


async def owner(update, context):
    if not is_owner(update):
        await update.message.reply_text(
            "❌ You are not authorized."
        )
        return

    await update.message.reply_text(
        owner_text(),
        reply_markup=owner_keyboard()
    )


# =========================================================
# OWNER CALLBACKS
# =========================================================

async def owner_callback(update, context):
    q = update.callback_query
    await q.answer()

    if not is_owner(update):
        return

    data = q.data

    # -----------------------------------------------------
    # ONE-TIME TEST
    # -----------------------------------------------------

    if data == "owner_test":

        user_id = q.from_user.id

        if test_used(user_id):
            await q.message.reply_text(
                "🧪 TEST PURCHASE\n\n"
                "❌ Your one-time test has already been used."
            )
            return

        account = get_test_account()

        if not account:
            await q.message.reply_text(
                "🧪 TEST PURCHASE\n\n"
                "❌ No Premium account is available for testing."
            )
            return

        account_id, login, password = account

        if not use_test(user_id, account_id):
            await q.message.reply_text(
                "❌ Your test has already been used."
            )
            return

        await q.message.reply_text(
            "🧪 TEST PURCHASE SUCCESSFUL!\n\n"
            "💎 TEST PREMIUM ACCOUNT\n\n"
            f"🧾 Test ID: TEST-{account_id}\n"
            f"👤 Login: `{login}`\n"
            f"🔐 Password: `{password}`\n\n"
            "⚡ Delivery simulation successful.\n\n"
            "ℹ️ This account was NOT sold and remains in stock.\n"
            "👤 A real customer can still purchase it for 500 ⭐.\n\n"
            "🚫 Your one-time test is now finished.",
            parse_mode="Markdown"
        )

        return

    # -----------------------------------------------------
    # REFRESH
    # -----------------------------------------------------

    if data == "owner_refresh":

        await q.edit_message_text(
            owner_text(),
            reply_markup=owner_keyboard()
        )

        return

    # -----------------------------------------------------
    # STOCK
    # -----------------------------------------------------

    if data == "owner_stock":

        premium = stock_accounts("premium")
        resources = stock_accounts("resources")

        text = "📦 STOCK\n\n💎 PREMIUM\n"

        if premium:
            for account_id, login in premium:
                text += (
                    f"🟢 #{account_id} — `{login}`\n"
                )
        else:
            text += "❌ Empty\n"

        text += "\n⭐ RESOURCES\n"

        if resources:
            for account_id, login in resources:
                text += (
                    f"🟢 #{account_id} — `{login}`\n"
                )
        else:
            text += "❌ Empty\n"

        await q.message.reply_text(
            text,
            parse_mode="Markdown"
        )

        return

    # -----------------------------------------------------
    # STATISTICS
    # -----------------------------------------------------

    if data == "owner_stats":

        total_accounts = total_count()
        total_sold = sold_count()

        percentage = 0

        if total_accounts:
            percentage = round(
                total_sold / total_accounts * 100,
                1
            )

        (
            total,
            premium_revenue,
            resources_revenue,
            support_revenue
        ) = revenue()

        await q.message.reply_text(
            "📊 STATISTICS\n\n"

            f"💎 Premium: {stock('premium')} available / "
            f"{sold_count('premium')} sold\n"

            f"⭐ Resources: {stock('resources')} available / "
            f"{sold_count('resources')} sold\n\n"

            f"📦 Total accounts: {total_accounts}\n"
            f"✅ Total sold: {total_sold}\n"
            f"📈 Sold percentage: {percentage}%\n\n"

            f"💎 Premium revenue: {premium_revenue} ⭐\n"
            f"⭐ Resources revenue: {resources_revenue} ⭐\n"
            f"❤️ Support: {support_revenue} ⭐\n"
            f"💰 TOTAL REVENUE: {total} ⭐"
        )

        return

    # -----------------------------------------------------
    # SALES
    # -----------------------------------------------------

    if data == "owner_sales":

        sales = recent_sales()

        if not sales:
            await q.message.reply_text(
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
            login
        ) in sales:

            if order_type == "premium":
                name = "💎 Premium Account"
            elif order_type == "resources":
                name = "⭐ Premium Resources"
            else:
                name = "❤️ Support"

            text += (
                f"{name}\n"
                f"🧾 Order: #{order_id}\n"
                f"💰 Amount: {amount} ⭐\n"
                f"👤 User: `{user_id}`\
