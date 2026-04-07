#!/usr/bin/env bash
set -euo pipefail

SMOKE_TIMEOUT="${SMOKE_TIMEOUT:-180}"
API_URL="http://localhost:8000"

echo "=== Alaya Smoke Test ==="

# Start services
echo "Starting services..."
docker compose up -d

# Wait for health check
echo "Waiting for API to be ready..."
for i in $(seq 1 60); do
    if curl -sf "${API_URL}/health/ready" > /dev/null 2>&1; then
        echo "API ready on attempt ${i}"
        break
    fi
    if [ "${i}" -eq 60 ]; then
        echo "ERROR: API not ready after 60 seconds"
        docker compose logs --tail=50
        docker compose down
        exit 1
    fi
    sleep 1
done

# Get bootstrap key from seed output
echo "Retrieving bootstrap API key..."
BOOTSTRAP_KEY=$(docker compose logs migrations 2>/dev/null | grep -oP 'ak_[a-zA-Z0-9]+' | head -1)
if [ -z "${BOOTSTRAP_KEY}" ]; then
    echo "ERROR: Could not find bootstrap API key in migration logs"
    docker compose down
    exit 1
fi
echo "Found key: ${BOOTSTRAP_KEY:0:12}..."

# Test: List entities
echo "Testing: GET /api/v1/entities"
STATUS=$(curl -sf -o /dev/null -w '%{http_code}' \
    -H "X-Api-Key: ${BOOTSTRAP_KEY}" \
    "${API_URL}/api/v1/entities")
if [ "${STATUS}" != "200" ]; then
    echo "FAIL: Expected 200, got ${STATUS}"
    docker compose down
    exit 1
fi
echo "PASS: 200"

# Test: Create entity (need entity type first)
echo "Testing: GET /api/v1/entity-types"
TYPES_RESPONSE=$(curl -sf \
    -H "X-Api-Key: ${BOOTSTRAP_KEY}" \
    "${API_URL}/api/v1/entity-types")
TYPE_ID=$(echo "${TYPES_RESPONSE}" | python3 -c "import sys,json; print(json.load(sys.stdin)['data'][0]['id'])" 2>/dev/null)
if [ -z "${TYPE_ID}" ]; then
    echo "FAIL: No entity types found"
    docker compose down
    exit 1
fi
echo "PASS: Found entity type ${TYPE_ID}"

echo "Testing: POST /api/v1/entities"
CREATE_STATUS=$(curl -sf -o /dev/null -w '%{http_code}' \
    -H "X-Api-Key: ${BOOTSTRAP_KEY}" \
    -H "Content-Type: application/json" \
    -d "{\"entity_type_id\": \"${TYPE_ID}\", \"name\": \"Smoke Test Entity\"}" \
    "${API_URL}/api/v1/entities")
if [ "${CREATE_STATUS}" != "201" ]; then
    echo "FAIL: Expected 201, got ${CREATE_STATUS}"
    docker compose down
    exit 1
fi
echo "PASS: 201"

# Cleanup
echo "Stopping services..."
docker compose down

echo "=== Smoke Test PASSED ==="
