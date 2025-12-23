from flask import Flask, request, send_file, jsonify
from flask_cors import CORS
from PyPDF2 import PdfReader, PdfWriter
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


def fill_pdf_form(full_name, ticket_no):
    """
    Fill the PDF form fields directly using PyPDF2's form filling capabilities
    """
    try:
        # Read the template PDF
        reader = PdfReader(TEMPLATE_PATH)
        
        # First, let's check what form fields exist
        if reader.get_fields():
            print("✅ PDF has form fields:", reader.get_fields())
            
        # Create a writer object
        writer = PdfWriter()
        
        # Clone the page
        page = reader.pages[0]
        writer.add_page(page)
        
        # Try to fill form fields directly
        # Common field names to try
        field_mapping = {
            'DATE': EVENT_DATE,
            'Date': EVENT_DATE,
            'date': EVENT_DATE,
            'EVENT_DATE': EVENT_DATE,
            
            'Name': full_name,
            'NAME': full_name,
            'Full Name': full_name,
            'FULL_NAME': full_name,
            'FULLNAME': full_name,
            
            'Ticket Price': TICKET_PRICE,
            'PRICE': TICKET_PRICE,
            'Price': TICKET_PRICE,
            'TICKET_PRICE': TICKET_PRICE,
            
            'Event Place': EVENT_PLACE,
            'PLACE': EVENT_PLACE,
            'Place': EVENT_PLACE,
            'LOCATION': EVENT_PLACE,
            'EVENT_PLACE': EVENT_PLACE,
            
            'TICKET NO': ticket_no,
            'TICKET_NO': ticket_no,
            'Ticket No': ticket_no,
            'TICKET_NUMBER': ticket_no,
            'Ticket Number': ticket_no,
            'TICKET': ticket_no
        }
        
        # Update form fields
        writer.update_page_form_field_values(
            writer.pages[0], 
            field_mapping
        )
        
        # Create output stream
        output = io.BytesIO()
        writer.write(output)
        output.seek(0)
        
        return output
        
    except Exception as e:
        print(f"❌ Error filling form fields: {e}")
        # Fallback: Let's try a different approach
        return fill_pdf_fallback(full_name, ticket_no)


def fill_pdf_fallback(full_name, ticket_no):
    """
    Fallback method if direct form filling doesn't work
    This tries to find and fill ANY form fields in the PDF
    """
    try:
        reader = PdfReader(TEMPLATE_PATH)
        writer = PdfWriter()
        writer.add_page(reader.pages[0])
        
        # Get all form fields
        fields = reader.get_fields()
        
        if fields:
            print(f"🔍 Found {len(fields)} form fields:")
            for field_name in fields:
                print(f"  - '{field_name}'")
            
            # Create a dictionary of all possible field names and values
            all_possible_values = {
                EVENT_DATE: [EVENT_DATE],
                full_name: [full_name],
                TICKET_PRICE: [TICKET_PRICE, f"${TICKET_PRICE}"],
                EVENT_PLACE: [EVENT_PLACE],
                ticket_no: [ticket_no]
            }
            
            # Try to fill each field based on its name
            form_data = {}
            for field_name in fields.keys():
                field_lower = field_name.lower()
                
                if 'date' in field_lower:
                    form_data[field_name] = EVENT_DATE
                elif 'name' in field_lower:
                    form_data[field_name] = full_name
                elif 'price' in field_lower or 'cost' in field_lower:
                    form_data[field_name] = TICKET_PRICE
                elif 'place' in field_lower or 'location' in field_lower or 'venue' in field_lower:
                    form_data[field_name] = EVENT_PLACE
                elif 'ticket' in field_lower or 'no' in field_lower or 'number' in field_lower:
                    form_data[field_name] = ticket_no
                else:
                    # Try to guess based on field name
                    form_data[field_name] = EVENT_DATE  # Default
            
            print(f"📝 Filling form with data: {form_data}")
            writer.update_page_form_field_values(writer.pages[0], form_data)
        
        output = io.BytesIO()
        writer.write(output)
        output.seek(0)
        
        return output
        
    except Exception as e:
        print(f"❌ Fallback also failed: {e}")
        raise


# --------------------------------------------------
# ROUTES
# --------------------------------------------------

@app.route("/", methods=["GET"])
def health_check():
    return jsonify({"status": "Raffle API running"}), 200


@app.route("/debug_fields", methods=["GET"])
def debug_fields():
    """
    Debug endpoint to see what form fields exist in the template
    """
    try:
        reader = PdfReader(TEMPLATE_PATH)
        fields = reader.get_fields()
        
        if fields:
            field_info = {}
            for name, field in fields.items():
                field_info[name] = {
                    "type": str(type(field)),
                    "value": str(field.get('/V')) if field.get('/V') else "None"
                }
            
            return jsonify({
                "has_form_fields": True,
                "field_count": len(fields),
                "fields": field_info
            }), 200
        else:
            return jsonify({
                "has_form_fields": False,
                "message": "No interactive form fields found in PDF"
            }), 200
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500


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
            filled_pdf = fill_pdf_form(full_name, ticket_no)

            return send_file(
                filled_pdf,
                as_attachment=True,
                download_name=f"RaffleTicket_{ticket_no}.pdf",
                mimetype="application/pdf"
            )

        # -------- MULTIPLE TICKETS → ZIP --------
        zip_stream = io.BytesIO()
        with zipfile.ZipFile(zip_stream, "w", zipfile.ZIP_DEFLATED) as zf:
            for _ in range(quantity):
                ticket_no = generate_ticket_no()
                filled_pdf = fill_pdf_form(full_name, ticket_no)

                zf.writestr(
                    f"RaffleTicket_{ticket_no}.pdf",
                    filled_pdf.read()
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
        return jsonify({"error": f"Ticket generation failed: {str(e)}"}), 500


# --------------------------------------------------
# MAIN
# --------------------------------------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
