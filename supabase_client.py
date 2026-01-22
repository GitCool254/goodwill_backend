from supabase import create_client, Client
import os

# Get environment variables
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

# Fail fast if missing
if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Supabase URL or Service Role Key is not set in environment variables!")

# Create Supabase client
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
