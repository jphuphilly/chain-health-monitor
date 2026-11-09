#!/usr/bin/env bash
# Checks each layer in order. The first FAIL tells you where to look.
set -uo pipefail
pass(){ echo "PASS  $1"; }
fail(){ echo "FAIL  $1"; FAILED=1; }
FAILED=0

kubectl -n chainmon get deploy chain-health-exporter -o jsonpath='{.status.readyReplicas}' | grep -q 1 \
  && pass "exporter pod ready" || fail "exporter pod not ready (kubectl -n chainmon describe pod -l app=chain-health-exporter)"

kubectl -n chainmon port-forward svc/chain-health-exporter 19105:9105 >/dev/null 2>&1 & PF1=$!
kubectl -n monitoring port-forward svc/kps-kube-prometheus-stack-prometheus 19090:9090 >/dev/null 2>&1 & PF2=$!
sleep 4

N=$(curl -s localhost:19105/metrics | grep -c '^chainmon_head_block{')
[ "$N" -gt 0 ] && pass "exporter reports $N chain/provider heads" || fail "exporter /metrics has no chainmon_head_block"

q(){ curl -s --data-urlencode "query=$1" localhost:19090/api/v1/query | python3 -c 'import json,sys;print(len(json.load(sys.stdin)["data"]["result"]))'; }
[ "$(q 'up{job=~".*chain-health-exporter.*"} == 1')" -gt 0 ] && pass "Prometheus is scraping the exporter" \
  || fail "Prometheus not scraping (check ServiceMonitor; Prometheus UI > Status > Targets)"
[ "$(q 'chainmon:chain_head_age_seconds')" -gt 0 ] && pass "recording rules are evaluating" \
  || fail "no recording-rule output (kubectl -n chainmon get prometheusrule chainmon)"

kill $PF1 $PF2 2>/dev/null
kubectl -n monitoring logs deploy/alloy --tail=50 2>/dev/null | grep -qi "error" \
  && echo "WARN  Alloy logged errors: kubectl -n monitoring logs deploy/alloy" || pass "Alloy running without errors"
echo "Then in Grafana > Explore > Loki run:  {app=\"chain-health-exporter\"}"
exit $FAILED
