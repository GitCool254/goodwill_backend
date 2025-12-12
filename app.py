from flask import Flask, request, send_file
from flask_cors import CORS
from PyPDF2 import PdfReader, PdfWriter
from PyPDF2.generic import BooleanObject, NameObject
import io
import random
import zipfile

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)

TEMPLATE_PATH = "/storage/emulated/0/Download/Raffle_Ticket_Template1.pdf"

HARD_CODED_EVENT_DATE = "Dec 30, 2025"
HARD_CODED_PRICE = "5"
HARD_CODED_EVENT_PLACE = "Nairobi"


def generate_ticket_no():
    return f"GWS-{random.randint(100000, 999999)}"


def fill_pdf(reader: PdfReader, full_name: str):
    """Fill form fields and return filled PDF bytes"""

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

    # Ensure appearance
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
    """Truly flatten PDF by removing all form fields and AcroForm."""

    filled_reader = PdfReader(filled_stream)
    flat_writer = PdfWriter()

    # Copy pages normally
    for page in filled_reader.pages:
        flat_writer.add_page(page)

    # Remove AcroForm completely (REAL FLATTEN)
    if "/AcroForm" in filled_reader.trailer["/Root"]:
        # Delete from WRITER root object
        if "/AcroForm" in flat_writer._root_object:
            del flat_writer._root_object["/AcroForm"]

    # Write flattened output
    flattened = io.BytesIO()
    flat_writer.write(flattened)
    flattened.seek(0)
    return flattened


@app.route("/generate_ticket", methods=["POST"])
def generate_ticket():
    data = request.get_json()
    full_name = data.get("name", "").strip()
    quantity = int(data.get("quantity", 1))

    if not full_name:
        return {"error": "Missing required field: name"}, 400

    try:
        reader = PdfReader(TEMPLATE_PATH)

        # SINGLE ticket
        if quantity == 1:
            filled_stream, ticket_no = fill_pdf(reader, full_name)
            flattened_stream = flatten_pdf(filled_stream)

            return send_file(
                flattened_stream,
                as_attachment=True,
                download_name=f"RaffleTicket_{ticket_no}.pdf",
                mimetype="application/pdf"
            )

        # MULTIPLE tickets -> ZIP
        zip_stream = io.BytesIO()
        with zipfile.ZipFile(zip_stream, "w") as zf:
            for _ in range(quantity):
                filled_stream, ticket_no = fill_pdf(reader, full_name)
                flattened_stream = flatten_pdf(filled_stream)
                zf.writestr(f"RaffleTicket_{ticket_no}.pdf", flattened_stream.read())

        zip_stream.seek(0)
        return send_file(
            zip_stream,
            as_attachment=True,
            download_name=f"RaffleTickets_{full_name.replace(' ', '_')}.zip",
            mimetype="application/zip"
        )

    except Exception as e:
        print("❌ Ticket generation error:", e)
        return {"error": "Ticket generation failed"}, 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
