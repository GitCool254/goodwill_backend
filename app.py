from flask import Flask, request, jsonify, Response
from flask_cors import CORS
from decimal import Decimal, ROUND_HALF_UP
import fitz  # PyMuPDF
import io
import random
import zipfile
import os
import hashlib
import requests
import json
from datetime import datetime, timedelta
import boto3
from botocore.client import Config
import math
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from time import time
from filelock import FileLock, Timeout
import threading
import re
import uuid
import secrets
from google.oauth2 import service_account
from googleapiclient.discovery import build
import qrcode
from PIL import Image

# APP SETUP
app = Flask(__name__)

# Rate limiter (per-IP)
limiter = Limiter(
    key_func=get_remote_address, default_limits=[]  # no global limits
)
limiter.init_app(app)

app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

CORS(
    app,
    resources={

        r"/generate_ticket": {
            "origins": [
                "https://goodwillrafflestore.onrender.com",
                "https://goodwillstores.onrender.com",
                "https://goodwillrafflestores.vercel.app",
                "https://goodwillstores.vercel.app",
            ]
        },
        r"/download_ticket": {
            "origins": [
                "https://goodwillrafflestore.onrender.com",
                "https://goodwillstores.onrender.com",
                "https://goodwillrafflestores.vercel.app",
                "https://goodwillstores.vercel.app",
            ],
            "expose_headers": ["Content-Disposition"],
        },
        r"/redownload_ticket": {
            "origins": [
                "https://goodwillrafflestore.onrender.com",
                "https://goodwillstores.onrender.com",
                "https://goodwillrafflestores.vercel.app",
                "https://goodwillstores.vercel.app",
            ],
            "expose_headers": ["Content-Disposition"],
        },
        r"/my_tickets": {
            "origins": [
                "https://goodwillrafflestore.onrender.com",
                "https://goodwillstores.onrender.com",
                "https://goodwillrafflestores.vercel.app",
                "https://goodwillstores.vercel.app",
            ]
        },
        r"/ticket_state": {
            "origins": [
                "https://goodwillrafflestore.onrender.com",
                "https://goodwillstores.onrender.com",
                "https://goodwillrafflestores.vercel.app",
                "https://goodwillstores.vercel.app",
            ]
        },
        r"/tickets_sold": {
            "origins": [
                "https://goodwillrafflestore.onrender.com",
                "https://goodwillstores.onrender.com",
                "https://goodwillrafflestores.vercel.app",
                "https://goodwillstores.vercel.app",
            ]
        },
        r"/recent_winners": {
            "origins": [
                "https://goodwillrafflestore.onrender.com",
                "https://goodwillstores.onrender.com",
                "https://goodwillrafflestores.vercel.app",
                "https://goodwillstores.vercel.app",
            ]
        },
        r"/paypal_config": {
            "origins": [
                "https://goodwillrafflestore.onrender.com",
                "https://goodwillstores.onrender.com",
                "https://goodwillrafflestores.vercel.app",
                "https://goodwillstores.vercel.app",
            ]
        },
        r"/referral/generate": {
            "origins": [
                "https://goodwillrafflestore.onrender.com",
                "https://goodwillstores.onrender.com",
                "https://goodwillrafflestores.vercel.app",
                "https://goodwillstores.vercel.app",
            ]
        },
        r"/referral/rewards": {
            "origins": [
                "https://goodwillrafflestore.onrender.com",
                "https://goodwillstores.onrender.com",
                "https://goodwillrafflestores.vercel.app",
                "https://goodwillstores.vercel.app",
            ]
        },
        r"/address_toggles": {
            "origins": [
                "https://goodwillrafflestore.onrender.com",
                "https://goodwillstores.onrender.com",
                "https://goodwillrafflestores.vercel.app",
                "https://goodwillstores.vercel.app",
            ]
        },
        r"/winners_detail_toggle": {
            "origins": [
                "https://goodwillrafflestore.onrender.com",
                "https://goodwillstores.onrender.com",
                "https://goodwillrafflestores.vercel.app",
                "https://goodwillstores.vercel.app",
            ]
        },
        r"/bootstrap": {
            "origins": [
                "https://goodwillrafflestore.onrender.com",
                "https://goodwillstores.onrender.com",
                "https://goodwillrafflestores.vercel.app",
                "https://goodwillstores.vercel.app",
            ]
        },
        r"/get_sku": {
            "origins": [
                "https://goodwillrafflestore.onrender.com",
                "https://goodwillstores.onrender.com",
                "https://goodwillrafflestores.vercel.app",
                "https://goodwillstores.vercel.app",
            ]
        },
        r"/check_ticket_status": {
            "origins": [
                "https://goodwillrafflestore.onrender.com",
                "https://goodwillstores.onrender.com",
                "https://goodwillrafflestores.vercel.app",
                "https://goodwillstores.vercel.app",
            ]
        },
        r"/verify_ticket/*": {
            "origins": [
                "https://goodwillrafflestore.onrender.com",
                "https://goodwillstores.onrender.com",
                "https://goodwillrafflestores.vercel.app",
                "https://goodwillstores.vercel.app",
            ]
        },
    },
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_PATH = os.path.join(BASE_DIR, "Goodwillstores_Ticket_Template10.pdf")
# Service account key (already in your Termux setup)
GSHEET_KEY_FILE = os.path.join(BASE_DIR, "goodwill-backend.json")
GSHEET_ID = os.environ.get("GSHEET_ID")

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

GSHEET_KEY_JSON = os.environ.get("GSHEET_KEY_JSON")
print("GSHEET_KEY_JSON exists:", bool(GSHEET_KEY_JSON))
print("GSHEET_ID:", GSHEET_ID)

credentials = service_account.Credentials.from_service_account_info(
    json.loads(GSHEET_KEY_JSON),
    scopes=SCOPES
)

sheets_service = build("sheets", "v4", credentials=credentials)

def log_to_google_sheet(full_name, email, ticket_numbers, amount, order_id, local_time=None):
    """
    Appends a row to the Google Sheet with: date, name, email, ticket numbers, amount, order_id
    If local_time is provided (datetime object), use it; otherwise use UTC.
    """
    if not GSHEET_ID:
        print("⚠️ GSHEET_ID not set. Skipping logging.")
        return

    try:
        sheet = sheets_service.spreadsheets()
        if local_time:
            now = local_time.strftime("%Y-%m-%d %H:%M:%S")
        else:
            now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        row = [
            now,
            full_name,
            email,
            ", ".join(ticket_numbers),
            str(amount),
            order_id,
        ]
        body = {"values": [row]}
        sheet.values().append(
            spreadsheetId=GSHEET_ID,
            range="Sheet1!A:F",
            valueInputOption="RAW",
            body=body,
        ).execute()
        print(f"✅ Logged order {order_id} to Google Sheet")
    except Exception as e:
        print("❌ Failed to log to Google Sheet:", e)

MAX_SHEET_RETRIES = 3
SHEET_RETRY_DELAY = 1  # seconds

def log_to_google_sheet_with_retry(full_name, email, ticket_numbers, amount, order_id, local_time=None):
    for attempt in range(1, MAX_SHEET_RETRIES + 1):
        try:
            log_to_google_sheet(
                full_name=full_name,
                email=email,
                ticket_numbers=ticket_numbers,
                amount=amount,
                order_id=order_id,
                local_time=local_time,
            )
            return True
        except Exception as e:
            print(f"⚠️ Google Sheets logging failed (attempt {attempt}): {e}")
            if attempt < MAX_SHEET_RETRIES:
                time.sleep(SHEET_RETRY_DELAY)
            else:
                print("❌ Google Sheets logging ultimately failed, skipping...")
                return False

# --------------------------------------------------
# PATHS
# --------------------------------------------------

# --------------------------------------------------
# TICKET SALES LEDGER (ADDITIVE – DO NOT MODIFY)
# --------------------------------------------------

SALES_FILE = os.path.join(BASE_DIR, "ticket_sales.json")
SALES_KEY = "state/ticket_sales.json"

def read_sales():
    """Returns total tickets sold (persistent).
    R2 authoritative, local fallback.
    """
    # 1️⃣ R2 primary
    # if r2_client:
    try:
        obj = r2_client.get_object(
            Bucket=R2_BUCKET_NAME,
            Key=SALES_KEY,
        )
        return int(json.loads(obj["Body"].read()).get("sold", 0))
    except Exception:
        pass

    # 2️⃣ Local fallback
    if os.path.exists(SALES_FILE):
        try:
            with open(SALES_FILE, "r") as f:
                return int(json.load(f).get("sold", 0))
        except Exception:
            pass

    return 0

def write_sales(total_sold):
    payload = json.dumps(
        {
            "sold": int(total_sold),
            "updated_at": datetime.utcnow().isoformat() + "Z",
        },
        indent=2,
    ).encode()

    # 1️⃣ R2 primary
    if r2_client:
        try:
            r2_client.put_object(
                Bucket=R2_BUCKET_NAME,
                Key=SALES_KEY,
                Body=payload,
                ContentType="application/json",
            )
            return
        except Exception as e:
            print("R2 sales save failed, fallback local:", e)

    # 2️⃣ Local fallback
    with open(SALES_FILE, "w") as f:
        f.write(payload.decode())


# --------------------------------------------------
# AUTHORITATIVE TICKET STATE (DO NOT RESET HISTORY)
# --------------------------------------------------
STATE_FILE = os.path.join(BASE_DIR, "ticket_state.json")

STATE_KEY = "state/ticket_state.json"
STATE_LOCK_FILE = STATE_FILE + ".lock"

NONCE_LOCK_FILE = os.path.join(BASE_DIR, "nonce.lock")
NONCE_FILE = os.path.join(BASE_DIR, "used_nonces.json")

REFERRALS_LOCK_FILE = os.path.join(BASE_DIR, "referrals.lock")
referrals_lock = FileLock(REFERRALS_LOCK_FILE)

def load_ticket_state():
    """Persistent authoritative remaining ticket state.
    R2 primary, local fallback.
    """
    # 1️⃣ R2 primary
    if r2_client:
        try:
            obj = r2_client.get_object(
                Bucket=R2_BUCKET_NAME,
                Key=STATE_KEY,
            )
            return json.loads(obj["Body"].read())
        except Exception:
            pass

    # 2️⃣ Local fallback
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass

    return {"remaining": None, "last_calc_date": None, "initialized": False}


def save_ticket_state(state):
    # ----------------------------------------------------------
    # Record the moment the raffle FIRST reached zero remaining.
    # This timestamp is immutable — once set it is never re-written.
    # It anchors the 48-hour countdown after which all issued
    # tickets are marked EXPIRED.
    # ----------------------------------------------------------
    try:
        remaining_val = int(state.get("remaining") or 0)
    except Exception:
        remaining_val = 0

    if remaining_val <= 0 and not state.get("sold_out_at"):
        state["sold_out_at"] = datetime.utcnow().isoformat() + "Z"
        print(f"🏁 Raffle sold out at {state['sold_out_at']}")

    payload = json.dumps(state, indent=2).encode()

    # 1️⃣ R2 primary
    if r2_client:
        try:
            r2_client.put_object(
                Bucket=R2_BUCKET_NAME,
                Key=STATE_KEY,
                Body=payload,
                ContentType="application/json",
            )
            return
        except Exception as e:
            print("R2 state save failed, fallback local:", e)

    # 2️⃣ Local fallback
    with open(STATE_FILE, "w") as f:
        f.write(payload.decode())


def load_raffle_meta():
    # 1️⃣ R2 primary
    if r2_client:
        try:
            obj = r2_client.get_object(
                Bucket=R2_BUCKET_NAME,
                Key=RAFFLE_META_KEY,
            )
            return json.loads(obj["Body"].read())
        except Exception:
            pass

    # 2️⃣ Local fallback
    if os.path.exists(RAFFLE_META_FILE):
        try:
            with open(RAFFLE_META_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass

    return {"round": 1}


def save_raffle_meta(data):
    payload = json.dumps(data, indent=2).encode()

    # 1️⃣ R2 primary
    if r2_client:
        try:
            r2_client.put_object(
                Bucket=R2_BUCKET_NAME,
                Key=RAFFLE_META_KEY,
                Body=payload,
                ContentType="application/json",
            )
            return
        except Exception as e:
            print("R2 raffle_meta save failed, fallback local:", e)

    # 2️⃣ Local fallback
    with open(RAFFLE_META_FILE, "w") as f:
        f.write(payload.decode())


def perform_raffle_reset_if_requested():
    global RAFFLE_ID

    if not RAFFLE_RESET_FLAG:
        return

    print("🔁 RAFFLE RESET INITIATED")

    # -------------------------
    # 1️⃣ Delete ticket state
    # -------------------------
    if r2_client:
        try:
            r2_client.delete_object(Bucket=R2_BUCKET_NAME, Key=STATE_KEY)
            print("🗑 Deleted R2 ticket_state")
        except Exception:
            pass

        try:
            r2_client.delete_object(Bucket=R2_BUCKET_NAME, Key=SALES_KEY)
            print("🗑 Deleted R2 ticket_sales")
        except Exception:
            pass

    if os.path.exists(STATE_FILE):
        os.remove(STATE_FILE)
        print("🗑 Deleted local ticket_state.json")

    if os.path.exists(SALES_FILE):
        os.remove(SALES_FILE)
        print("🗑 Deleted local ticket_sales.json")

    # -------------------------
    # 2️⃣ Increment RAFFLE ROUND
    # -------------------------
    meta = load_raffle_meta()
    current_round = int(meta.get("round", 1))
    new_round = current_round + 1

    meta["round"] = new_round
    save_raffle_meta(meta)

    # Update RAFFLE_ID dynamically
    RAFFLE_ID = f"goodwill-raffle-2026-round{new_round}"

    print("🚀 New RAFFLE_ID:", RAFFLE_ID)

    # IMPORTANT: turn flag off after reset
    print("⚠️ Remember to set RAFFLE_RESET_FLAG back to False after deployment.")

def perform_cmst_reset_if_requested():
    if not CMST_RESET_FLAG:
        return

    print("🔁 CMST RESET INITIATED")

    if r2_client:
        try:
            r2_client.delete_object(Bucket=R2_BUCKET_NAME, Key=CMST_KEY)
            print("🗑 Deleted R2 cmst_records")
        except Exception:
            pass

    if os.path.exists(CMST_FILE):
        os.remove(CMST_FILE)
        print("🗑 Deleted local cmst_records.json")

    print("⚠️ Remember to set CMST_RESET_FLAG back to False after deployment.")

# --------------------------------------------------
# DAILY TICKET DECAY (AUTHORITATIVE)
# --------------------------------------------------

RAFFLE_START_DATE = "2026-08-12"
SIMULATED_START_DATE = "2026-08-15"
INITIAL_TICKETS = 250
DEDICATED_DAYS = 20
RAFFLE_ID = "goodwill-raffle-2026-round5"

# --------------------------------------------------
# RAFFLE RESET CONTROL (MANUAL CAMPAIGN RESTART)
# --------------------------------------------------

RAFFLE_RESET_FLAG = False  # 🔁 Set to True to reset campaign
CMST_RESET_FLAG = False  # 🔁 Set to True to reset CMST records

RAFFLE_META_FILE = os.path.join(BASE_DIR, "raffle_meta.json")
RAFFLE_META_KEY = "state/raffle_meta.json"

def seeded_random(seed: int) -> float:
    x = math.sin(seed) * 10000
    return x - math.floor(x)


def compute_daily_decay(days_passed: int) -> int:
    """Deterministic daily decay.
    Same raffle + same day = same decay forever.
    """
    if days_passed <= 0:
        return 0

    progress = min(days_passed / DEDICATED_DAYS, 1)

    base_min = 3
    base_max = 6

    min_daily = base_min + int(progress * 4)
    max_daily = base_max + int(progress * 6)

    # 🔒 Deterministic seed per raffle + per day
    seed_str = f"{RAFFLE_ID}: {days_passed}"
    seed_hash = hashlib.sha256(seed_str.encode()).hexdigest()
    seed_int = int(seed_hash[:8], 16)

    rng = random.Random(seed_int)
    return rng.randint(min_daily, max_daily)

def compute_total_decay(days_passed: int) -> int:
    """
    Returns cumulative decay from day 1 up to days_passed.
    """
    total = 0
    for d in range(1, days_passed + 1):
        total += compute_daily_decay(d)
    return total

def apply_daily_decay_if_needed():
    """
    Authoritative daily decay.
    Uses SAME lock as record_ticket_sale() to prevent race conditions.
    Remaining can NEVER increase.
    """

    with FileLock(STATE_LOCK_FILE):

        state = load_ticket_state()
        today = datetime.utcnow().strftime("%Y-%m-%d")

        sold = read_sales()
        max_allowed = max(INITIAL_TICKETS - sold, 0)

        # -----------------------------
        # INITIALIZE (first run ever)
        # -----------------------------
        if not state.get("initialized"):
            state["remaining"] = max_allowed
            state["initialized"] = True
            state["last_calc_date"] = today
            save_ticket_state(state)
            return state

        # -----------------------------
        # HARD GUARD: NEVER increase
        # -----------------------------
        if state.get("remaining") is None or state["remaining"] > max_allowed:
            state["remaining"] = max_allowed
            save_ticket_state(state)
            # Already
            # processed
            # today
        if state.get("last_calc_date") == today:
            return state

        # Sold out guard
        if int(state.get("remaining", 0)) <= 0:
            state["remaining"] = 0
            state["last_calc_date"] = today
            save_ticket_state(state)
            return state

        # -----------------------------                                        # DECAY COMPUTATION
        # -----------------------------
        start_date_str = SIMULATED_START_DATE or RAFFLE_START_DATE
        start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
        days_passed = max((datetime.utcnow() - start_date).days, 0)

        total_decay = compute_total_decay(days_passed)

        authoritative_remaining = max(INITIAL_TICKETS - total_decay - sold, 0)

        # FINAL HARD GUARD (never increase)
        if authoritative_remaining > state["remaining"]:
            authoritative_remaining = state["remaining"]

        state["remaining"] = authoritative_remaining
        state["last_calc_date"] = today

        save_ticket_state(state)
        return state

# PERSISTENT TICKET STORAGE

TICKET_STORAGE_DIR = os.environ.get(
    "TICKET_STORAGE_DIR", os.path.join(BASE_DIR, "storage", "tickets")
)

os.makedirs(TICKET_STORAGE_DIR, exist_ok=True)

MAX_REDOWNLOADS = 3

# --------------------------------------------------
# TICKET VERIFICATION SYSTEM
# --------------------------------------------------

# Public frontend URL used inside ticket QR codes.
# The QR points to the WEBSITE verification page,
# NOT directly to the backend API.
TICKET_VERIFY_BASE_URL = os.environ.get(
    "TICKET_VERIFY_BASE_URL",
    "https://goodwillstores.vercel.app/verify-ticket"
)

# Local fallback storage for individual verification records.
VERIFICATION_STORAGE_DIR = os.path.join(
    BASE_DIR,
    "storage",
    "ticket_verification"
)

os.makedirs(VERIFICATION_STORAGE_DIR, exist_ok=True)

# R2 stores each verification record independently.
# Individual objects avoid maintaining one large shared JSON index.
VERIFICATION_R2_PREFIX = "verification/tickets/"


def generate_ticket_verification_token():
    """
    Generates a cryptographically secure random token.

    The token contains no customer information,
    ticket number, product name, email, or other
    predictable information.
    """
    return secrets.token_urlsafe(32)


def build_ticket_verification_url(token):
    """
    Builds the public website URL encoded into the ticket QR code.
    """
    return f"{TICKET_VERIFY_BASE_URL.rstrip('/')}/{token}"


def verification_record_local_path(token):
    """
    Returns the local fallback path for a verification record.
    """
    return os.path.join(
        VERIFICATION_STORAGE_DIR,
        f"{token}.json"
    )


def save_ticket_verification_record(token, record):
    """
    Persist a ticket verification record.

    Primary:
        Cloudflare R2

    Fallback:
        Local JSON file

    Each ticket has its own record so verification records
    do not depend on a single shared JSON index.
    """

    payload = json.dumps(
        record,
        indent=2
    ).encode("utf-8")

    # 1️⃣ R2 PRIMARY
    if r2_client:
        try:
            r2_client.put_object(
                Bucket=R2_BUCKET_NAME,
                Key=f"{VERIFICATION_R2_PREFIX}{token}.json",
                Body=payload,
                ContentType="application/json",
            )

            print(
                f"✅ Ticket verification record saved to R2: "
                f"{record.get('ticket_no')}"
            )
            return

        except Exception as e:
            print(
                "⚠️ R2 verification save failed, "
                "using local fallback:",
                e
            )

    # 2️⃣ LOCAL FALLBACK
    try:
        path = verification_record_local_path(token)

        with open(path, "w") as f:
            f.write(payload.decode("utf-8"))

        print(
            f"✅ Ticket verification record saved locally: "
            f"{record.get('ticket_no')}"
        )

    except Exception as e:
        print(
            "❌ Failed to save local ticket verification record:",
            e
        )
        raise


def load_ticket_verification_record(token):
    """
    Load a ticket verification record.

    Primary:
        Cloudflare R2

    Fallback:
        Local JSON file

    Returns:
        dict if found
        None if not found
    """

    # 1️⃣ R2 PRIMARY
    if r2_client:
        try:
            obj = r2_client.get_object(
                Bucket=R2_BUCKET_NAME,
                Key=f"{VERIFICATION_R2_PREFIX}{token}.json",
            )

            return json.loads(
                obj["Body"].read()
            )

        except Exception:
            pass

    # 2️⃣ LOCAL FALLBACK
    path = verification_record_local_path(token)

    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)

        except Exception as e:
            print(
                "❌ Failed to read local verification record:",
                e
            )

    return None


def create_ticket_verification_record(
    token,
    ticket_no,
    full_name,
    email,
    product_title,
    ticket_price,
    cmst_no,
    order_id,
):
    """
    Creates the authoritative backend verification record
    for one generated raffle ticket.

    The record is created independently for every ticket.
    """

    record = {
        "token": token,
        "ticket_no": ticket_no,
        "status": "ACTIVE",
        "full_name": full_name,
        "email": email,
        "product": product_title,
        "ticket_price": str(ticket_price),
        "cmst_no": int(cmst_no),
        "order_id": order_id,
        "raffle_id": RAFFLE_ID,
        "created_at": datetime.utcnow().isoformat() + "Z",
    }

    save_ticket_verification_record(
        token=token,
        record=record,
    )

    return record

# --------------------------------------------------
# CLEANUP POLICY
# --------------------------------------------------

CLEANUP_AFTER_DAYS = 10
SECONDS_PER_DAY = 86400

# --------------------------------------------------
# EVENT DATA
# --------------------------------------------------

EVENT_DATE = "Dec 30, 2025"
EVENT_PLACE = "District of Colombia, DC, United States"
EVENT_TIME = "5PM"

MAX_NAME_LENGTH = 43
MAX_PLACE_LENGTH = 45

# 🔒 Security: Maximum tickets per order
MAX_TICKETS_PER_ORDER = 10

MAX_EXPAND_CHARS = 25
EXPAND_PADDING = 6

# --------------------------------------------------
# HELPERS
# --------------------------------------------------
ORDERS_INDEX_FILE = os.path.join(TICKET_STORAGE_DIR, "orders.json")
ORDERS_INDEX_KEY = "indexes/orders.json"
EMAIL_INDEX_KEY = "indexes/email_orders.json"
USED_ORDERS_KEY = "indexes/used_orders.json"
REFERRALS_FILE = os.path.join(BASE_DIR, "referrals.json")
REFERRALS_KEY = "state/referrals.json"
CMST_FILE = os.path.join(BASE_DIR, "cmst_records.json")
CMST_KEY = "state/cmst_records.json"
CMST_LOCK_FILE = os.path.join(BASE_DIR, "cmst.lock")

# Two-layer lock:
#  • cmst_thread_lock  → protects against concurrent threads inside one worker process
#  • cmst_lock         → protects against concurrent worker processes (gunicorn workers)
#    timeout=15        → prevents infinite deadlock if a worker crashes mid-lock
cmst_thread_lock = threading.Lock()
cmst_lock = FileLock(CMST_LOCK_FILE, timeout=15)

# ===============================
# Cloudflare R2 (Storage Only) Step 1R
# ===============================

R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY")
R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME")

r2_client = None

# Initialize R2 client if all credentials exist
if all(
    [R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME]
):
    r2_client = boto3.client(
        "s3",
        endpoint_url=f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )

print("🟢 R2 ENABLED:", bool(r2_client))


def record_ticket_sale(quantity: int):

    with FileLock(STATE_LOCK_FILE):

        state = load_ticket_state()

        if not state.get("initialized"):
            state["remaining"] = INITIAL_TICKETS
            state["initialized"] = True

        remaining = int(state.get("remaining", 0))

        if remaining < quantity:
            raise ValueError("Not enough tickets remaining")

        # Burn first
        state["remaining"] = remaining - quantity
        state["last_calc_date"] = datetime.utcnow().strftime("%Y-%m-%d")
        save_ticket_state(state)

        # Then update ledger
        current_sold = read_sales()
        write_sales(current_sold + quantity)

        print(f"📈 Tickets sold: +{quantity}, remaining {state['remaining']}")


# Step 2R
def upload_zip_to_r2(order_id: str, zip_bytes: bytes):
    """
    Best-effort upload.
    Failure here must NEVER affect ticket delivery.
    """
    if not r2_client:
        return

    try:
        r2_client.put_object(
            Bucket=R2_BUCKET_NAME,
            Key=f"tickets/{order_id}.zip",
            Body=zip_bytes,
            ContentType="application/zip",
        )
    except Exception as e:
        # Silent fail — log only
        print("R2 upload failed:", e)


def upload_pdf_to_r2(order_id: str, filename: str, pdf_bytes: bytes):
    if not r2_client:
        return

    try:
        r2_client.put_object(
            Bucket=R2_BUCKET_NAME,
            Key=f"tickets/{order_id}/{filename}",
            Body=pdf_bytes,
            ContentType="application/pdf",
        )
    except Exception as e:
        print("R2 PDF upload failed:", e)


def fetch_zip_from_r2(order_id):
    if not r2_client:
        return None

    try:
        obj = r2_client.get_object(
            Bucket=R2_BUCKET_NAME, Key=f"tickets/{order_id}.zip"
        )
        return obj["Body"].read()
    except Exception as e:
        print("R2 fetch failed:", e)
        return None

def fetch_pdf_from_r2(order_id: str, filename: str):
    if not r2_client:
        return None

    try:
        obj = r2_client.get_object(
            Bucket=R2_BUCKET_NAME,
            Key=f"tickets/{order_id}/{filename}",
        )
        return obj["Body"].read()
    except Exception as e:
        print("R2 PDF fetch failed:", e)
        return None

def cleanup_old_r2_objects(days=CLEANUP_AFTER_DAYS):
    """
    Deletes old ticket ZIPs and PDFs from R2.
    Safe, best-effort, non-blocking.
    """
    if not r2_client:
        return

    cutoff_ts = datetime.utcnow().timestamp() - (days * SECONDS_PER_DAY)

    try:
        paginator = r2_client.get_paginator("list_objects_v2")
        pages = paginator.paginate(Bucket=R2_BUCKET_NAME, Prefix="tickets/")

        for page in pages:
            for obj in page.get("Contents", []):
                last_modified = obj["LastModified"].timestamp()
                if last_modified < cutoff_ts:
                    try:
                        r2_client.delete_object(
                            Bucket=R2_BUCKET_NAME, Key=obj["Key"]
                        )
                        print("🧹 R2 deleted:", obj["Key"])
                    except Exception as e:
                        print("R2 delete failed:", e)

    except Exception as e:
        print("R2 cleanup error:", e)

def load_orders_index():
    # 1️⃣ PRIMARY: R2
    if r2_client:
        try:
            obj = r2_client.get_object(
                Bucket=R2_BUCKET_NAME,
                Key=ORDERS_INDEX_KEY,
            )
            return json.loads(obj["Body"].read())
        except Exception as e:
            print("R2 orders index missing, fallback to local:", e)

    # 2️⃣ FALLBACK: local disk
    if os.path.exists(ORDERS_INDEX_FILE):
        try:
            with open(ORDERS_INDEX_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass

    return {"orders": {}}

def save_orders_index(data):
    payload = json.dumps(data, indent=2).encode()

    # 1️⃣ PRIMARY: R2
    if r2_client:
        try:
            r2_client.put_object(
                Bucket=R2_BUCKET_NAME,
                Key=ORDERS_INDEX_KEY,
                Body=payload,
                ContentType="application/json",
            )
            return
        except Exception as e:
            print("R2 save failed, fallback to local:", e)

    # 2️⃣ FALLBACK: local
    os.makedirs(TICKET_STORAGE_DIR, exist_ok=True)
    with open(ORDERS_INDEX_FILE, "w") as f:
        f.write(payload.decode())

def load_email_index():
    if r2_client:
        try:
            obj = r2_client.get_object(
                Bucket=R2_BUCKET_NAME,
                Key=EMAIL_INDEX_KEY,
            )
            return json.loads(obj["Body"].read())
        except Exception:
            pass

    return {}

def save_email_index(data):
    payload = json.dumps(data, indent=2).encode()

    if r2_client:
        try:
            r2_client.put_object(
                Bucket=R2_BUCKET_NAME,
                Key=EMAIL_INDEX_KEY,
                Body=payload,
                ContentType="application/json",
            )
            return
        except Exception as e:
            print("R2 email index save failed:", e)

def load_used_orders():
    # 1️⃣ R2 PRIMARY
    if r2_client:
        try:
            obj = r2_client.get_object(
                Bucket=R2_BUCKET_NAME,
                Key=USED_ORDERS_KEY,
            )
            return set(json.loads(obj["Body"].read()))
        except Exception:
            pass

    # 2️⃣ Fallback memory
    return set()

def save_used_orders(order_set):
    payload = json.dumps(list(order_set), indent=2).encode()

    # 1️⃣ R2 PRIMARY
    if r2_client:
        try:
            r2_client.put_object(
                Bucket=R2_BUCKET_NAME,
                Key=USED_ORDERS_KEY,
                Body=payload,
                ContentType="application/json",
            )
            return
        except Exception as e:
            print("R2 used_orders save failed:", e)

    # 2️⃣ If R2 fails → memory only (do nothing)

def load_referrals():
    # 1️⃣ R2 primary
    if r2_client:
        try:
            obj = r2_client.get_object(Bucket=R2_BUCKET_NAME, Key=REFERRALS_KEY)
            return json.loads(obj["Body"].read())
        except Exception:
            pass
    # 2️⃣ Local fallback
    if os.path.exists(REFERRALS_FILE):
        try:
            with open(REFERRALS_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_referrals(data):
    payload = json.dumps(data, indent=2).encode()
    if r2_client:
        try:
            r2_client.put_object(Bucket=R2_BUCKET_NAME, Key=REFERRALS_KEY, Body=payload, ContentType="application/json")
            return
        except Exception:
            pass
    with open(REFERRALS_FILE, "w") as f:
        f.write(payload.decode())

# --------------------------------------------------
# CMST NUMBER SYSTEM (unique progressive number per email)
# --------------------------------------------------
def load_cmst_records():
    # 1️⃣ R2 primary
    if r2_client:
        try:
            obj = r2_client.get_object(Bucket=R2_BUCKET_NAME, Key=CMST_KEY)
            return json.loads(obj["Body"].read())
        except Exception:
            pass
    # 2️⃣ Local fallback
    if os.path.exists(CMST_FILE):
        try:
            with open(CMST_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_cmst_records(data):
    payload = json.dumps(data, indent=2).encode()
    if r2_client:
        try:
            r2_client.put_object(
                Bucket=R2_BUCKET_NAME,
                Key=CMST_KEY,
                Body=payload,
                ContentType="application/json",
            )
            return
        except Exception:
            pass
    with open(CMST_FILE, "w") as f:
        f.write(payload.decode())


def get_or_assign_cmst(email):
    """
    Returns the CMST number for the given email.
    Thread-safe + process-safe via two-layer locking:
      • cmst_thread_lock  → in-process (threads)
      • cmst_lock         → cross-process (gunicorn workers), 15s timeout
    Retries up to 3 times if the file lock times out.
    """
    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            with cmst_thread_lock:                 # in-process
                with cmst_lock:                    # cross-process, 15s timeout
                    records = load_cmst_records()

                    # Return existing if already assigned
                    if email in records:
                        return int(records[email])

                    # Find the next available number
                    used = set(int(v) for v in records.values())
                    next_no = 100
                    while next_no in used:
                        next_no += 1
                    if next_no > 1000:
                        raise ValueError("CMST number limit reached (1000)")

                    records[email] = next_no
                    save_cmst_records(records)
                    print(f"🆔 CMST assigned: {email} -> CMST No {next_no}")
                    return next_no

        except Timeout:
            print(f"⚠️ CMST lock timeout (attempt {attempt}/{max_retries})")
            if attempt == max_retries:
                raise RuntimeError("CMST lock acquisition failed after retries")
            time.sleep(0.5)

def register_order(order_id, email, files, product, quantity, ticket_numbers, user_local_time=None):
    index = load_orders_index()

    index["orders"][order_id] = {
        "email": email,
        "files": files,
        "product": product,
        "quantity": quantity,
        "tickets": ticket_numbers,  # list of ticket numbers
        "created_at": datetime.utcnow().isoformat() + "Z",
        "user_local_time": user_local_time.isoformat() if user_local_time else None,
    }

    save_orders_index(index)

    # 🔥 Update email lookup index
    email_index = load_email_index()

    if email not in email_index:
        email_index[email] = []

    if order_id not in email_index[email]:
        email_index[email].append(order_id)

    save_email_index(email_index)

def validate_order_id(order_id):
    if not isinstance(order_id, str):
        return False
    if not re.fullmatch(r"[A-Za-z0-9\-]{10,50}", order_id):
        return False
    return True


# --------------------------------------------------
# HOLIDAY PROMOTION LOGIC
# --------------------------------------------------
def get_easter_sunday(year):
    """Return Easter Sunday date for the given year (Anonymous Gregorian algorithm)."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return datetime(year, month, day)

def is_holiday_active(now=None):
    """Returns True if the given datetime (or current UTC if none) falls within any holiday promotion period."""
    if now is None:
        now = datetime.utcnow()
    year = now.year

    # Compute dynamic Easter range: Good Friday to Easter Monday (4 days)
    easter_sunday = get_easter_sunday(year)
    good_friday = easter_sunday - timedelta(days=2)
    easter_monday = easter_sunday + timedelta(days=1)
    # Set times to ensure whole‑day coverage
    good_friday = good_friday.replace(hour=0, minute=0, second=0)
    easter_monday = easter_monday.replace(hour=23, minute=59, second=59)

    # Holiday definitions (matching frontend HolidaySystem.jsx)
    holidays = [
        {"type": "weekly", "weekday": 4},  # Black Friday: every Friday
        {"type": "range", "start": datetime(year, 12, 10), "end": datetime(year, 12, 31, 23, 59, 59)},
        {"type": "range", "start": datetime(year, 1, 1), "end": datetime(year, 1, 7, 23, 59, 59)},
        {"type": "range", "start": datetime(year, 4, 10), "end": datetime(year, 4, 14, 23, 59, 59)},  # Valentine
        {"type": "range", "start": good_friday, "end": easter_monday},  # Easter
        {"type": "range", "start": datetime(year, 4, 30), "end": datetime(year, 5, 1, 23, 59, 59)},  # Labor's Day
    ]

    for h in holidays:
        if h["type"] == "weekly":
            if now.weekday() == h["weekday"]:
                return True
        else:
            if h["start"] <= now <= h["end"]:
                return True
    return False

def cleanup_old_orders(days=CLEANUP_AFTER_DAYS):
    cutoff = datetime.utcnow().timestamp() - (days * 86400)
    for order_id in os.listdir(TICKET_STORAGE_DIR):
        order_dir = os.path.join(TICKET_STORAGE_DIR, order_id)

        if not os.path.isdir(order_dir):
            continue

        try:
            if os.path.getmtime(order_dir) < cutoff:
                for f in os.listdir(order_dir):
                    os.remove(os.path.join(order_dir, f))
                os.rmdir(order_dir)
        except Exception as e:
            print("Cleanup error:", e)


PAYPAL_MODE = os.environ.get("PAYPAL_MODE", "live")
PAYPAL_API_BASE = (
    "https://api-m.paypal.com"
    if PAYPAL_MODE == "live"
    else "https://api-m.sandbox.paypal.com"
)

# Mode‑specific credentials
if PAYPAL_MODE == "live":
    PAYPAL_CLIENT_ID = os.environ.get("PAYPAL_LIVE_CLIENT_ID")
    PAYPAL_SECRET = os.environ.get("PAYPAL_LIVE_SECRET")
else:
    PAYPAL_CLIENT_ID = os.environ.get("PAYPAL_SANDBOX_CLIENT_ID")
    PAYPAL_SECRET = os.environ.get("PAYPAL_SANDBOX_SECRET")

# Fallback to old single‑pair variables if new ones are missing (optional)
if not PAYPAL_CLIENT_ID:
    PAYPAL_CLIENT_ID = os.environ.get("PAYPAL_CLIENT_ID")
if not PAYPAL_SECRET:
    PAYPAL_SECRET = os.environ.get("PAYPAL_SECRET")

USED_ORDERS = load_used_orders()  # R2 primary, memory fallback

# ==================================================
# TRUE ANTI-REPLAY PROTECTION (R2 PERSISTENT)
# ==================================================

NONCE_INDEX_KEY = "security/used_nonces.json"
NONCE_EXPIRY_SECONDS = 300  # 5 minutes

def load_used_nonces():
    # 1️⃣ R2 PRIMARY
    if r2_client:
        try:
            obj = r2_client.get_object(
                Bucket=R2_BUCKET_NAME,
                Key=NONCE_INDEX_KEY,
            )
            return json.loads(obj["Body"].read())
        except Exception as e:
            print("R2 nonce load failed, fallback local:", e)

    # 2️⃣ LOCAL FALLBACK
    if os.path.exists(NONCE_FILE):
        try:
            with open(NONCE_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            print("Local nonce load failed:", e)

    return {}

def save_used_nonces(data):
    payload = json.dumps(data, indent=2).encode()

    # 1️⃣ R2 PRIMARY
    if r2_client:
        try:
            r2_client.put_object(
                Bucket=R2_BUCKET_NAME,
                Key=NONCE_INDEX_KEY,
                Body=payload,
                ContentType="application/json",
            )
            return
        except Exception as e:
            print("R2 nonce save failed, fallback local:", e)

    # 2️⃣ LOCAL FALLBACK
    try:
        with open(NONCE_FILE, "w") as f:
            f.write(payload.decode())
    except Exception as e:
        print("Local nonce save failed:", e)


REPLAY_BOUNCE_COUNT = 0

GENERATED_FILES = {}  # order_id -> { filename, mimetype, data }
MAX_CACHE_ITEMS = 100

def verify_paypal_order(order_id, expected_amount):
    auth = (PAYPAL_CLIENT_ID, PAYPAL_SECRET)

    r = requests.get(
        f"{PAYPAL_API_BASE}/v2/checkout/orders/{order_id}",
        auth=auth,
        headers={"Content-Type": "application/json"},
        timeout=10,
    )

    print("🔎 PayPal URL:", f"{PAYPAL_API_BASE}/v2/checkout/orders/{order_id}")
    print("🔎 Status code:", r.status_code)
    print("🔎 Response:", r.text)

    if r.status_code != 200:
        return False, "PayPal verification failed"

    order = r.json()

    # Validate intent
    if order.get("intent") != "CAPTURE":
        return False, "Invalid PayPal intent"

    if order.get("status") != "COMPLETED":
        return False, "Payment not completed"

    # Validate capture details (extra security)
    payments = order["purchase_units"][0].get("payments", {})
    captures = payments.get("captures", [])

    if not captures:
        return False, "No capture found"

    valid_capture = None
    for cap in captures:
        if cap.get("status") == "COMPLETED":
            valid_capture = cap
            break

    if not valid_capture:
        return False, "No completed capture found"

    capture = valid_capture

    if capture.get("status") != "COMPLETED":
        return False, "Payment not captured"

    capture_amount = Decimal(capture["amount"]["value"]).quantize(
        Decimal("0.01")
    )

    if capture_amount != expected_amount:
        return False, "Captured amount mismatch"

    # Validate currency
    currency = order["purchase_units"][0]["amount"]["currency_code"]
    if currency != "USD":
        return False, f"Invalid currency ({currency})"

    # Validate receiver email (LIVE only)
    if PAYPAL_MODE == "live":
        payee = order["purchase_units"][0].get("payee", {})
        receiver_email = payee.get("email_address")

        expected_email = os.environ.get("PAYPAL_BUSINESS_EMAIL")

        if not expected_email:
            return False, "Merchant email not configured"

        if receiver_email != expected_email:
            return False, "Payment not sent to correct merchant"

    paid_amount = Decimal(
        order["purchase_units"][0]["amount"]["value"]
    ).quantize(Decimal("0.01"))

    if paid_amount != expected_amount:
        return (
            False,
            f"Amount mismatch (paid {paid_amount}, expected {expected_amount})",
        )

    used_orders = load_used_orders()
    if order_id in used_orders:
        return False, "Order already used"

    used_orders.add(order_id)
    save_used_orders(used_orders)
    return True, None

def generate_ticket_no():
    return f"GWS-{uuid.uuid4().hex[:8].upper()}"

def generate_ticket_with_placeholders(
    full_name, ticket_no, event_date, ticket_price, event_place, event_time, product_title, cmst_no, verification_url
):

    if not os.path.exists(TEMPLATE_PATH):
        raise FileNotFoundError(f"Template not found: {TEMPLATE_PATH}")
    doc = fitz.open(TEMPLATE_PATH)
    page = doc[0]
    page.wrap_contents()

    # Per-placeholder font sizes (falls back to DEFAULT_FONT_SIZE)
    PLACEHOLDER_FONT_SIZES = {
        "{{NAME_SMALL}}": 7,     # Small name placeholder
        "{{NAME}}": 10,          # Legacy fallback
    }
    DEFAULT_FONT_SIZE = 10

    first_name = full_name.split()[0] if full_name.split() else full_name

    replacements = {
        "{{NAME_SMALL}}": first_name,   # Small name
        "{{NAME}}": full_name,         # Legacy fallback
        "{{TICKET-NO}}": ticket_no,
        "{{TICKET_PRICE}}": ticket_price,
        "{{EVENT_PLACE}}": event_place,
        "{{DATE}}": event_date,
        "{{TIME}}": event_time,
    }

    combined_placeholder = "{{DATE}} {{TIME}}"
    combined_value = f"{event_date} {event_time}".strip()
    for placeholder, value in replacements.items():

        # Determine font size for THIS placeholder BEFORE
        fontsize = PLACEHOLDER_FONT_SIZES.get(placeholder, DEFAULT_FONT_SIZE)

        if placeholder in ("{{DATE}}", "{{TIME}}"):
            matches = page.search_for(combined_placeholder)
            if matches:
                placeholder = combined_placeholder
                value = combined_value
            else:
                matches = page.search_for(placeholder)
        else:
            matches = page.search_for(placeholder)

        if not matches:
            continue

        for rect in matches:
            text_str = str(value)
            fontname = "helv"

            # --- Measure text width ---
            text_width = fitz.get_text_length(
                text_str, fontname=fontname, fontsize=fontsize
            )

            base_width = rect.width

            # --- Rectangle sizing logic ---
            if len(text_str) <= MAX_EXPAND_CHARS:
                new_width = max(base_width, text_width + EXPAND_PADDING)
            else:
                avg_char_width = text_width / max(len(text_str), 1)
                locked_width = (
                    avg_char_width * MAX_EXPAND_CHARS
                ) + EXPAND_PADDING
                new_width = max(base_width, locked_width)

            flex_rect = fitz.Rect(
                rect.x0, rect.y0, rect.x0 + new_width, rect.y1
            )

            # --- Clear background ---
            if placeholder == "{{NAME_SMALL}}":
                # The complete congratulatory message is redrawn as one
                # continuous sentence so the first name, "!", and "Thank"
                # remain grammatically spaced with no leftover placeholder gap.
                #
                # Template:
                # "Congratulations {{NAME_SMALL}}! Thank you for participating
                #  with Goodwillstores. We wish you the best of luck!"
                #
                # Only this congratulatory message line is replaced.
                # Everything else in the ticket remains unchanged.

                words = page.get_text("words")

                # Locate the complete congratulatory message line.
                line_words = [
                    w for w in words
                    if abs(
                        ((w[1] + w[3]) / 2)
                        - ((rect.y0 + rect.y1) / 2)
                    ) < 3
                ]
                line_words.sort(key=lambda w: w[0])

                if line_words:
                    sentence_rect = fitz.Rect(
                        line_words[0][0],
                        min(w[1] for w in line_words),
                        line_words[-1][2],
                        max(w[3] for w in line_words),
                    )

                    # Clear only the existing congratulatory message line.
                    page.add_redact_annot(sentence_rect, fill=False)
                    page.apply_redactions(images=0)

                    # Rebuild the complete sentence with normal text spacing.
                    text_str = (
                        f"Congratulations {first_name}! "
                        f"Thank you for participating with Goodwillstores. "
                        f"We wish you the best of luck!"
                    )

                    fontname = "helv"
                    fontsize = 7.5

                    # Keep the original left position and vertical position.
                    flex_rect = fitz.Rect(
                        sentence_rect.x0,
                        sentence_rect.y0,
                        sentence_rect.x1,
                        sentence_rect.y1,
                    )

                    # Automatically reduce only if the rebuilt sentence
                    # would exceed the original sentence width.
                    while fontsize > 6:
                        text_width = fitz.get_text_length(
                            text_str,
                            fontname=fontname,
                            fontsize=fontsize
                        )

                        if text_width <= flex_rect.width:
                            break

                        fontsize -= 1

                    # Insert the complete sentence as one continuous line.
                    page.insert_text(
                        (
                            flex_rect.x0,
                            flex_rect.y0
                            + (flex_rect.height / 2)
                            + (fontsize * 0.35)
                        ),
                        text_str,
                        fontsize=fontsize,
                        fontname=fontname,
                        color=(0, 0, 0),
                    )

                    # Prevent the normal placeholder insertion below from
                    # inserting the first name a second time.
                    continue

            else:
                page.draw_rect(
                    flex_rect,
                    color=(1, 1, 1),
                    fill=(1, 1, 1)
                )


            # --- Auto-shrink font to fit ---
            while fontsize > 6:
                if fitz.get_text_length(
                    text_str, fontname=fontname, fontsize=fontsize
                ) <= (flex_rect.width - 4):
                    break
                fontsize -= 1

            # --- CORRECT vertical centering (baseline-aware) ---
            y_position = (
                flex_rect.y0 + (flex_rect.height / 2) + (fontsize * 0.35)
            )

            # --- Draw text INSIDE rectangle ---
            page.insert_text(
                (flex_rect.x0 + 2, y_position),
                text_str,
                fontsize=fontsize,
                fontname=fontname,
                color=(0, 0, 0),
            )

    # ----------------------------------------------------------------
    # QR CODE
    # ----------------------------------------------------------------
    # Drawn ONCE per ticket, AFTER all placeholder replacements.
    # The QR code contains ONLY the public verification URL.
    # It does NOT contain any customer name, email, product, ticket
    # number, CMST number, or ticket status. The backend remains the
    # authoritative source of truth.
    # ----------------------------------------------------------------
    qr_data = verification_url

    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=6,
        border=2,
    )
    qr.add_data(qr_data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    img_bytes = io.BytesIO()
    img.save(img_bytes, format="PNG")
    img_bytes.seek(0)

    qr_placeholder = "{{QR_CODE}}"
    qr_rects = page.search_for(qr_placeholder)
    if qr_rects:
        qr_rect_found = qr_rects[0]
        # Clear the placeholder text.
        page.draw_rect(qr_rect_found, color=(1, 1, 1), fill=(1, 1, 1))
        # Standard square QR area.
        qr_size = 100
        qr_rect = fitz.Rect(
            qr_rect_found.x0,
            qr_rect_found.y0,
            qr_rect_found.x0 + qr_size,
            qr_rect_found.y0 + qr_size,
        )
        page.insert_image(
            qr_rect, stream=img_bytes, keep_proportion=True
        )
    else:
        print(
            f"⚠️ QR placeholder '{{QR_CODE}}' "
            f"not found in template for ticket {ticket_no}"
        )

    output = io.BytesIO()
    doc.save(output)
    doc.close()
    output.seek(0)
    return output

def stream_file(path, chunk_size=8192):
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            yield chunk

def send_ticket_file(order_id, enforce_limit=False):
    order_dir = os.path.join(TICKET_STORAGE_DIR, order_id)

    # 🔹 STEP 4: Local-first, R2 fallback
    if not os.path.exists(order_dir):

        # ✅ Step 1: Try orders index recovery (authoritative history)

        index = load_orders_index()
        order = index.get("orders", {}).get(order_id)

        if order:
            os.makedirs(order_dir, exist_ok=True)

            # If this was a multi-ticket order, expect ZIP from R2
            if order.get("quantity", 1) > 1:
                zip_bytes = fetch_zip_from_r2(order_id)

                if not zip_bytes:
                    return (
                        jsonify(
                            {
                                "error": "TICKET_EXPIRED",
                                "message": "This ticket has expired and is no longer available for download.",
                            }
                        ),
                        410,
                    )

                zip_path = os.path.join(
                    order_dir, f"RaffleTickets_{order_id}.zip"
                )
                with open(zip_path, "wb") as f:
                    f.write(zip_bytes)

            # 🔁 Attempt R2 recovery for single-ticket PDF
            if order.get("quantity", 1) == 1:
                filename = order["files"][0]
                pdf_path = os.path.join(order_dir, filename)

                # Try R2 recovery only if file not already present
                if not os.path.exists(pdf_path):
                    pdf_bytes = fetch_pdf_from_r2(order_id, filename)

                    if not pdf_bytes:
                        return (
                            jsonify(
                                {
                                    "error": "TICKET_EXPIRED",
                                    "message": "This ticket has expired and is no longer available for download.",
                                }
                            ),
                            410,
                        )

                    with open(pdf_path, "wb") as f:
                        f.write(pdf_bytes)

            # (Frontend fix will ensure immediate download)
        else:
            return (
                jsonify(
                    {
                        "error": "TICKET_NOT_FOUND",
                        "message": "We couldn’t find this ticket.",
                    }
                ),
                404,
            )

        # Basic integrity check (ZIP magic header)

    # 🔒 Enforce max re-downloads (PDF + ZIP, including cached)
    if enforce_limit:
        counter_path = os.path.join(order_dir, "downloads.txt")
        count = 0

        if os.path.exists(counter_path):
            with open(counter_path, "r") as f:
                count = int(f.read().strip() or 0)

        if count >= MAX_REDOWNLOADS:
            return (
                jsonify(
                    {
                        "error": "MAX_REDOWNLOADS_REACHED",
                        "message": "You have reached the maximum number of allowed re-downloads.",
                    }
                ),
                403,
            )

        with open(counter_path, "w") as f:
            f.write(str(count + 1))

    # ⚡ FAST PATH: single-ticket in-memory download
    cached = GENERATED_FILES.get(order_id)
    if cached and cached["filename"].lower().endswith(".pdf"):
        return Response(
            cached["data"],
            mimetype="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{cached["filename"]}"',
                "Content-Length": str(len(cached["data"])),
            },
            direct_passthrough=True,  # 🚀 ZERO-COPY
        )

    files = [f for f in os.listdir(order_dir) if not f.endswith(".txt")]
    if not files:
        return jsonify({"error": "Ticket not found"}), 404

    # 🔒 Deterministic selection
    zip_files = [f for f in files if f.lower().endswith(".zip")]
    pdf_files = [f for f in files if f.lower().endswith(".pdf")]

    if zip_files:
        selected_file = zip_files[0]  # Multi-ticket case
    elif pdf_files:
        selected_file = pdf_files[0]  # Single-ticket case
    else:
        return jsonify({"error": "Unsupported ticket format"}), 404

    file_path = os.path.join(order_dir, selected_file)

    print("📦 Sending ticket file:", file_path)

    # 🔎 Set correct mimetype (CRITICAL FIX)
    if selected_file.lower().endswith(".pdf"):
        mimetype = "application/pdf"
    else:
        mimetype = "application/zip"

    return Response(
        stream_file(file_path),
        mimetype=mimetype,
        headers={
            "Content-Disposition": f'attachment; filename="{selected_file}"',
            "Content-Length": os.path.getsize(file_path),
        },
    )

@app.before_request
def enforce_https():
    # Allow health checks internally
    if request.endpoint == "health_check":
        return

    # Render sets X-Forwarded-Proto
    if request.headers.get("X-Forwarded-Proto", "http") != "https":
        return jsonify({"error": "HTTPS required"}), 403

def verify_request_nonce(req):
    timestamp = req.headers.get("X-Timestamp")
    nonce = req.headers.get("X-Nonce")

    if not timestamp or not nonce:
        return False, "Missing security headers"

    try:
        ts = int(timestamp)
        now = int(datetime.utcnow().timestamp())
        if abs(now - ts) > NONCE_EXPIRY_SECONDS:
            return False, "Request expired"
    except Exception:
        return False, "Invalid timestamp"

    with FileLock(NONCE_LOCK_FILE):

        used_nonces = load_used_nonces()

        # Cleanup expired
        expired = [
            n for n, stored_ts in used_nonces.items()
            if now - stored_ts > NONCE_EXPIRY_SECONDS
        ]
        for n in expired:
            del used_nonces[n]

        if nonce in used_nonces:
            return False, "Replay detected"

        used_nonces[nonce] = ts
        save_used_nonces(used_nonces)

    return True, None


# --------------------------------------------------
# ROUTES
# --------------------------------------------------

# Simple in-memory caching

CACHE_EXPIRY = 10  # seconds

_ticket_state_cache = {"data": None, "timestamp": 0}


@app.route("/ticket_state", methods=["GET"])
@limiter.limit("5 per 10 seconds")  # max 5 requests per IP every 10 seconds
def ticket_state():
    now = time()

    # -----------------------------
    # CACHE HIT
    # -----------------------------
    if (
        _ticket_state_cache["data"]
        and now - _ticket_state_cache["timestamp"] < CACHE_EXPIRY
    ):
        cached_resp, status = _ticket_state_cache["data"]
        payload = cached_resp.get_json()
        payload["cache"] = "HIT"
        return jsonify(payload), status

    # -----------------------------
    # CACHE MISS (fresh compute)
    # -----------------------------
    state = apply_daily_decay_if_needed()
    today = datetime.utcnow().strftime("%Y-%m-%d")

    remaining = state.get("remaining")
    tickets_sold_ui = None
    if isinstance(remaining, int):
        tickets_sold_ui = max(INITIAL_TICKETS - remaining, 0)

    payload = {
        "remaining": remaining,
        "tickets_sold": tickets_sold_ui,
        "last_calc_date": state.get("last_calc_date"),
        "initialized": state.get("initialized", False),
        "today": today,
        "cache": "MISS",
    }

    response = jsonify(payload), 200

    # update cache
    _ticket_state_cache["data"] = response
    _ticket_state_cache["timestamp"] = now

    return response

@app.route("/tickets_sold", methods=["GET"])
@limiter.limit("5 per 10 seconds")
def tickets_sold():
    """
    Frontend reads how many tickets are already sold.
    """
    return jsonify({"total_sold": read_sales()}), 200

@app.route("/paypal_config", methods=["GET"])
def paypal_config():
    return jsonify({
        "client_id": PAYPAL_CLIENT_ID,
        "mode": PAYPAL_MODE
    })

@app.route("/", methods=["GET"])
def health_check():
    return (
        jsonify(
            {
                "status": "ok",
                "service": "raffle-api",
                "version": "1.0.0",
                "time": datetime.utcnow().isoformat() + "Z",
            }
        ),
        200,
    )

def order_already_generated(order_id):
    order_dir = os.path.join(TICKET_STORAGE_DIR, order_id)
    return os.path.exists(order_dir) and os.listdir(order_dir)

@app.route("/generate_ticket", methods=["POST"])
@limiter.limit("5 per minute")
def generate_ticket():
    ok, err = verify_request_nonce(request)
    if not ok:
        return jsonify({"error": err}), 403

    data = request.get_json(force=True)

    # --- Get user's local time from timezone offset header (client provides timezone offset in minutes) ---
    # Client should send: "X-Timezone-Offset": "-300" (for EST) or "+600" (for AEST)
    user_tz_offset_str = request.headers.get("X-Timezone-Offset")
    user_local_now = None
    if user_tz_offset_str:
        try:
            offset_minutes = int(user_tz_offset_str)
            # Apply offset to server UTC time to get user's local time
            user_local_now = datetime.utcnow() + timedelta(minutes=offset_minutes)
        except ValueError:
            user_local_now = None

    referral_code = data.get("referral_code", "").strip()
    use_free_ticket = data.get("use_free_ticket", False)

    full_name = data.get("name", "").strip()
    event_place = data.get("event_place", EVENT_PLACE).strip()

    if len(event_place) > MAX_PLACE_LENGTH:
        event_place = event_place[:MAX_PLACE_LENGTH] + "…"

    raw_quantity = data.get("quantity")
    if raw_quantity is None:
        return jsonify({"error": "Missing quantity"}), 400

    try:
        # Convert to Decimal to handle numeric strings precisely
        qty_dec = Decimal(str(raw_quantity))
        # Check if it's a whole number (no fractional part)
        if qty_dec % 1 != 0:
            return jsonify({"error": "Quantity must be a whole number"}), 400
        quantity = int(qty_dec)
    except Exception:
        return jsonify({"error": "Invalid quantity"}), 400

    # 🔒 Enforce minimum and maximum tickets per order
    if quantity < 1:
        return jsonify({"error": "Quantity must be at least 1"}), 400

    if quantity > MAX_TICKETS_PER_ORDER:
        return jsonify({
            "error": f"Maximum {MAX_TICKETS_PER_ORDER} tickets allowed per order"
        }), 400

    # --- SECURITY FIX: Validate product and price against known values ---
    ALLOWED_PRODUCTS = {
        "DJI Mini 2 drone": Decimal("6.00"),
        "Beachcroft Patio set": Decimal("6.00"),
        "Coolster 3125CX-2": Decimal("10.00"),
        "Balaclava": Decimal("3.00"),
        "Western boots": Decimal("4.00"),
        "Club Car DS": Decimal("10.00"),
        "G1 VR Headset": Decimal("5.00"),
        "Yamaha Jetski": Decimal("8.00"),
        "4D-V15 Drone": Decimal("5.00"),
        "Surfboard": Decimal("4.00"),
        "Treadmill Proform": Decimal("8.00"),
        "Mesa Lite e-bikes": Decimal("7.00"),
        "Sightmark wraith scope.": Decimal("5.00"),
        "Kitchen Island": Decimal("5.00"),
        "Broyhill Patio Set": Decimal("5.00"),
        "Light Grey Set": Decimal("6.00"),
        "Power Recliner Set": Decimal("6.00"),
        "Modern Sofa": Decimal("4.00"),
        "LG Washer & Dryer": Decimal("5.00"),
        "Fishing Tackle & Equipment": Decimal("6.00"),
        "Inflatable Hot Tub": Decimal("4.00"),
        "Baby Bassinet": Decimal("6.00"),
        "Irest massage seat": Decimal("6.00"),
    }

    product_title = data.get("product_title") or data.get("product")
    if not product_title:
        return jsonify({"error": "Missing product title"}), 400
    product_title = product_title.strip()
    if product_title not in ALLOWED_PRODUCTS:
        return jsonify({"error": "Invalid product"}), 400

    correct_price = ALLOWED_PRODUCTS[product_title]

    raw_price = data.get("ticket_price")
    if raw_price is None:
        return jsonify({"error": "Missing ticket price"}), 400

    # Sanitize price string (remove any non‑numeric characters except dot)
    price_str = re.sub(r'[^\d.]', '', str(raw_price))
    # Handle cases with multiple dots – keep only the first dot
    if price_str.count('.') > 1:
        parts = price_str.split('.')
        price_str = parts[0] + '.' + ''.join(parts[1:])
    try:
        provided_price = Decimal(price_str).quantize(Decimal("0.01"))
    except:
        return jsonify({"error": "Invalid ticket price"}), 400

    if provided_price != correct_price:
        return jsonify({"error": "Ticket price mismatch"}), 400

    ticket_price = provided_price   # use the validated price
    # --- end of security fix ---

    email = data.get("email", "").strip().lower()

    if len(email) > 254:
        return jsonify({"error": "Email too long"}), 400

    if not email:
        return jsonify({"error": "Missing email"}), 400

    # Validate email format
    email_regex = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
    if not email_regex.match(email):
        return jsonify({"error": "Invalid email format"}), 400

    order_id = data.get("order_id")

    if not validate_order_id(order_id):
        return jsonify({"error": "Invalid order ID"}), 400

    if not order_id:
        return jsonify({"error": "Missing PayPal order ID"}), 400

    expected_amount = (ticket_price * Decimal(quantity)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    ok, err = verify_paypal_order(order_id, expected_amount)

    if not ok:
        return jsonify({"error": err}), 403

    if len(full_name) > MAX_NAME_LENGTH:
        full_name = full_name[:MAX_NAME_LENGTH] + "…"

    if not full_name:
        return jsonify({"error": "Missing required field: name"}), 400

    # Start with the original quantity
    effective_quantity = quantity

    # 1️⃣ Apply holiday promotion first (BBuy 5, Get 2 Free)
    # always uses server UTC time
    holiday_active = is_holiday_active()

    if holiday_active and quantity == 5:
        effective_quantity = 7
        print(f"🎁 Holiday promotion applied: {quantity} -> {effective_quantity} tickets")

    # 2️⃣ Then apply free ticket credit (if user has any)
    if use_free_ticket:
        with referrals_lock:
            referrals = load_referrals()
            user_credits = 0
            for info in referrals.values():
                if info.get("referrer_email") == email:
                    user_credits = info.get("credits", 0)
                    break
            if user_credits > 0:
                effective_quantity = effective_quantity + 1
                # Decrement the credit
                for code, info in referrals.items():
                    if info.get("referrer_email") == email:
                        info["credits"] = user_credits - 1
                        break
                save_referrals(referrals)
                print(f"🎟️ Used 1 free ticket credit, new effective quantity: {effective_quantity}")
            else:
                print(f"⚠️ Free ticket requested but no credits available for {email}")

    # Referral:apply reward if referral code provided and quantity >= 
    if referral_code and quantity >= 3:
        with referrals_lock:
            referrals = load_referrals()
            if referral_code in referrals:
                referrer_info = referrals[referral_code]
                # Avoid self referral
                if referrer_info["referrer_email"] != email:
                    if email not in referrer_info.get("referred_emails", []):
                        referrer_info["credits"] = referrer_info.get("credits", 0) + 1
                        referrer_info.setdefault("referred_emails", []).append(email)
                        save_referrals(referrals)
                        print(f"🎁 Referral applied: {referral_code} earned a credit")

    # ---- Assign CMST number for this email ----
    try:
        cmst_no = get_or_assign_cmst(email)
    except Exception as e:
        print(f"❌ CMST assignment failed: {e}")
        return jsonify({"error": "CMST assignment failed"}), 500

    try:
        if effective_quantity == 1:
            ticket_no = generate_ticket_no()

            # 🔐 Generate a unique cryptographically secure
            # verification token for this ticket.
            verification_token = generate_ticket_verification_token()
            # 🌐 Public website URL encoded into the QR code.
            verification_url = build_ticket_verification_url(
                verification_token
            )

            # 💾 Create the authoritative backend verification
            # BEFORE generating the physical ticket PDF.
            create_ticket_verification_record(
                token=verification_token,
                ticket_no=ticket_no,
                full_name=full_name,
                email=email,
                product_title=product_title,
                ticket_price=ticket_price,
                cmst_no=cmst_no,
                order_id=order_id,
            )

            pdf = generate_ticket_with_placeholders(
                full_name,
                ticket_no,
                EVENT_DATE,
                str(ticket_price),
                event_place,
                EVENT_TIME,
                product_title,
                cmst_no,
                verification_url,
            )

            order_dir = os.path.join(TICKET_STORAGE_DIR, order_id)
            os.makedirs(order_dir, exist_ok=True)

            file_name = f"RaffleTicket_{ticket_no}.pdf"

            order_dir = os.path.join(TICKET_STORAGE_DIR, order_id)
            os.makedirs(order_dir, exist_ok=True)

            file_name = f"RaffleTicket_{ticket_no}.pdf"

            order_dir = os.path.join(TICKET_STORAGE_DIR, order_id)
            os.makedirs(order_dir, exist_ok=True)

            file_name = f"RaffleTicket_{ticket_no}.pdf"
            file_path = os.path.join(order_dir, file_name)

            pdf_bytes = pdf.getvalue()

            with open(file_path, "wb") as f:
                f.write(pdf_bytes)

            # ☁️ Persist single ticket to R2
            upload_pdf_to_r2(order_id, file_name, pdf_bytes)

            # 🚀 Cache for fast download
            GENERATED_FILES[order_id] = {
                "filename": file_name,
                "mimetype": "application/pdf",
                "data": pdf_bytes,
            }

            if len(GENERATED_FILES) > MAX_CACHE_ITEMS:
                GENERATED_FILES.pop(next(iter(GENERATED_FILES)))

            register_order(
                order_id=order_id,
                email=email,
                files=[file_name],
                product=product_title,
                quantity=1,
                ticket_numbers=[ticket_no],
                user_local_time=user_local_now,
            )

            record_ticket_sale(1)

            # Log to Google Sheets
            log_to_google_sheet_with_retry(
                full_name=full_name,
                email=email,
                ticket_numbers=[ticket_no],
                amount=expected_amount,
                order_id=order_id,
                local_time=user_local_now,
            )

            return jsonify({"status": "tickets_generated", "order_id": order_id}), 200

        ticket_files = []
        ticket_numbers = []

        order_dir = os.path.join(TICKET_STORAGE_DIR, order_id)
        os.makedirs(order_dir, exist_ok=True)

        zip_stream = io.BytesIO()
        with zipfile.ZipFile(
            zip_stream, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
        ) as zf:
            for _ in range(effective_quantity):
                ticket_no = generate_ticket_no()
                ticket_numbers.append(ticket_no)

                # 🔐 Generate a unique cryptographically secure
                # verification token for this individual ticket.
                verification_token = generate_ticket_verification_token()

                # 🌐 Public website URL encoded into this ticket's QR.
                verification_url = build_ticket_verification_url(
                    verification_token
                )

                # 💾 Create this ticket's authoritative verification record.
                create_ticket_verification_record(
                    token=verification_token,
                    ticket_no=ticket_no,
                    full_name=full_name,
                    email=email,
                    product_title=product_title,
                    ticket_price=ticket_price,
                    cmst_no=cmst_no,
                    order_id=order_id,
                )

                pdf = generate_ticket_with_placeholders(
                    full_name,
                    ticket_no,
                    EVENT_DATE,
                    str(ticket_price),
                    event_place,
                    EVENT_TIME,
                    product_title,
                    cmst_no,
                    verification_url,
                )

                name = f"RaffleTicket_{ticket_no}.pdf"
                zf.writestr(name, pdf.getvalue())
                ticket_files.append(name)

        zip_stream.seek(0)
        # 🔹 ADD Step3 R

        zip_bytes = zip_stream.getvalue()
        upload_zip_to_r2(order_id, zip_bytes)

        zip_stream.seek(0)

        zip_path = os.path.join(order_dir, f"RaffleTickets_{order_id}.zip")
        with open(zip_path, "wb") as f:
            f.write(zip_stream.getvalue())

        register_order(
            order_id=order_id,
            email=email,
            files=[os.path.basename(zip_path)],
            product=product_title,
            quantity=effective_quantity,
            ticket_numbers=ticket_numbers,
            user_local_time=user_local_now,
        )

        try:
            record_ticket_sale(effective_quantity)
        except ValueError:
            return jsonify({"error": "Tickets sold out"}), 409

        # Log to Google Sheets
        log_to_google_sheet_with_retry(
            full_name=full_name,
            email=email,
            ticket_numbers=ticket_numbers,
            amount=expected_amount,
            order_id=order_id,
            local_time=user_local_now, 
        )

        # cleanup_old_orders()

        return jsonify({"status": "tickets_generated", "order_id": order_id}), 200

    except Exception as e:
        print("❌ Ticket generation error: ", e)
        return jsonify({"error": "Ticket generation failed"}), 500


# --------------------------------------------------
# MAIN
# --------------------------------------------------

@app.route("/download_ticket", methods=["POST"])
@limiter.limit("10 per minute")
def download_ticket():
    ok, err = verify_request_nonce(request)
    if not ok:
        return jsonify({"error": err}), 403

    data = request.get_json(force=True)
    order_id = data.get("order_id")

    if not validate_order_id(order_id):
        return jsonify({"error": "Invalid order ID"}), 400

    if not order_id:
        return jsonify({"error": "Missing order_id"}), 400

    return send_ticket_file(order_id, enforce_limit=False)

@app.route("/my_tickets", methods=["POST"])
@limiter.limit("10 per minute")
def my_tickets():
    ok, err = verify_request_nonce(request)
    if not ok:
        return jsonify({"error": err}), 403

    data = request.get_json(force=True)
    email = data.get("email", "").strip().lower()

    if not email:
        return jsonify({"error": "Missing email"}), 400

    index = load_orders_index()
    email_index = load_email_index()

    order_ids = email_index.get(email, [])

    orders = []

    for oid in order_ids:
        meta = index["orders"].get(oid)
        if not meta:
            continue

        orders.append(
            {
                "order_id": oid,
                "product_name": meta.get("product"),
                "quantity": meta.get("quantity"),
                "tickets": meta.get("tickets", []),
                "date": meta.get("created_at"),
                "user_local_time": meta.get("user_local_time"),
            }
        )

    return jsonify({"orders": orders}), 200

@app.route("/redownload_ticket", methods=["POST"])
@limiter.limit("10 per minute")
def redownload_ticket():
    ok, err = verify_request_nonce(request)
    if not ok:
        return jsonify({"error": err}), 403

    data = request.get_json(force=True)
    order_id = data.get("order_id")

    if not validate_order_id(order_id):
        return jsonify({"error": "Invalid order ID"}), 400

    if not order_id:
        return jsonify({"error": "Missing order_id"}), 400

    return send_ticket_file(order_id, enforce_limit=True)

# --------------------------------------------------
# RECENT WINNERS (Announcement Feature)
# --------------------------------------------------
RECENT_WINNERS_FILE = os.path.join(BASE_DIR, "recent_winners.json")
SHOW_RECENT_WINNERS = os.environ.get("SHOW_RECENT_WINNERS", "false").lower() == "false"

def load_recent_winners():
    """Loads recent winners from local JSON file."""
    if not os.path.exists(RECENT_WINNERS_FILE):
        # Return a default list (or empty) if file doesn't exist
        return [
            {
                "name": "Melissa D.",
                "state": "Dodges Ferry TAS",
                "country": "Australia",
                "prize": "Larchmont Dining Set",
                "cash_out": False,
                "date_claimed":"30 July 2026",
                "ticket_no": "GWS-240715B9"
            },
            {
                "name": "Liam J..",
                "state": "Albans VIC",
                "country": "Australia",
                "prize": "Ballinasloe 3-piece Sectional",
                "cash_out": False,
                "date_claimed":"30 July 2026",
                "ticket_no": "GWS-37377A9E"
            },
            {
                "name": "Alexander G.",
                "state": "Dodges Ferry TAS",
                "country": "Australia",
                "prize": "800",
                "cash_out": True,
                "date_claimed":"1 August 2026",
                "ticket_no": "GWS-74BD35F1"
            },
            {
                "name": "Mae W.",
                "state": "Elanora QLD",
                "country": "Australia",
                "prize": "Trek Marlin 5 Gen 2",
                "cash_out": False,
                "date_claimed":"30 July 2026",
                "ticket_no": "GWS-8B43622A"
            },
            {
                "name": "Joshua T.",
                "state": "Applecross WA",
                "country": "Australia",
                "prize": "Venom X21(Dongfang DF50SRT)",
                "cash_out": False,
                "date_claimed":"31 July 2026",
                "ticket_no": "GWS-C2C2621C"
            },
        ]
    try:
        with open(RECENT_WINNERS_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        print("Failed to load recent_winners.json:", e)
        return []

def save_recent_winners(winners):
    """Saves recent winners to local JSON file."""
    try:
        with open(RECENT_WINNERS_FILE, "w") as f:
            json.dump(winners, f, indent=2)
    except Exception as e:
        print("Failed to save recent_winners.json:", e)

@app.route("/recent_winners", methods=["GET"])
@limiter.limit("10 per minute")
def recent_winners():
    """
    Returns list of recent winners indicating whether to show them.
    """
    if not SHOW_RECENT_WINNERS:
        return jsonify({"show": False, "winners": []}), 200

    winners = load_recent_winners()
    # Optionally filter only winners with a specific date, etc.
    return jsonify({"show": True, "winners": winners}), 200

@app.route("/check_ticket_status", methods=["POST"])
@limiter.limit("10 per minute")
def check_ticket_status():
    """
    Authoritative ticket status check.

    The backend is the single source of truth. It looks up the submitted
    ticket number against the RecentWinners list.

    Outcomes:
      • CLAIMED       → ticket found in RecentWinners
                        (already won in a previous draw → already claimed)
      • NOT_SELECTED  → ticket not found in RecentWinners
    """
    data = request.get_json(force=True)
    ticket_no = (data.get("ticket_no") or "").strip().upper()

    if not ticket_no:
        return jsonify({"error": "Missing ticket_no"}), 400

    # Ticket format: GWS-XXXXXXXX (8 alphanumeric, case-insensitive)
    if not re.fullmatch(r"GWS-[A-Z0-9]{8}", ticket_no):
        return jsonify({"error": "Invalid ticket number format"}), 400

    winners = load_recent_winners()

    for w in winners:
        w_ticket = (w.get("ticket_no") or "").strip().upper()
        if w_ticket == ticket_no:
            return jsonify({
                "status": "CLAIMED",
                "winner": {
                    "ticket_no":     w.get("ticket_no"),
                    "name":          w.get("name"),
                    "prize":         w.get("prize"),
                    "cash_out":      w.get("cash_out", False),
                    "date_claimed":  w.get("date_claimed") or w.get("date") or None,
                    "country":       w.get("country"),
                    "state":         w.get("state"),
                }
            }), 200

    return jsonify({"status": "NOT_SELECTED"}), 200

@app.route("/referral/generate", methods=["POST"])
@limiter.limit("10 per minute")
def generate_referral_code():
    data = request.get_json(force=True)
    email = data.get("email", "").strip().lower()
    if not email:
        return jsonify({"error": "Email required"}), 400

    with referrals_lock:
        referrals = load_referrals()
        # Check if email already has a code
        for code, info in referrals.items():
            if info.get("referrer_email") == email:
                return jsonify({"code": code, "credits": info.get("credits", 0)}), 200

        # Generate new code (first 8 chars of email hash)
        code = hashlib.md5(email.encode()).hexdigest()[:8].upper()
        referrals[code] = {
            "referrer_email": email,
            "credits": 0,
            "referred_emails": []
        }
        save_referrals(referrals)
        return jsonify({"code": code, "credits": 0}), 200

@app.route("/referral/rewards", methods=["POST"])
@limiter.limit("10 per minute")
def get_referral_rewards():
    data = request.get_json(force=True)
    email = data.get("email", "").strip().lower()
    if not email:
        return jsonify({"error": "Email required"}), 400

    with referrals_lock:
        referrals = load_referrals()
        credits = 0
        for info in referrals.values():
            if info.get("referrer_email") == email:
                credits = info.get("credits", 0)
                break
        return jsonify({"credits": credits}), 200

@app.route("/address_toggles", methods=["GET"])
@limiter.limit("10 per minute")
def address_toggles():
    """
    Returns toggle status for each country's address locations.
    Controlled via environment variables (default: true).
    """
    toggles = {
        "usa": os.environ.get("ADDRESS_TOGGLE_USA", "true").lower() == "false",
        "canada": os.environ.get("ADDRESS_TOGGLE_CANADA", "true").lower() == "false",
        "australia": os.environ.get("ADDRESS_TOGGLE_AUSTRALIA", "true").lower() == "true",
        "newZealand": os.environ.get("ADDRESS_TOGGLE_NEWZEALAND", "true").lower() == "false",
    }
    return jsonify(toggles), 200

@app.route("/winners_detail_toggle", methods=["GET"])
@limiter.limit("10 per minute")
def winners_detail_toggle():
    """
    Returns a boolean indicating whether to show the WinnersDetail component.
    Default: false. Set environment variable SHOW_WINNERS_DETAIL=true to enable.
    """
    show = os.environ.get("SHOW_WINNERS_DETAIL", "false").lower() == "true"
    return jsonify({"show": show}), 200

@app.route("/bootstrap", methods=["GET"])
@limiter.limit("10 per minute")
def bootstrap():
    """
    Combined endpoint that returns:
      • ticket_state
      • winners_detail_toggle
      • recent_winners
    in a single response. This reduces the number of round-trips the
    frontend must make during initial page load.

    Reuses the same 10-second cache as /ticket_state so it does not
    double the ticket_state computation cost.
    """
    now = time()

    # --- ticket_state (same logic + cache as /ticket_state) ---
    if (
        _ticket_state_cache["data"]
        and now - _ticket_state_cache["timestamp"] < CACHE_EXPIRY
    ):
        cached_resp, _ = _ticket_state_cache["data"]
        ticket_payload = cached_resp.get_json()
        ticket_payload["cache"] = "HIT"
    else:
        state = apply_daily_decay_if_needed()
        today = datetime.utcnow().strftime("%Y-%m-%d")

        remaining = state.get("remaining")
        tickets_sold_ui = None
        if isinstance(remaining, int):
            tickets_sold_ui = max(INITIAL_TICKETS - remaining, 0)

        ticket_payload = {
            "remaining": remaining,
            "tickets_sold": tickets_sold_ui,
            "last_calc_date": state.get("last_calc_date"),
            "initialized": state.get("initialized", False),
            "today": today,
            "cache": "MISS",
        }

        # Refresh the shared cache so /ticket_state benefits too.
        _ticket_state_cache["data"] = (jsonify(ticket_payload), 200)
        _ticket_state_cache["timestamp"] = now

    # --- winners_detail_toggle ---
    winners_toggle_payload = {
        "show": os.environ.get("SHOW_WINNERS_DETAIL", "false").lower() == "true"
    }

    # --- recent_winners ---
    if not SHOW_RECENT_WINNERS:
        recent_winners_payload = {"show": False, "winners": []}
    else:
        recent_winners_payload = {
            "show": True,
            "winners": load_recent_winners()
        }

    response = jsonify({
        "ticket_state": ticket_payload,
        "winners_toggle": winners_toggle_payload,
        "recent_winners": recent_winners_payload,
    })

    # Let Vercel's edge cache the bootstrap response for 10 s,
    # then serve stale for up to 60 s while revalidating in the
    # background. Most page loads will hit Vercel's edge, NOT Render.
    response.headers["Cache-Control"] = (
        "public, s-maxage=10, stale-while-revalidate=60"
    )

    return response, 200

# --------------------------------------------------
# SKU GENERATION (Deterministic per product)
# --------------------------------------------------
def generate_sku(product_title):
    """
    Generate a deterministic 13‑character alphanumeric SKU for a product.
    Uses SHA‑256 of the product title + a secret salt, then converts to base36
    and takes the first 13 characters.
    """
    secret_salt = os.environ.get("SKU_SALT", "goodwillstores_2026_salt")
    hash_input = f"{product_title}|{secret_salt}".encode()
    hash_digest = hashlib.sha256(hash_input).hexdigest()
    # Convert hex digest to a large integer
    hash_int = int(hash_digest, 16)
    # Convert to base36 (0-9A-Z)
    chars = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    result = []
    if hash_int == 0:
        return "GWS" + "0" * 13
    while hash_int > 0:
        hash_int, rem = divmod(hash_int, 36)
        result.append(chars[rem])
    sku_base = ''.join(reversed(result))
    # Ensure at least 13 characters, pad with leading '0' if necessary
    sku = "GWS" + (sku_base[:13]).zfill(13)
    return sku

@app.route("/get_sku", methods=["POST"])
@limiter.limit("10 per minute")
def get_sku():
    """
    Returns a deterministic SKU for a given product title.
    Expects JSON: { "product_title": "Product Name" }
    """
    data = request.get_json(force=True)
    product_title = data.get("product_title", "").strip()
    if not product_title:
        return jsonify({"error": "Missing product_title"}), 400
    sku = generate_sku(product_title)
    return jsonify({"sku": sku}), 200

# --------------------------------------------------
# PUBLIC TICKET VERIFICATION
# --------------------------------------------------

# Number of hours after the raffle first sells out, after which
# every issued ticket is permanently marked EXPIRED.
TICKET_EXPIRY_HOURS_AFTER_SOLD_OUT = 48


@app.route("/verify_ticket/<token>", methods=["GET"])
@limiter.limit("20 per minute")
def verify_ticket(token):
    """
    Public endpoint used by the /verify-ticket/<token> frontend page.
    Returns the authoritative verification record for the given token.

    The token is a URL-safe random string (see generate_ticket_verification_token).
    It contains no personally-identifying information.

    Expiry rule:
        A ticket becomes EXPIRED exactly 48 hours after the raffle
        first reached zero remaining tickets (ticket_state["sold_out_at"]).
        Once a record has been marked EXPIRED it is NEVER reverted to
        ACTIVE or any other status.
    """
    # Basic token format validation (A-Z, a-z, 0-9, -, _)
    if not token or not re.fullmatch(r"[A-Za-z0-9_-]{20,64}", token):
        return jsonify({
            "status": "INVALID",
            "message": "This verification link is not valid."
        }), 400

    record = load_ticket_verification_record(token)

    if not record:
        return jsonify({
            "status": "NOT_FOUND",
            "message": "We could not find a ticket for this verification link."
        }), 404

    # ----------------------------------------------------------
    # EXPIRY CHECK
    # ----------------------------------------------------------
    # Only escalate ACTIVE → EXPIRED.
    # Never revert EXPIRED back to any other status.
    # ----------------------------------------------------------
    if record.get("status") != "EXPIRED":
        try:
            ticket_state = load_ticket_state() or {}
        except Exception:
            ticket_state = {}

        sold_out_at_str = ticket_state.get("sold_out_at")

        if sold_out_at_str:
            try:
                sold_out_at = datetime.fromisoformat(
                    sold_out_at_str.replace("Z", "+00:00")
                ).replace(tzinfo=None)

                expiry_time = sold_out_at + timedelta(
                    hours=TICKET_EXPIRY_HOURS_AFTER_SOLD_OUT
                )

                if datetime.utcnow() >= expiry_time:
                    # Permanently mark this ticket EXPIRED.
                    record["status"] = "EXPIRED"
                    record["expired_at"] = (
                        datetime.utcnow().isoformat() + "Z"
                    )
                    save_ticket_verification_record(token, record)
                    print(
                        f"⌛ Ticket {record.get('ticket_no')} marked EXPIRED "
                        f"(raffle sold out at {sold_out_at_str})"
                    )
            except Exception as e:
                print(f"⚠️ Expiry check failed for token {token}: {e}")

    # Return only what the verification page needs (no full email for privacy).
    return jsonify({
        "status": "VALID",
        "ticket_no": record.get("ticket_no"),
        "full_name": record.get("full_name"),
        "product": record.get("product"),
        "cmst_no": record.get("cmst_no"),
        "created_at": record.get("created_at"),
        "raffle_id": record.get("raffle_id"),
        "ticket_status": record.get("status", "ACTIVE"),
        "expired_at": record.get("expired_at"),
    }), 200


# --------------------------------------------------
# ONE-TIME STARTUP CLEANUP (SAFE)
# --------------------------------------------------
try:
    perform_raffle_reset_if_requested()  # 🔁 campaign reset
    perform_cmst_reset_if_requested() # 🔁 CMST reset
    cleanup_old_orders()
    cleanup_old_r2_objects()
except Exception as e:
    print("Startup cleanup skipped:", e)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
