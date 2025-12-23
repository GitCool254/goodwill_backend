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
EVENT_PLACE = "Nairobi"

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
    event_place
):
    """
    Replaces visible placeholders in the PDF with permanent bold text.
    """
    doc = fitz.open(TEMPLATE_PATH)
    page = doc[0]

    replacements = {
        "{{NAME}}": full_name,
        "{{TICKET_NO}}": ticket_no,
        "{{TICKET_PRICE}}": ticket_price,
        "{{EVENT_PLACE}}": event_place,
        "{{DATE}}": event_date,
    }

    for placeholder, value in replacements.items():
        matches = page.search_for(placeholder)

        if not matches:
            print(f"⚠️ Placeholder not found: {placeholder}")
            continue

        for rect in matches:
            # Clear placeholder
            page.draw_rect(rect, color=(1, 1, 1), fill=(1, 1, 1))

            # Insert permanent bold text
            page.insert_text(
                (rect.x0 + 2, rect.y1 - 3),
                value,
                fontsize=12,
                fontname="helv",
                color=(0, 0, 0),
                render_mode=2  # bold
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
    quantity = int(data.get("quantity", 1))

    if not full_name:
        return jsonify({"error": "Missing required field: name"}), 400

    try:
        # -------- SINGLE TICKET --------
        if quantity == 1:
            ticket_no = generate_ticket_no()

            pdf = generate_ticket_with_placeholders(
                full_name=full_name,
                ticket_no=ticket_no,
                event_date=EVENT_DATE,
                ticket_price=TICKET_PRICE,
                event_place=EVENT_PLACE,
            )

            return send_file(
                pdf,
                as_attachment=True,
                download_name=f"RaffleTicket_{ticket_no}.pdf",
                mimetype="application/pdf"
            )

        # -------- MULTIPLE TICKETS (ZIP) --------
        zip_stream = io.BytesIO()
        with zipfile.ZipFile(zip_stream, "w", zipfile.ZIP_DEFLATED) as zf:
            for _ in range(quantity):
                ticket_no = generate_ticket_no()

                pdf = generate_ticket_with_placeholders(
                    full_name,
                    ticket_no,
                    EVENT_DATE,
                    TICKET_PRICE,
                    EVENT_PLACE,
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
