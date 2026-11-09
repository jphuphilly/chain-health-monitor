"""Wraps prometheus/rules.yml in a PrometheusRule object for kube-prometheus-stack.
Usage: python3 scripts/make_prometheusrule.py | kubectl apply -f -
"""
import pathlib, sys, yaml

root = pathlib.Path(__file__).resolve().parent.parent
rules = yaml.safe_load((root / "prometheus" / "rules.yml").read_text())
obj = {
    "apiVersion": "monitoring.coreos.com/v1",
    "kind": "PrometheusRule",
    "metadata": {"name": "chainmon", "namespace": "chainmon"},
    "spec": rules,
}
yaml.safe_dump(obj, sys.stdout, sort_keys=False)
