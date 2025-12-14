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
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)

# --------------------------------------------------
# PATHS (RENDER SAFE)
# --------------------------------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# PDF template MUST be inside goodwill_backend/
TEMPLATE_PATH = os.path.join(BASE_DIR, "Raffle_Ticket_Template1.pdf")

# Render allows writes ONLY to /tmp
OUTPUT_DIR = "/tmp/tickets"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# --------------------------------------------------
# HARD-CODED EVENT DATA
# --------------------------------------------------

HARD_CODED_EVENT_DATE = "Dec 30, 2025"
HARD_CODED_PRICE = "5"
HARD_CODED_EVENT_PLACE = "Nairobi"

# --------------------------------------------------
# HELPERS
# --------------------------------------------------

def generate_ticket_no():
    return f"GWS-{random.randint(100000, 999999)}"


def fill_pdf(reader: PdfReader, full_name: str):
    """Fill PDF form fields and return filled PDF bytes"""

    writer = PdfWriter()
    page = reader.pages[0]
    writer.add_page(page)

    ticket_no = generate_ticket_no()

    fields = {
        "Text1": HARD_CODED_EVENT_DATE,
        "Text2": full_name,
        "Text3": HARD_CODED_PRICE,
        "Text4": HARD_CODED_EVENT_PLACE,
        "Text5": ticket_no,
    }

    writer.update_page_form_field_values(writer.pages[0], fields)

    # Preserve form appearance
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
    """Flatten PDF (remove form fields permanently)"""

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

@app.route("/generate_ticket", methods=["POST"])
def generate_ticket():
    data = request.get_json(force=True)

    full_name = data.get("name", "").strip()
    quantity = int(data.get("quantity", 1))
    order_id = data.get("order_id", "UNKNOWN")

    if not full_name:
        return jsonify({"error": "Missing required field: name"}), 400

    try:
        reader = PdfReader(TEMPLATE_PATH)
        generated_files = []

        # Generate tickets
        for _ in range(quantity):
            filled_stream, ticket_no = fill_pdf(reader, full_name)
            flattened_stream = flatten_pdf(filled_stream)

            filename = f"RaffleTicket_{ticket_no}.pdf"
            filepath = os.path.join(OUTPUT_DIR, filename)

            with open(filepath, "wb") as f:
                f.write(flattened_stream.read())

            generated_files.append(filename)

        # SINGLE ticket → direct PDF download
        if quantity == 1:
            return jsonify({
                "success": True,
                "download_url": f"/download/{generated_files[0]}"
            })

        # MULTIPLE tickets → ZIP
        zip_name = f"RaffleTickets_{order_id}.zip"
        zip_path = os.path.join(OUTPUT_DIR, zip_name)

        with zipfile.ZipFile(zip_path, "w") as zf:
            for filename in generated_files:
                zf.write(os.path.join(OUTPUT_DIR, filename), filename)

        return jsonify({
            "success": True,
            "download_url": f"/download/{zip_name}"
        })

    except Exception as e:
        print("❌ Ticket generation error:", e)
        return jsonify({"error": "Ticket generation failed"}), 500


@app.route("/download/<filename>")
def download_file(filename):
    filepath = os.path.join(OUTPUT_DIR, filename)

    if not os.path.exists(filepath):
        return jsonify({"error": "File not found"}), 404

    return send_file(filepath, as_attachment=True)

# --------------------------------------------------
# MAIN
# --------------------------------------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
