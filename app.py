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
                "https://goodwill-raffle-store-raffle-store.vercel.app"
            ],
            "expose_headers": ["X-Ticket-Numbers"]
        },
        r"/redownload_ticket": {
            "origins": [
                "https://goodwill-raffle-store-raffle-store.onrender.com",
                "https://goodwill-raffle-store-raffle-store.vercel.app"
            ]
        }
    }
)



# --------------------------------------------------
# PATHS
# --------------------------------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_PATH = os.path.join(BASE_DIR, "Raffle_Ticket_TemplateN.pdf")

# --------------------------------------------------
# PERSISTENT TICKET STORAGE
# --------------------------------------------------
TICKET_STORAGE_DIR = os.environ.get(
    "TICKET_STORAGE_DIR",
    os.path.join(BASE_DIR, "storage", "tickets")
)

os.makedirs(TICKET_STORAGE_DIR, exist_ok=True)

MAX_REDOWNLOADS = 2

# --------------------------------------------------
# EVENT DATA
# --------------------------------------------------

EVENT_DATE = "Dec 30, 2025"
EVENT_PLACE = "District of Colombia, DC, United States"
EVENT_TIME = "5PM"

MAX_NAME_LENGTH = 45
MAX_PLACE_LENGTH = 45

MAX_EXPAND_CHARS = 25
EXPAND_PADDING = 6

SECRET_KEY = os.environ.get("API_SIGN_SECRET", "goodwill_5490_secret")

# --------------------------------------------------
# HELPERS
# --------------------------------------------------

def verify_signature(payload: str, signature: str) -> bool:
    expected = hmac.new(
        SECRET_KEY.encode(),
        payload.encode(),
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(expected, signature)

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

def verify_paypal_order(order_id, expected_amount):
    auth = (PAYPAL_CLIENT_ID, PAYPAL_SECRET)

    r = requests.get(
        f"{PAYPAL_API_BASE}/v2/checkout/orders/{order_id}",
        auth=auth,
        headers={"Content-Type": "application/json"}
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
        return False, f"Amount mismatch (paid {paid_amount}, expected {expected_amount})"

    if order_id in USED_ORDERS:
        return False, "Order already used"

    USED_ORDERS.add(order_id)
    return True, None

def generate_ticket_no():
    return f"GWS-{random.randint(100000, 999999)}"


def generate_ticket_with_placeholders(
    full_name,
    ticket_no,
    event_date,
    ticket_price,
    event_place,
    event_time
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
                text_str,
                fontname=fontname,
                fontsize=fontsize
            )

            base_width = rect.width

            # --- Rectangle sizing logic ---
            if len(text_str) <= MAX_EXPAND_CHARS:
                new_width = max(base_width, text_width + EXPAND_PADDING)
            else:
                avg_char_width = text_width / max(len(text_str), 1)
                locked_width = (avg_char_width * MAX_EXPAND_CHARS) + EXPAND_PADDING
                new_width = max(base_width, locked_width)

            flex_rect = fitz.Rect(
                rect.x0,
                rect.y0,
                rect.x0 + new_width,
                rect.y1
            )

            # --- Clear background ---
            page.draw_rect(
                flex_rect,
                color=(1, 1, 1),
                fill=(1, 1, 1)
            )

            # --- Auto-shrink font to fit ---
            while fontsize > 6:
                if fitz.get_text_length(
                    text_str,
                    fontname=fontname,
                    fontsize=fontsize
                ) <= (flex_rect.width - 4):
                    break
                fontsize -= 1

            # --- CORRECT vertical centering (baseline-aware) ---
            y_position = flex_rect.y0 + (flex_rect.height / 2) + (fontsize * 0.35)

            # --- Draw text INSIDE rectangle ---
            page.insert_text(
                (flex_rect.x0 + 2, y_position),
                text_str,
                fontsize=fontsize,
                fontname=fontname,
                color=(0, 0, 0)
            )

    output = io.BytesIO()
    doc.save(output)
    doc.close()
    output.seek(0)
    return output

# --------------------------------------------------
# ROUTES
# --------------------------------------------------

@app.route("/", methods=["GET"])
def health_check():
    return jsonify({"status": "Raffle API running"}), 200


@app.route("/generate_ticket", methods=["POST"])
def generate_ticket():
    data = request.get_json(force=True)

    full_name = data.get("name", "").strip()
    event_place = data.get("event_place", EVENT_PLACE).strip()

    try:
        quantity = int(data.get("quantity", 1))
    except:
        return jsonify({"error": "Invalid quantity"}), 400

    ticket_price = data.get("ticket_price")

    try:
        ticket_price = Decimal(str(ticket_price)).quantize(Decimal("0.01"))
    except:
        return jsonify({"error": "Invalid ticket price"}), 400

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

            pdf_bytes = pdf.getbuffer()

            response = Response(
                pdf_bytes,
                mimetype="application/pdf",
                headers={
                    "Content-Disposition": f'attachment; filename="RaffleTicket_{ticket_no}.pdf"',
                    "Content-Length": str(len(pdf_bytes)),
                    "Cache-Control": "no-store",
                    "X-Content-Type-Options": "nosniff"
                }
            )

            response.headers["X-Ticket-Numbers"] = ticket_no

            # 🔥 WRITE TO DISK AFTER response object is created
            pdf_bytes = pdf.getvalue()

            order_dir = os.path.join(TICKET_STORAGE_DIR, order_id)
            os.makedirs(order_dir, exist_ok=True)

            file_path = os.path.join(order_dir, f"RaffleTicket_{ticket_no}.pdf")
            with open(file_path, "wb") as f:
                f.write(pdf_bytes)

            return response

        ticket_numbers = []

        zip_stream = io.BytesIO()
        with zipfile.ZipFile(zip_stream, "w", zipfile.ZIP_STORED) as zf:
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

                zf.writestr(
                    f"RaffleTicket_{ticket_no}.pdf",
                    pdf.getvalue()
                )

        zip_stream.seek(0)

        response = Response(
            zip_stream,
            mimetype="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="RaffleTickets_{full_name.replace(" ", "_")}.zip"',
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff"
            },
            direct_passthrough=True
        )

        # 🔐 STORE FILE FOR RE-DOWNLOAD (Option A)
        # 🔐 STORE FILE TO DISK (persistent)
        order_dir = os.path.join(TICKET_STORAGE_DIR, order_id)
        os.makedirs(order_dir, exist_ok=True)

        zip_path = os.path.join(
            order_dir,
            f"RaffleTickets_{full_name.replace(' ', '_')}.zip"
        )

        with open(zip_path, "wb") as f:
            f.write(zip_stream.getvalue())

        # ✅ SEND ALL GENERATED TICKET NUMBERS
        response.headers["X-Ticket-Numbers"] = ",".join(ticket_numbers)
        return response

    except Exception as e:
        print("❌ Ticket generation error:", e)
        return jsonify({"error": "Ticket generation failed"}), 500

# --------------------------------------------------
# MAIN
# --------------------------------------------------

@app.route("/redownload_ticket", methods=["POST"])
def redownload_ticket():
    data = request.get_json(force=True)
    order_id = data.get("order_id")

    if not order_id:
        return jsonify({"error": "Missing order_id"}), 400

    order_dir = os.path.join(TICKET_STORAGE_DIR, order_id)

    if not os.path.exists(order_dir):
        return jsonify({"error": "Ticket not found"}), 404

    files = os.listdir(order_dir)
    if not files:
        return jsonify({"error": "Ticket not found"}), 404

    download_counter = os.path.join(order_dir, "downloads.txt")

    # Read current count
    if os.path.exists(download_counter):
        with open(download_counter, "r") as f:
            count = int(f.read().strip() or 0)
    else:
        count = 0

    # Enforce limit
    if count >= MAX_REDOWNLOADS:
        return jsonify({"error": "Re-download limit reached"}), 403

    # Increment count
    with open(download_counter, "w") as f:
        f.write(str(count + 1))

    file_path = os.path.join(order_dir, files[0])

    return send_file(
        file_path,
        as_attachment=True,
        download_name=files[0]
    )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
