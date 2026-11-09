#!/usr/bin/env bash
# End-to-end check without Docker or a cluster:
# starts the fake chain + exporter, breaks a provider, and checks the exporter noticed.
set -euo pipefail
cd "$(dirname "$0")/.."
LOG=$(mktemp)
cleanup(){ kill ${MOCK:-} ${EXP:-} 2>/dev/null || true; }
trap cleanup EXIT

PORT=18545 python3 scripts/mock_rpc.py >/dev/null 2>&1 & MOCK=$!
sed 's/localhost:8545/localhost:18545/; s/^port: 9105/port: 19105/; s/interval_seconds: 5/interval_seconds: 1/' \
  exporter/config.demo.yaml > "$LOG.yaml"
CONFIG_PATH="$LOG.yaml" python3 exporter/app.py > "$LOG" 2>&1 & EXP=$!
sleep 4

m(){ curl -s localhost:19105/metrics; }
fail(){ echo "FAIL: $1"; echo "--- exporter log"; cat "$LOG"; exit 1; }

m | grep -q 'chainmon_head_block{chain="demo",provider="alpha"}' || fail "no head metric"
m | grep -q 'chainmon_probe_success{chain="demo",provider="bravo"} 1.0' || fail "bravo not healthy at start"
echo "PASS healthy chain reported"

curl -s "localhost:18545/control?provider=bravo&mode=lag" >/dev/null; sleep 3
grep -q '"msg": "provider behind".*"provider": "bravo"' "$LOG" || fail "lag not logged"
echo "PASS lagging provider detected and logged"

curl -s "localhost:18545/control?provider=bravo&mode=ok" >/dev/null; sleep 3
grep -q '"msg": "provider recovered"' "$LOG" || fail "recovery not logged"
echo "PASS recovery logged"

curl -s "localhost:18545/control?provider=alpha&mode=down" >/dev/null; sleep 3
m | grep -q 'chainmon_probe_success{chain="demo",provider="alpha"} 0.0' || fail "outage not reflected"
m | grep -q 'chainmon_head_block{chain="demo",provider="alpha"}' && fail "failed provider still reports a head"
m | grep -q 'chainmon_probes_total{chain="demo",provider="alpha",result="error"}' || fail "errors not counted"
echo "PASS outage counted and failed provider removed from head maths"
echo "ALL PASSED"
