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

# --------------------------------------------------
# APP SETUP
# --------------------------------------------------

app = Flask(__name__)
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
CORS(
    app,
    resources={
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
        r"/my_tickets": {  # ✅ ADD THIS
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

def read_sales():
    """
    Returns total tickets sold (persistent).
    Safe fallback to 0.
    """
    if not os.path.exists(SALES_FILE):
        return 0
    try:
        with open(SALES_FILE, "r") as f:
            return int(json.load(f).get("sold", 0))
    except Exception:
        return 0


def write_sales(total_sold):
    """
    Persist total tickets sold.
    """
    with open(SALES_FILE, "w") as f:
        json.dump(
            {
                "sold": int(total_sold),
                "updated_at": datetime.utcnow().isoformat() + "Z",
            },
            f,
            indent=2,
        )

# --------------------------------------------------
# AUTHORITATIVE TICKET STATE (DO NOT RESET HISTORY)
# --------------------------------------------------

STATE_FILE = os.path.join(BASE_DIR, "ticket_state.json")

def load_ticket_state():
    """
    Persistent authoritative remaining ticket state.
    Never touches sales history.
    """
    if not os.path.exists(STATE_FILE):
        return {
            "remaining": None,
            "last_calc_date": None
        }

    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {
            "remaining": None,
            "last_calc_date": None
        }

def save_ticket_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

# --------------------------------------------------
# PERSISTENT TICKET STORAGE
# --------------------------------------------------

TICKET_STORAGE_DIR = os.environ.get(
    "TICKET_STORAGE_DIR", os.path.join(BASE_DIR, "storage", "tickets")
)

os.makedirs(TICKET_STORAGE_DIR, exist_ok=True)

MAX_REDOWNLOADS = 2

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

SECRET_KEY = os.environ.get("API_SIGN_SECRET", "goodwill_5490_secret")

# --------------------------------------------------
# HELPERS
# --------------------------------------------------
ORDERS_INDEX_FILE = os.path.join(TICKET_STORAGE_DIR, "orders.json")

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

def record_ticket_sale(quantity: int):
    current_sold = read_sales()
    new_total = current_sold + quantity
    write_sales(new_total)

    # 🔥 Burn remaining tickets authoritatively
    state = load_ticket_state()
    if state.get("remaining") is not None:
        state["remaining"] = max(
            int(state["remaining"]) - quantity,
            0
        )
        save_ticket_state(state)

    print(f"📈 Tickets sold updated: +{quantity}, total {new_total}")


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

def load_orders_index():
    if not os.path.exists(ORDERS_INDEX_FILE):
        return {"orders": {}}
    with open(ORDERS_INDEX_FILE, "r") as f:
        return json.load(f)


def save_orders_index(data):
    with open(ORDERS_INDEX_FILE, "w") as f:
        json.dump(data, f, indent=2)


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

def cleanup_old_orders(days=7):
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
    """
    Enforces HMAC signature on JSON requests.
    Works behind proxies too.
    """
    # fallback to proxy-prefixed headers
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

    raw_body = req.get_data(as_text=True) or ""
    payload = f"{timestamp}.{raw_body}"

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

USED_ORDERS = set()  # in-memory lock (OK for now)

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

        # Attempt R2 recovery (ZIP orders only)
        zip_bytes = fetch_zip_from_r2(order_id)

        if not zip_bytes:
            return jsonify({"error": "Ticket not found"}), 404

        # Basic integrity check (ZIP magic header)
        if not zip_bytes.startswith(b"PK"):
            print("❌ R2 data is not a valid ZIP")
            return jsonify({"error": "Corrupt ticket archive"}), 500

        os.makedirs(order_dir, exist_ok=True)

        zip_path = os.path.join(order_dir, f"RaffleTickets_{order_id}.zip")
        with open(zip_path, "wb") as f:
            f.write(zip_bytes)

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

    if enforce_limit:
        counter_path = os.path.join(order_dir, "downloads.txt")
        count = 0

        if os.path.exists(counter_path):
            with open(counter_path, "r") as f:
                count = int(f.read().strip() or 0)

        if count >= MAX_REDOWNLOADS:
            return jsonify({"error": "Re-download limit reached"}), 403

        with open(counter_path, "w") as f:
            f.write(str(count + 1))

    file_path = os.path.join(order_dir, selected_file)

    print("📦 Sending ticket file:", file_path)

    return Response(
        stream_file(file_path),
        mimetype="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{selected_file}"',
            "Content-Length": os.path.getsize(file_path),
        },
    )


# --------------------------------------------------
# ROUTES
# --------------------------------------------------
@app.route("/ticket_state", methods=["GET"])
def ticket_state():
    state = load_ticket_state()
    total_sold = read_sales()
    today = datetime.utcnow().strftime("%Y-%m-%d")

    # ✅ FIRST-TIME INITIALIZATION SAFETY
    if state.get("remaining") is None:
        # frontend will still overwrite via /sync_remaining
        state["remaining"] = 0
        state["last_calc_date"] = today
        save_ticket_state(state)

    return jsonify({
        "remaining": state["remaining"],
        "last_calc_date": state["last_calc_date"],
        "total_sold": total_sold,
        "today": today
    }), 200

@app.route("/tickets_sold", methods=["GET"])
def tickets_sold():
    """
    Frontend reads how many tickets are already sold.
    """
    return jsonify({
        "total_sold": read_sales()
    }), 200

@app.route("/record_sale", methods=["POST"])
def record_sale():
    """
    Records ticket sales AFTER successful payment.
    Additive only – does not affect ticket generation.
    """
    data = request.get_json(force=True)
    tickets_bought = int(data.get("tickets", 0))

    if tickets_bought <= 0:
        return jsonify({"error": "Invalid ticket count"}), 400

    current_sold = read_sales()
    new_total = current_sold + tickets_bought

    write_sales(new_total)

    # 🔥 Burn remaining tickets authoritatively
    state = load_ticket_state()
    if state.get("remaining") is not None:
        state["remaining"] = max(1
            int(state["remaining"]) - quantity,
            0
        )
        save_ticket_state(state)

    return jsonify({
        "success": True,
        "tickets_bought": tickets_bought,
        "total_sold": new_total
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

            cleanup_old_orders()

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

        record_ticket_sale(quantity)

        cleanup_old_orders()

        return (
            jsonify({"status": "tickets_generated", "order_id": order_id}),
            200,
        )

    except Exception as e:
        print("❌ Ticket generation error:", e)
        return jsonify({"error": "Ticket generation failed"}), 500


@app.route("/sync_remaining", methods=["POST"])
def sync_remaining():
    """
    Frontend syncs daily recalculated remaining tickets.
    This happens once per day.
    """
    data = request.get_json(force=True)
    remaining = data.get("remaining")

    if remaining is None:
        return jsonify({"error": "Missing remaining"}), 400

    today = datetime.utcnow().strftime("%Y-%m-%d")

    state = load_ticket_state()
    state["remaining"] = int(remaining)
    state["last_calc_date"] = today                                    
    save_ticket_state(state)

    return jsonify({
        "success": True,
        "remaining": state["remaining"],
        "date": today
    }), 200


# --------------------------------------------------
# MAIN
# --------------------------------------------------


@app.route("/download_ticket", methods=["POST"])
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
def my_tickets():
    ok, err = verify_request_hmac(request)
    if not ok:
        return jsonify({"error": err}), 403

    data = request.get_json(force=True)
    email = data.get("email", "").strip().lower()

    if not email:
        return jsonify({"error": "Missing email"}), 400

    index = load_orders_index()
    orders = [
        {
            "order_id": oid,
            "product_name": meta.get("product"),
            "quantity": meta.get("quantity"),
            "tickets": meta.get("tickets", []),
            "date": meta.get("created_at"),
        }
        for oid, meta in index["orders"].items()
        if meta["email"] == email
    ]

    return jsonify({"orders": orders}), 200


@app.route("/redownload_ticket", methods=["POST"])
def redownload_ticket():
    ok, err = verify_request_hmac(request)
    if not ok:
        return jsonify({"error": err}), 403

    data = request.get_json(force=True)
    order_id = data.get("order_id")

    if not order_id:
        return jsonify({"error": "Missing order_id"}), 400

    return send_ticket_file(order_id, enforce_limit=True)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
