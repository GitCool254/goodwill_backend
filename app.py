from flask import Flask, request, send_file, jsonify, Response
from flask_cors import CORS
from decimal import Decimal, ROUND_HALF_UP
import fitz  # PyMuPDF
import io
import random
import zipfile
import os
import hmac
import hashlib
import requests
import json
from datetime import datetime
from werkzeug.wsgi import FileWrapper
import boto3
from botocore.client import Config
import math
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from time import time

# --------------------------------------------------
# APP SETUP
# --------------------------------------------------

app = Flask(__name__)

# Rate limiter (per-IP)
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[]  # no global limits
)

limiter.init_app(app)

app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

CORS(
    app,
    resources={
        # ----------------------------------
        # Ticket generation & downloads
        # ----------------------------------
        r"/generate_ticket": {
            "origins": [
                "https://goodwill-raffle-store-raffle-store.onrender.com",
                "https://goodwillrafflestore.onrender.com",
                "https://goodwillrafflestores.vercel.app",
            ]
        },
        r"/download_ticket": {
            "origins": [
                "https://goodwill-raffle-store-raffle-store.onrender.com",
                "https://goodwillrafflestore.onrender.com",
                "https://goodwillrafflestores.vercel.app",
            ],
            "expose_headers": ["Content-Disposition"],
        },
        r"/redownload_ticket": {
            "origins": [
                "https://goodwill-raffle-store-raffle-store.onrender.com",
                "https://goodwillrafflestore.onrender.com",
                "https://goodwillrafflestores.vercel.app",
            ],
            "expose_headers": ["Content-Disposition"],
        },
        r"/my_tickets": {
            "origins": [
                "https://goodwill-raffle-store-raffle-store.onrender.com",
                "https://goodwillrafflestore.onrender.com",
                "https://goodwillrafflestores.vercel.app",
            ]
        },

        # ----------------------------------
        # ✅ Ticket state & syncing (FIX)
        # ----------------------------------
        r"/ticket_state": {
            "origins": [
                "https://goodwill-raffle-store-raffle-store.onrender.com",
                "https://goodwillrafflestore.onrender.com",
                "https://goodwillrafflestores.vercel.app",
            ]
        },
        r"/tickets_sold": {
            "origins": [
                "https://goodwill-raffle-store-raffle-store.onrender.com",
                "https://goodwillrafflestore.onrender.com",
                "https://goodwillrafflestores.vercel.app",
            ]
        },

        r"/sign_payload": {
            "origins": [
                "https://goodwill-raffle-store-raffle-store.onrender.com",
                "https://goodwillrafflestore.onrender.com",
                "https://goodwillrafflestores.vercel.app",
            ]
        },
    },
)

# --------------------------------------------------
# PATHS
# --------------------------------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_PATH = os.path.join(BASE_DIR, "Raffle_Ticket_TemplateN.pdf")


# --------------------------------------------------
# TICKET SALES LEDGER (ADDITIVE – DO NOT MODIFY)
# --------------------------------------------------

SALES_FILE = os.path.join(BASE_DIR, "ticket_sales.json")
SALES_KEY = "state/ticket_sales.json"

def read_sales():
    """
    Returns total tickets sold (persistent).
    R2 authoritative, local fallback.
    """

    # 1️⃣ R2 primary
    if r2_client:
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

def load_ticket_state():
    """
    Persistent authoritative remaining ticket state.
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

    return {
        "remaining": None,
        "last_calc_date": None,
        "initialized": False
    }

def save_ticket_state(state):
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


# --------------------------------------------------
# DAILY TICKET DECAY (AUTHORITATIVE)
# --------------------------------------------------

RAFFLE_START_DATE = "2026-02-12"
SIMULATED_START_DATE = "2026-02-15"
INITIAL_TICKETS = 55
DEDICATED_DAYS = 10
RAFFLE_ID = "goodwill-raffle-2026-round1"

def seeded_random(seed: int) -> float:
    x = math.sin(seed) * 10000
    return x - math.floor(x)

def compute_daily_decay(days_passed: int) -> int:
    """
    Deterministic daily decay.
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
    seed_str = f"{RAFFLE_ID}:{days_passed}"
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
    state = load_ticket_state()
    today = datetime.utcnow().strftime("%Y-%m-%d")

    # Initialize or reconcile state (NEVER allow remaining to increase)
    sold = read_sales()
    max_allowed = max(INITIAL_TICKETS - sold, 0)

    if not state.get("initialized"):
        state["remaining"] = max_allowed
        state["initialized"] = True
        state["last_calc_date"] = today
        save_ticket_state(state)
        return state

    # 🔒 HARD GUARD: never allow remaining to go UP
    if state.get("remaining") is None or state["remaining"] > max_allowed:
        state["remaining"] = max_allowed
        save_ticket_state(state)

    # Already decayed today → do nothing
    if state.get("last_calc_date") == today:
        return state

    # Stop if sold out
    if int(state.get("remaining", 0)) <= 0:
        state["remaining"] = 0
        state["last_calc_date"] = today
        save_ticket_state(state)
        return state

    start_date_str = SIMULATED_START_DATE or RAFFLE_START_DATE
    start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
    days_passed = max((datetime.utcnow() - start_date).days, 0)

    total_decay = compute_total_decay(days_passed)
    sold = read_sales()

    authoritative_remaining = max(
        INITIAL_TICKETS - total_decay - sold,
        0
    )

    state["remaining"] = authoritative_remaining
    state["last_calc_date"] = today

    save_ticket_state(state)
    return state

# --------------------------------------------------
# PERSISTENT TICKET STORAGE
# --------------------------------------------------

TICKET_STORAGE_DIR = os.environ.get(
    "TICKET_STORAGE_DIR", os.path.join(BASE_DIR, "storage", "tickets")
)

os.makedirs(TICKET_STORAGE_DIR, exist_ok=True)

MAX_REDOWNLOADS = 3

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

MAX_EXPAND_CHARS = 25
EXPAND_PADDING = 6

SECRET_KEY = os.environ.get("API_SIGN_SECRET")

if not SECRET_KEY:
    raise RuntimeError("API_SIGN_SECRET not set")

# --------------------------------------------------
# HELPERS
# --------------------------------------------------
ORDERS_INDEX_FILE = os.path.join(TICKET_STORAGE_DIR, "orders.json")
ORDERS_INDEX_KEY = "indexes/orders.json"
EMAIL_INDEX_KEY = "indexes/email_orders.json"
USED_ORDERS_KEY = "indexes/used_orders.json"

# ===============================
# Cloudflare R2 (Storage Only) Step 1R
# ===============================

R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY")
R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME")

r2_client = None

if all([R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME]):
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
    # 1️⃣ Update persistent sales ledger
    current_sold = read_sales()
    new_total = current_sold + quantity
    write_sales(new_total)

    # 2️⃣ Load authoritative ticket state
    state = load_ticket_state()

    # 3️⃣ Initialize state if first sale ever
    if not state.get("initialized"):
        state["remaining"] = max(INITIAL_TICKETS - current_sold, 0)
        state["initialized"] = True

    remaining = int(state.get("remaining", 0))

    # 4️⃣ Hard stop if not enough tickets
    if remaining < quantity:
        raise ValueError("Not enough tickets remaining")

    # 5️⃣ 🔥 Burn tickets immediately (THIS IS THE HACK)
    state["remaining"] = remaining - quantity

    # 6️⃣ 🔒 Lock today so decay CANNOT run again today
    state["last_calc_date"] = datetime.utcnow().strftime("%Y-%m-%d")

    # 7️⃣ Persist state
    save_ticket_state(state)

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
            ContentType="application/zip"
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
            ContentType="application/pdf"
        )
    except Exception as e:
        print("R2 PDF upload failed:", e)

def fetch_zip_from_r2(order_id):
    if not r2_client:
        return None

    try:
        obj = r2_client.get_object(
            Bucket=R2_BUCKET_NAME,
            Key=f"tickets/{order_id}.zip"
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
        pages = paginator.paginate(
            Bucket=R2_BUCKET_NAME,
            Prefix="tickets/"
        )

        for page in pages:
            for obj in page.get("Contents", []):
                last_modified = obj["LastModified"].timestamp()
                if last_modified < cutoff_ts:
                    try:
                        r2_client.delete_object(
                            Bucket=R2_BUCKET_NAME,
                            Key=obj["Key"]
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

def register_order(order_id, email, files, product, quantity, ticket_numbers):
    index = load_orders_index()

    index["orders"][order_id] = {
        "email": email,
        "files": files,
        "product": product,
        "quantity": quantity,
        "tickets": ticket_numbers,  # list of ticket numbers
        "created_at": datetime.utcnow().isoformat() + "Z",
    }

    save_orders_index(index)

    # 🔥 Update email lookup index
    email_index = load_email_index()

    if email not in email_index:
        email_index[email] = []

    if order_id not in email_index[email]:
        email_index[email].append(order_id)

    save_email_index(email_index)

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

def verify_signature(payload: str, signature: str) -> bool:
    expected = hmac.new(
        SECRET_KEY.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(expected, signature)

def verify_request_hmac(req):
    signature = req.headers.get("X-Signature") or req.headers.get("HTTP_X_SIGNATURE")
    timestamp = req.headers.get("X-Timestamp") or req.headers.get("HTTP_X_TIMESTAMP")

    if not signature or not timestamp:
        return False, "Missing signature headers"

    try:
        ts = int(timestamp)
        now = int(datetime.utcnow().timestamp())
        if abs(now - ts) > 300:
            return False, "Request expired"
    except Exception:
        return False, "Invalid timestamp"

    # --- FIX: Use JSON parse + canonical dump instead of raw body ---
    try:
        data = req.get_json(force=True) or {}
    except Exception:
        return False, "Invalid JSON payload"

    payload = f"{timestamp}.{json.dumps(data, separators=(',', ':'))}"

    if not verify_signature(payload, signature):
        return False, "Invalid signature"

    return True, None

PAYPAL_CLIENT_ID = os.environ.get("PAYPAL_CLIENT_ID")
PAYPAL_SECRET = os.environ.get("PAYPAL_SECRET")
PAYPAL_MODE = os.environ.get("PAYPAL_MODE", "sandbox")

PAYPAL_API_BASE = (
    "https://api-m.paypal.com"
    if PAYPAL_MODE == "live"
    else "https://api-m.sandbox.paypal.com"
)

USED_ORDERS = load_used_orders()  # R2 primary, memory fallback

GENERATED_FILES = {}  # order_id -> { filename, mimetype, data }
MAX_CACHE_ITEMS = 100

def verify_paypal_order(order_id, expected_amount):
    auth = (PAYPAL_CLIENT_ID, PAYPAL_SECRET)

    r = requests.get(
        f"{PAYPAL_API_BASE}/v2/checkout/orders/{order_id}",
        auth=auth,
        headers={"Content-Type": "application/json"},
        timeout=10
    )

    print("🔎 PayPal URL:", f"{PAYPAL_API_BASE}/v2/checkout/orders/{order_id}")
    print("🔎 Status code:", r.status_code)
    print("🔎 Response:", r.text)

    if r.status_code != 200:
        return False, "PayPal verification failed"

    order = r.json()

    if order.get("status") != "COMPLETED":
        return False, "Payment not completed"

    paid_amount = Decimal(
        order["purchase_units"][0]["amount"]["value"]
    ).quantize(Decimal("0.01"))

    if paid_amount != expected_amount:
        return (
            False,
            f"Amount mismatch (paid {paid_amount}, expected {expected_amount})",
        )

    if order_id in USED_ORDERS:
        return False, "Order already used"

    USED_ORDERS.add(order_id)
    save_used_orders(USED_ORDERS)

    return True, None


def generate_ticket_no():
    return f"GWS-{random.randint(100000, 999999)}"


def generate_ticket_with_placeholders(
    full_name, ticket_no, event_date, ticket_price, event_place, event_time
):
    if not os.path.exists(TEMPLATE_PATH):
        raise FileNotFoundError(f"Template not found: {TEMPLATE_PATH}")

    doc = fitz.open(TEMPLATE_PATH)
    page = doc[0]
    page.wrap_contents()

    replacements = {
        "{{NAME}}": full_name,
        "{{TICKET-NO}}": ticket_no,
        "{{TICKET_PRICE}}": ticket_price,
        "{{EVENT_PLACE}}": event_place,
        "{{DATE}}": event_date,
        "{{TIME}}": event_time,
    }

    combined_placeholder = "{{DATE}} {{TIME}}"
    combined_value = f"{event_date} {event_time}".strip()

    for placeholder, value in replacements.items():

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
            fontsize = 12

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
            page.draw_rect(flex_rect, color=(1, 1, 1), fill=(1, 1, 1))

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
                    return jsonify({
                        "error": "TICKET_EXPIRED",
                        "message": "This ticket has expired and is no longer available for download."
                    }), 410

                zip_path = os.path.join(order_dir, f"RaffleTickets_{order_id}.zip")
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
                        return jsonify({
                            "error": "TICKET_EXPIRED",
                            "message": "This ticket has expired and is no longer available for download."
                        }), 410

                    with open(pdf_path, "wb") as f:
                        f.write(pdf_bytes)


            # (Frontend fix will ensure immediate download)
        else:
            return jsonify({
                "error": "TICKET_NOT_FOUND",
                "message": "We couldn’t find this ticket."
            }), 404

        # Basic integrity check (ZIP magic header)

    # 🔒 Enforce max re-downloads (PDF + ZIP, including cached)
    if enforce_limit:
        counter_path = os.path.join(order_dir, "downloads.txt")
        count = 0

        if os.path.exists(counter_path):
            with open(counter_path, "r") as f:
                count = int(f.read().strip() or 0)

        if count >= MAX_REDOWNLOADS:
            return jsonify({
                "error": "MAX_REDOWNLOADS_REACHED",
                "message": "You have reached the maximum number of allowed re-downloads."
            }), 403

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
            direct_passthrough=True,   # 🚀 ZERO-COPY
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

# --------------------------------------------------
# ROUTES
# --------------------------------------------------

# -------------------------
# Simple in-memory caching
# -------------------------
CACHE_EXPIRY = 10  # seconds

_ticket_state_cache = {
    "data": None,
    "timestamp": 0
}


@app.route("/sign_payload", methods=["POST"])
@limiter.limit("20 per minute")
def sign_payload():
    data = request.get_json(force=True)
    payload = json.dumps(data, separators=(',', ':'))  # canonical JSON
    timestamp = str(int(datetime.utcnow().timestamp()))
    message = f"{timestamp}.{payload}"
    signature = hmac.new(SECRET_KEY.encode(), message.encode(), hashlib.sha256).hexdigest()
    return jsonify({"signature": signature, "timestamp": timestamp})


@app.route("/ticket_state", methods=["GET"])
@limiter.limit("5 per 10 seconds")  # max 5 requests per IP every 10 seconds
def ticket_state():
    now = time()

    # -----------------------------
    # CACHE HIT
    # -----------------------------
    if _ticket_state_cache["data"] and now - _ticket_state_cache["timestamp"] < CACHE_EXPIRY:
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
        "cache": "MISS"
    }

    response = jsonify(payload), 200

    # update cache
    _ticket_state_cache["data"] = response
    _ticket_state_cache["timestamp"] = now

    return response

@app.route("/tickets_sold", methods=["GET"])
def tickets_sold():

    """
    Frontend reads how many tickets are already sold.
    """
    return jsonify({
        "total_sold": read_sales()
    }), 200

@app.route("/record_sale", methods=["POST"])
@limiter.limit("5 per minute")
def record_sale():
    ok, err = verify_request_hmac(request)
    if not ok:
        return jsonify({"error": err}), 403

    data = request.get_json(force=True)
    tickets_bought = int(data.get("tickets", 0))

    if tickets_bought <= 0:
        return jsonify({"error": "Invalid ticket count"}), 400

    # 🔒 Authoritative update (sales + remaining)
    try:
        record_ticket_sale(tickets_bought)
    except ValueError:
        return jsonify({"error": "Tickets sold out"}), 409

    return jsonify({
        "success": True,
        "tickets_bought": tickets_bought,
        "total_sold": read_sales()
    }), 200

@app.route("/", methods=["GET"])
def health_check():
    return jsonify({
        "status": "ok",
        "service": "raffle-api",
        "version": "1.0.0",
        "time": datetime.utcnow().isoformat() + "Z"
    }), 200


def order_already_generated(order_id):
    order_dir = os.path.join(TICKET_STORAGE_DIR, order_id)
    return os.path.exists(order_dir) and os.listdir(order_dir)


@app.route("/generate_ticket", methods=["POST"])
@limiter.limit("5 per minute")
def generate_ticket():
    ok, err = verify_request_hmac(request)
    if not ok:
        return jsonify({"error": err}), 403

    data = request.get_json(force=True)

    full_name = data.get("name", "").strip()
    event_place = data.get("event_place", EVENT_PLACE).strip()

    try:
        quantity = int(data.get("quantity", 1))
    except BaseException:
        return jsonify({"error": "Invalid quantity"}), 400

    ticket_price = data.get("ticket_price")

    try:
        ticket_price = Decimal(str(ticket_price)).quantize(Decimal("0.01"))
    except BaseException:
        return jsonify({"error": "Invalid ticket price"}), 400

    email = data.get("email", "").strip().lower()

    product_title = (
        data.get("product_title") or data.get("product") or "Raffle Ticket"
    )

    if not email:
        return jsonify({"error": "Missing email"}), 400

    order_id = data.get("order_id")

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

    try:
        if quantity == 1:
            ticket_no = generate_ticket_no()

            pdf = generate_ticket_with_placeholders(
                full_name,
                ticket_no,
                EVENT_DATE,
                str(ticket_price),
                event_place,
                EVENT_TIME,
            )

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
            )

            record_ticket_sale(1)

            # cleanup_old_orders()

            return (
                jsonify({"status": "tickets_generated", "order_id": order_id}),
                200,
            )

        ticket_files = []
        ticket_numbers = []

        order_dir = os.path.join(TICKET_STORAGE_DIR, order_id)
        os.makedirs(order_dir, exist_ok=True)

        zip_stream = io.BytesIO()
        with zipfile.ZipFile(
            zip_stream, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
        ) as zf:
            for _ in range(quantity):
                ticket_no = generate_ticket_no()
                ticket_numbers.append(ticket_no)
                pdf = generate_ticket_with_placeholders(
                    full_name,
                    ticket_no,
                    EVENT_DATE,
                    str(ticket_price),
                    event_place,
                    EVENT_TIME,
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
            quantity=quantity,
            ticket_numbers=ticket_numbers,
        )

        try:
            record_ticket_sale(quantity)
        except ValueError:
            return jsonify({"error": "Tickets sold out"}), 409

        # cleanup_old_orders()

        return (
            jsonify({"status": "tickets_generated", "order_id": order_id}),
            200,
        )

    except Exception as e:
        print("❌ Ticket generation error:", e)
        return jsonify({"error": "Ticket generation failed"}), 500

# --------------------------------------------------
# MAIN
# --------------------------------------------------


@app.route("/download_ticket", methods=["POST"])
@limiter.limit("10 per minute")
def download_ticket():
    ok, err = verify_request_hmac(request)
    if not ok:
        return jsonify({"error": err}), 403

    data = request.get_json(force=True)
    order_id = data.get("order_id")

    if not order_id:
        return jsonify({"error": "Missing order_id"}), 400

    return send_ticket_file(order_id, enforce_limit=False)


@app.route("/my_tickets", methods=["POST"])
@limiter.limit("10 per minute")
def my_tickets():
    ok, err = verify_request_hmac(request)
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

        orders.append({
            "order_id": oid,
            "product_name": meta.get("product"),
            "quantity": meta.get("quantity"),
            "tickets": meta.get("tickets", []),
            "date": meta.get("created_at"),
        })

    return jsonify({"orders": orders}), 200


@app.route("/redownload_ticket", methods=["POST"])
@limiter.limit("10 per minute")
def redownload_ticket():
    ok, err = verify_request_hmac(request)
    if not ok:
        return jsonify({"error": err}), 403

    data = request.get_json(force=True)
    order_id = data.get("order_id")

    if not order_id:
        return jsonify({"error": "Missing order_id"}), 400

    return send_ticket_file(order_id, enforce_limit=True)

# --------------------------------------------------
# ONE-TIME STARTUP CLEANUP (SAFE)
# --------------------------------------------------
try:
    cleanup_old_orders()
    cleanup_old_r2_objects()
except Exception as e:
    print("Startup cleanup skipped:", e)



if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
