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

            if order_user_id !=
