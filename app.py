from flask import Flask, request, send_file, jsonify
from flask_cors import CORS
from PyPDF2 import PdfReader, PdfWriter
from PyPDF2.generic import BooleanObject, NameObject
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
# PATHS (SAFE FOR RENDER & TERMUX)
# --------------------------------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# PDF template MUST be inside goodwill_backend/
TEMPLATE_PATH = os.path.join(BASE_DIR, "Raffle_Ticket_Template1.pdf")

# --------------------------------------------------
# HARD-CODED EVENT DATA
# --------------------------------------------------

EVENT_DATE = "Dec 30, 2025"
TICKET_PRICE = "5"
EVENT_PLACE = "Nairobi"

# --------------------------------------------------
# HELPERS
# --------------------------------------------------

def generate_ticket_no():
    return f"GWS-{random.randint(100000, 999999)}"


def fill_pdf(reader: PdfReader, full_name: str):
    """Fill PDF form fields and return filled PDF stream"""

    writer = PdfWriter()
    writer.add_page(reader.pages[0])

    ticket_no = generate_ticket_no()

    fields = {
        "Text1": EVENT_DATE,
        "Text2": full_name,
        "Text3": TICKET_PRICE,
        "Text4": EVENT_PLACE,
        "Text5": ticket_no,
    }

    writer.update_page_form_field_values(writer.pages[0], fields)

    # Preserve appearance
    if "/AcroForm" in reader.trailer["/Root"]:
        writer._root_object.update({
            NameObject("/AcroForm"): reader.trailer["/Root"]["/AcroForm"]
        })

    writer._root_object["/AcroForm"][NameObject("/NeedAppearances")] = BooleanObject(True)

    output = io.BytesIO()
    writer.write(output)
    output.seek(0)

    return output, ticket_no


def flatten_pdf(filled_stream: io.BytesIO):
    """Flatten PDF (remove all form fields permanently)"""

    reader = PdfReader(filled_stream)
    writer = PdfWriter()

    for page in reader.pages:
        writer.add_page(page)

    # Remove AcroForm completely
    if "/AcroForm" in writer._root_object:
        del writer._root_object["/AcroForm"]

    flattened = io.BytesIO()
    writer.write(flattened)
    flattened.seek(0)

    return flattened

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
        reader = PdfReader(TEMPLATE_PATH)

        # -------- SINGLE TICKET → PDF --------
        if quantity == 1:
            filled_stream, ticket_no = fill_pdf(reader, full_name)
            flattened_stream = flatten_pdf(filled_stream)

            return send_file(
                flattened_stream,
                as_attachment=True,
                download_name=f"RaffleTicket_{ticket_no}.pdf",
                mimetype="application/pdf"
            )

        # -------- MULTIPLE TICKETS → ZIP --------
        zip_stream = io.BytesIO()
        with zipfile.ZipFile(zip_stream, "w", zipfile.ZIP_DEFLATED) as zf:
            for _ in range(quantity):
                filled_stream, ticket_no = fill_pdf(reader, full_name)
                flattened_stream = flatten_pdf(filled_stream)
                zf.writestr(
                    f"RaffleTicket_{ticket_no}.pdf",
                    flattened_stream.read()
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
    app.run(host="0.0.0.0", port=5000)
