#!/usr/bin/env bash
# Deploys the full stack to the cluster your kubectl points at (e.g. Linode LKE).
#   IMAGE=ghcr.io/<github-user>/chain-health-exporter:latest ./scripts/k8s-deploy.sh
# Safe to re-run: every step is an upgrade/apply.
set -euo pipefail
: "${IMAGE:?set IMAGE, e.g. IMAGE=ghcr.io/<github-user>/chain-health-exporter:latest}"
cd "$(dirname "$0")/.."
K=deploy/k8s

echo "==> cluster: $(kubectl config current-context)"

echo "==> helm repos"
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts >/dev/null 2>&1 || true
helm repo add grafana https://grafana.github.io/helm-charts >/dev/null 2>&1 || true
helm repo update >/dev/null

kubectl create namespace monitoring --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -f $K/namespace.yaml

echo "==> kube-prometheus-stack (Prometheus, Alertmanager, Grafana)"
helm upgrade --install kps prometheus-community/kube-prometheus-stack \
  -n monitoring -f $K/values-kube-prometheus-stack.yaml --wait --timeout 15m

echo "==> Loki"
helm upgrade --install loki grafana/loki -n monitoring -f $K/values-loki.yaml --wait --timeout 10m

echo "==> Alloy (log shipper)"
helm upgrade --install alloy grafana/alloy -n monitoring -f $K/values-alloy.yaml --wait --timeout 5m

echo "==> config, rules, dashboard"
kubectl -n chainmon create configmap chainmon-config \
  --from-file=config.yaml=exporter/config.yaml --dry-run=client -o yaml | kubectl apply -f -
kubectl -n chainmon create configmap mock-rpc-script \
  --from-file=mock_rpc.py=scripts/mock_rpc.py --dry-run=client -o yaml | kubectl apply -f -
python3 scripts/make_prometheusrule.py | kubectl apply -f -
kubectl -n monitoring create configmap chain-health-dashboard \
  --from-file=chain-health.json=dashboards/chain-health.json --dry-run=client -o yaml \
  | kubectl label --local -f - grafana_dashboard=1 -o yaml | kubectl apply -f -

echo "==> exporter + mock chain"
HASH=$(sha256sum exporter/config.yaml | cut -c1-12)
sed -e "s#IMAGE#${IMAGE}#" -e "s#CONFIG_HASH#${HASH}#" $K/exporter.yaml | kubectl apply -f -
kubectl apply -f $K/mock-rpc.yaml
kubectl -n chainmon rollout status deploy/chain-health-exporter --timeout 3m
kubectl -n chainmon rollout status deploy/mock-rpc --timeout 3m

cat <<MSG

Done. Verify:
  ./scripts/verify-k8s.sh
Grafana:
  kubectl -n monitoring port-forward svc/kps-grafana 3000:80   ->  http://localhost:3000
MSG
