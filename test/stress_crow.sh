#!/usr/bin/env bash
set -euo pipefail

URL="${1:-http://localhost:8000}"
DURATION="${DURATION:-30}"
CONCURRENCY="${CONCURRENCY:-100}"
TIMEOUT="${TIMEOUT:-5}"
PATHS_CSV="${PATHS_CSV:-/controlli/health}"
METHOD="${METHOD:-GET}"
HTTP_VERSION="${HTTP_VERSION:---http1.1}"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
mkdir -p output

if ! command -v curl >/dev/null 2>&1; then
  echo "Errore: curl non trovato" >&2
  exit 1
fi

IFS=',' read -r -a PATHS <<< "$PATHS_CSV"

START_TS=$(date +%s)
END_TS=$(( START_TS + DURATION ))

worker() {
  local id="$1"
  local ok=0 fail=0 total=0 bytes=0
  local lat_file="$TMP_DIR/lat_$id.csv"
  : > "$lat_file"

  while [ "$(date +%s)" -lt "$END_TS" ]; do
    local path="${PATHS[$(( RANDOM % ${#PATHS[@]} ))]}"
    local out code time_total size
    if ! out=$(curl -sS -o /dev/null \
      -X "$METHOD" \
      "$HTTP_VERSION" \
      --max-time "$TIMEOUT" \
      -w '%{http_code};%{time_total};%{size_download}' \
      "$URL$path" 2>/dev/null); then
      out='000;0;0'
    fi

    IFS=';' read -r code time_total size <<< "$out"
    total=$(( total + 1 ))
    bytes=$(( bytes + size ))
    awk -v t="$time_total" 'BEGIN { printf "%.6f\n", t }' >> "$lat_file"

    if [ "$code" -ge 200 ] && [ "$code" -lt 300 ]; then
      ok=$(( ok + 1 ))
    else
      fail=$(( fail + 1 ))
    fi
  done

  printf '%s,%s,%s,%s,%s\n' "$id" "$total" "$ok" "$fail" "${bytes:-0}" > "$TMP_DIR/res_$id.csv"
}

export URL METHOD TIMEOUT END_TS TMP_DIR
export PATHS_CSV
for i in $(seq 1 "$CONCURRENCY"); do
  worker "$i" &
done
wait

shopt -s nullglob
lat_files=("$TMP_DIR"/lat_*.csv)
res_files=("$TMP_DIR"/res_*.csv)
shopt -u nullglob

if [ ${#lat_files[@]} -eq 0 ] || [ ${#res_files[@]} -eq 0 ]; then
  echo "Errore: nessun risultato raccolto. Verifica che il target sia raggiungibile e che i worker completino almeno una richiesta." >&2
  exit 1
fi

cat "${lat_files[@]}" | sort -n > "$TMP_DIR/all_lat.csv"
cat "${res_files[@]}" > "$TMP_DIR/all_res.csv"

TOTAL_REQ=$(awk -F',' '{s+=$2} END{print s+0}' "$TMP_DIR/all_res.csv")
TOTAL_OK=$(awk -F',' '{s+=$3} END{print s+0}' "$TMP_DIR/all_res.csv")
TOTAL_FAIL=$(awk -F',' '{s+=$4} END{print s+0}' "$TMP_DIR/all_res.csv")
TOTAL_BYTES=$(awk -F',' '{s+=$5} END{print s+0}' "$TMP_DIR/all_res.csv")
RPS=$(awk -v t="$TOTAL_REQ" -v d="$DURATION" 'BEGIN { if (d>0) printf "%.2f", t/d; else print 0 }')
AVG_LAT=$(awk '{s+=$1; n+=1} END{ if(n>0) printf "%.4f", s/n; else print 0 }' "$TMP_DIR/all_lat.csv")
P50=$(awk 'BEGIN{c=0} {a[++c]=$1} END{ if(c>0){idx=int((c*50+99)/100); if(idx<1)idx=1; if(idx>c)idx=c; printf "%.4f", a[idx]} else print 0 }' "$TMP_DIR/all_lat.csv")
P95=$(awk 'BEGIN{c=0} {a[++c]=$1} END{ if(c>0){idx=int((c*95+99)/100); if(idx<1)idx=1; if(idx>c)idx=c; printf "%.4f", a[idx]} else print 0 }' "$TMP_DIR/all_lat.csv")
P99=$(awk 'BEGIN{c=0} {a[++c]=$1} END{ if(c>0){idx=int((c*99+99)/100); if(idx<1)idx=1; if(idx>c)idx=c; printf "%.4f", a[idx]} else print 0 }' "$TMP_DIR/all_lat.csv")
SUCCESS_RATE=$(awk -v ok="$TOTAL_OK" -v total="$TOTAL_REQ" 'BEGIN { if(total>0) printf "%.2f", (ok/total)*100; else print 0 }')
MB_SENT=$(awk -v b="$TOTAL_BYTES" 'BEGIN { printf "%.2f", b/1024/1024 }')

cat <<REPORT
=== Stress Test Healthcheck ===
Target: $URL
Method: $METHOD
HTTP version: ${HTTP_VERSION#--}
Duration: ${DURATION}s
Concurrency: $CONCURRENCY
Paths: $PATHS_CSV

Requests total: $TOTAL_REQ
Successful (2xx): $TOTAL_OK
Failed (3xx/4xx/5xx/timeout/network): $TOTAL_FAIL
Success rate: ${SUCCESS_RATE}%
Requests/sec: $RPS
Downloaded: ${MB_SENT} MiB

Latency avg: ${AVG_LAT}s
Latency p50: ${P50}s
Latency p95: ${P95}s
Latency p99: ${P99}s
REPORT

cat > output/stress_results_example.txt <<EXAMPLE
Esempio uso:
  chmod +x ./stress_crow.sh
  ./stress_crow.sh http://localhost:18080

Con parametri custom:
  CONCURRENCY=200 DURATION=60 ./stress_crow.sh http://localhost:18080

Override del path o della versione HTTP:
  PATHS_CSV='/controlli/health' HTTP_VERSION='--http1.1' ./stress_crow.sh http://localhost:18080

In parallelo, monitora Docker:
  docker stats
  docker logs -f saas_backend
EXAMPLE
