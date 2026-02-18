#!/data/data/com.termux/files/usr/bin/bash

BASE_URL="https://goodwill-backend-kjn5.onrender.com"
NOW=$(date +%s)

echo "=============================="
echo "RAFFLE SECURITY TEST REPORT"
echo "Target: $BASE_URL"
echo "Time: $(date)"
echo "=============================="
echo ""

# -----------------------------------------
# 1️⃣ Health Check
# -----------------------------------------
echo "1️⃣ Health Check"
curl -s "$BASE_URL/" | jq .
echo ""

# -----------------------------------------
# 2️⃣ Missing HMAC
# -----------------------------------------
echo "2️⃣ Missing HMAC Test"
curl -s -X POST "$BASE_URL/generate_ticket" \
  -H "Content-Type: application/json" \
  -d '{"name":"Hacker","quantity":1}' | jq .
echo ""

# -----------------------------------------
# 3️⃣ Fake Signature
# -----------------------------------------
echo "3️⃣ Fake Signature Test"
curl -s -X POST "$BASE_URL/generate_ticket" \
  -H "Content-Type: application/json" \
  -H "X-Signature: fake123" \
  -H "X-Timestamp: $NOW" \
  -d '{"name":"Hacker","quantity":1}' | jq .
echo ""

# -----------------------------------------
# 4️⃣ Expired Timestamp
# -----------------------------------------
OLD_TS=$((NOW - 1000))
echo "4️⃣ Expired Timestamp Test"
curl -s -X POST "$BASE_URL/generate_ticket" \
  -H "Content-Type: application/json" \
  -H "X-Signature: fake123" \
  -H "X-Timestamp: $OLD_TS" \
  -d '{"name":"Hacker","quantity":1}' | jq .
echo ""

# -----------------------------------------
# 5️⃣ Download Non-Existent Order
# -----------------------------------------
echo "5️⃣ Fake Order Download Test"
curl -s -X POST "$BASE_URL/download_ticket" \
  -H "Content-Type: application/json" \
  -H "X-Signature: fake123" \
  -H "X-Timestamp: $NOW" \
  -d '{"order_id":"FAKEORDER123"}' | jq .
echo ""

# -----------------------------------------
# 6️⃣ Directory Traversal Attempt
# -----------------------------------------
echo "6️⃣ Directory Traversal Test"
curl -s -X POST "$BASE_URL/download_ticket" \
  -H "Content-Type: application/json" \
  -H "X-Signature: fake123" \
  -H "X-Timestamp: $NOW" \
  -d '{"order_id":"../../app.py"}' | jq .
echo ""

# -----------------------------------------
# 7️⃣ Rate Limit Test (ticket_state)
# -----------------------------------------
echo "7️⃣ Rate Limit Test"
for i in {1..7}
do
  echo -n "Request $i: "
  curl -s -o /dev/null -w "%{http_code}\n" "$BASE_URL/ticket_state"
done
echo ""

echo "=============================="
echo "TEST COMPLETE"
echo "=============================="
