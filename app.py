from flask import Flask, request, send_file, jsonify
from flask_cors import CORS
from PyPDF2 import PdfReader, PdfWriter
import io
import random
import zipfile
import os
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter

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


def create_text_overlay(full_name, ticket_no):
    """
    Creates a PDF overlay with permanent text (not form fields)
    """
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)

    # Use black color for text
    c.setFillColorRGB(0, 0, 0)
    
    # Based on your template structure, we need to place text
    # to the right of the labels (DATE:, Name:, etc.)
    
    # Font settings
    c.setFont("Helvetica-Bold", 12)
    
    # Adjust these coordinates based on where the blank spaces are in your template
    # The first number is X (horizontal), second is Y (vertical)
    
    # Try these coordinates (adjust as needed):
    # DATE: - placed to the right of "DATE:"
    c.drawString(80, 650, EVENT_DATE)  # Adjust Y value based on template
    
    # Name: - placed to the right of "Name:"
    c.drawString(80, 620, full_name)  # Adjust Y value based on template
    
    # Ticket Price: - placed to the right of "Ticket Price:"
    c.drawString(80, 590, TICKET_PRICE)  # Adjust Y value based on template
    
    # Event Place: - placed to the right of "Event Place:"
    c.drawString(80, 560, EVENT_PLACE)  # Adjust Y value based on template
    
    # TICKET NO: - placed to the right of "TICKET NO:"
    c.drawString(80, 530, ticket_no)  # Adjust Y value based on template

    c.showPage()
    c.save()

    buffer.seek(0)
    return buffer


def merge_overlay_with_template(overlay_stream):
    """
    Merges text overlay onto the ticket template
    """
    template_reader = PdfReader(TEMPLATE_PATH)
    overlay_reader = PdfReader(overlay_stream)

    writer = PdfWriter()

    base_page = template_reader.pages[0]
    overlay_page = overlay_reader.pages[0]

    base_page.merge_page(overlay_page)
    writer.add_page(base_page)

    output = io.BytesIO()
    writer.write(output)
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
        # -------- SINGLE TICKET → PDF --------
        if quantity == 1:
            ticket_no = generate_ticket_no()
            overlay = create_text_overlay(full_name, ticket_no)
            final_pdf = merge_overlay_with_template(overlay)

            return send_file(
                final_pdf,
                as_attachment=True,
                download_name=f"RaffleTicket_{ticket_no}.pdf",
                mimetype="application/pdf"
            )

        # -------- MULTIPLE TICKETS → ZIP --------
        zip_stream = io.BytesIO()
        with zipfile.ZipFile(zip_stream, "w", zipfile.ZIP_DEFLATED) as zf:
            for _ in range(quantity):
                ticket_no = generate_ticket_no()
                overlay = create_text_overlay(full_name, ticket_no)
                final_pdf = merge_overlay_with_template(overlay)

                zf.writestr(
                    f"RaffleTicket_{ticket_no}.pdf",
                    final_pdf.read()
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
