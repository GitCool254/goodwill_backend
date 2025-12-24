from flask import Flask, request, send_file, jsonify
from flask_cors import CORS
import fitz  # PyMuPDF
import io
import random
import zipfile
import os

# --------------------------------------------------
# APP SETUP
# --------------------------------------------------

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# --------------------------------------------------
# PATHS
# --------------------------------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_PATH = os.path.join(BASE_DIR, "Raffle_Ticket_TemplateN.pdf")

# --------------------------------------------------
# EVENT DATA
# --------------------------------------------------

EVENT_DATE = "Dec 30, 2025"
TICKET_PRICE = "5"
EVENT_PLACE = "District of Colombia, DC, United States"
EVENT_TIME = "5PM"

MAX_NAME_LENGTH = 30
MAX_PLACE_LENGTH = 35

MAX_EXPAND_CHARS = 25
EXPAND_PADDING = 6

# --------------------------------------------------
# HELPERS
# --------------------------------------------------

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

            # --- Measure actual text width ---
            text_width = fitz.get_text_length(
                text_str,
                fontname=fontname,
                fontsize=fontsize
            )

            BASE_WIDTH = rect.width

            # --- RECTANGLE SIZE LOGIC ---
            if len(text_str) <= MAX_EXPAND_CHARS:
                # Grow OR shrink naturally to text width
                new_width = max(BASE_WIDTH, text_width + EXPAND_PADDING)
            else:
                # Lock rectangle width at 25-character width
                avg_char_width = text_width / max(len(text_str), 1)
                locked_width = (avg_char_width * MAX_EXPAND_CHARS) + EXPAND_PADDING
                new_width = max(BASE_WIDTH, locked_width)

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

            # --- Auto-shrink font if needed ---
            while fontsize > 6 and fitz.get_text_length(
                text_str,
                fontname=fontname,
                fontsize=fontsize
            ) > (flex_rect.width - 4):
                fontsize -= 0.5

            # --- Vertical centering ---
            y_position = flex_rect.y0 + (flex_rect.height - fontsize) / 2

            # --- Draw text ---
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
    quantity = int(data.get("quantity", 1))

    if len(full_name) > MAX_NAME_LENGTH:
        full_name = full_name[:MAX_NAME_LENGTH] + "…"

    if len(event_place) > MAX_PLACE_LENGTH:
        event_place = event_place[:MAX_PLACE_LENGTH] + "…"

    if not full_name:
        return jsonify({"error": "Missing required field: name"}), 400

    try:
        if quantity == 1:
            ticket_no = generate_ticket_no()

            pdf = generate_ticket_with_placeholders(
                full_name,
                ticket_no,
                EVENT_DATE,
                TICKET_PRICE,
                event_place,
                EVENT_TIME,
            )

            return send_file(
                pdf,
                as_attachment=True,
                download_name=f"RaffleTicket_{ticket_no}.pdf",
                mimetype="application/pdf"
            )

        zip_stream = io.BytesIO()
        with zipfile.ZipFile(zip_stream, "w", zipfile.ZIP_DEFLATED) as zf:
            for _ in range(quantity):
                ticket_no = generate_ticket_no()

                pdf = generate_ticket_with_placeholders(
                    full_name,
                    ticket_no,
                    EVENT_DATE,
                    TICKET_PRICE,
                    event_place,
                    EVENT_TIME,
                )

                zf.writestr(
                    f"RaffleTicket_{ticket_no}.pdf",
                    pdf.read()
                )

        zip_stream.seek(0)

        return send_file(
            zip_stream,
            as_attachment=True,
            download_name=f"RaffleTickets_{full_name.replace(' ', '_')}.zip",
            mimetype="application/zip"
        )

    except Exception as e:
        print("❌ Ticket generation error:", e)
        return jsonify({"error": "Ticket generation failed"}), 500

# --------------------------------------------------
# MAIN
# --------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
