import requests
import time

# -----------------------------
# CONFIG
# -----------------------------
URL = "https://goodwill-backend-kjn5.onrender.com/ticket_state"  # change if deployed remotely
NUM_IPS = 2           # number of fake IPs to simulate
REQUESTS_PER_IP = 7   # requests per IP
DELAY_BETWEEN = 1     # seconds between requests
CACHE_CHECK_FIELD = "cache"  # field returned by /ticket_state indicating cache hit/miss

# -----------------------------
# TEST FUNCTION
# -----------------------------
def test_ticket_state(ip: str):
    print(f"\n=== Testing for IP: {ip} ===\n")
    for i in range(REQUESTS_PER_IP):
        headers = {"X-Forwarded-For": ip}
        try:
            response = requests.get(URL, headers=headers)
            status = response.status_code
            try:
                data = response.json()
                cache_status = data.get(CACHE_CHECK_FIELD, "N/A")
            except Exception:
                data = response.text
                cache_status = "N/A"

            print(f"Request {i+1} | Status: {status} | Cache: {cache_status} | Data: {data}")
        except Exception as e:
            print(f"Request {i+1} | Exception: {e}")
        time.sleep(DELAY_BETWEEN)

# -----------------------------
# MAIN
# -----------------------------
if __name__ == "__main__":
    for ip_index in range(NUM_IPS):
        fake_ip = f"1.2.3.{ip_index + 1}"
        test_ticket_state(fake_ip)

    print("\n✅ Test complete. Check for 429 status (rate limiting) and cache HIT/MISS fields.\n")
