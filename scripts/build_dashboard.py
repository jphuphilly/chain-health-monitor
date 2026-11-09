"""Generates dashboards/chain-health.json (Grafana dashboard).

Edit this file, not the JSON:  python3 scripts/build_dashboard.py
Datasource UIDs expected: "prometheus" and "loki".
"""

import json
import pathlib

PROM = {"type": "prometheus", "uid": "prometheus"}
LOKI = {"type": "loki", "uid": "loki"}
CH = '{chain=~"$chain"}'

_id = 0


def nid():
    global _id
    _id += 1
    return _id


def target(expr, legend="", ref="A", instant=False):
    t = {"datasource": PROM, "expr": expr, "legendFormat": legend, "refId": ref}
    if instant:
        t["instant"] = True
        t["range"] = False
    return t


def thresholds(steps):
    return {"mode": "absolute",
            "steps": [{"color": c, "value": v} for c, v in steps]}


def stat(title, expr, legend, x, y, w, h, unit, steps, desc="", decimals=None):
    p = {
        "id": nid(), "type": "stat", "title": title, "description": desc,
        "datasource": PROM, "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "targets": [target(expr, legend, instant=True)],
        "fieldConfig": {"defaults": {"unit": unit, "thresholds": thresholds(steps),
                                     "color": {"mode": "thresholds"}}, "overrides": []},
        "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                    "colorMode": "background", "graphMode": "none", "textMode": "value_and_name",
                    "justifyMode": "center", "orientation": "auto"},
    }
    if decimals is not None:
        p["fieldConfig"]["defaults"]["decimals"] = decimals
    return p


def ts(title, targets, x, y, w, h, unit, desc="", steps=None, thresh_style="off"):
    return {
        "id": nid(), "type": "timeseries", "title": title, "description": desc,
        "datasource": PROM, "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "targets": targets,
        "fieldConfig": {"defaults": {
            "unit": unit,
            "custom": {"lineWidth": 2, "fillOpacity": 8, "showPoints": "never",
                       "thresholdsStyle": {"mode": thresh_style}},
            "thresholds": thresholds(steps or [["green", None]]),
        }, "overrides": []},
        "options": {"legend": {"displayMode": "table", "placement": "right",
                               "calcs": ["lastNotNull", "max"]},
                    "tooltip": {"mode": "multi", "sort": "desc"}},
    }


def row(title, y):
    return {"id": nid(), "type": "row", "title": title, "collapsed": False,
            "gridPos": {"x": 0, "y": y, "w": 24, "h": 1}, "panels": []}


panels = []
y = 0

# ---- Overview ----
panels.append(row("Right now", y)); y += 1
panels.append(stat(
    "Chain freshness (seconds since newest block, best provider)",
    f"chainmon:chain_head_age_seconds{CH}", "{{chain}}", 0, y, 12, 5, "s",
    [["green", None], ["yellow", 30], ["red", 60]],
    desc="Age of the newest block seen by ANY provider. Red here means the chain itself may be halted."))
panels.append(stat(
    "Healthy providers",
    f"sum by (chain) (chainmon_probe_success{CH}) / count by (chain) (chainmon_probe_success{CH})",
    "{{chain}}", 12, y, 8, 5, "percentunit",
    [["red", None], ["yellow", 0.5], ["green", 1]]))
panels.append(stat(
    "Firing alerts", 'count(ALERTS{alertstate="firing", alertname=~"Chain.*|Provider.*"}) or vector(0)',
    "", 20, y, 4, 5, "none", [["green", None], ["red", 1]]))
y += 5

# ---- Freshness & lag ----
panels.append(row("Is it the chain, or the provider?", y)); y += 1
panels.append(ts(
    "Head age per provider",
    [target(f"chainmon:head_age_seconds{CH}", "{{chain}} / {{provider}}")],
    0, y, 12, 8, "s",
    desc="Every line rising together = chain halt. One line rising alone = provider problem.",
    steps=[["green", None], ["red", 60]], thresh_style="dashed"))
panels.append(ts(
    "Provider lag behind best provider",
    [target(f"chainmon:provider_lag_seconds{CH}", "{{chain}} / {{provider}}")],
    12, y, 12, 8, "s",
    desc="Blocks behind the best provider x normal block time.",
    steps=[["green", None], ["red", 30]], thresh_style="dashed"))
y += 8

# ---- RPC health ----
panels.append(row("RPC health", y)); y += 1
panels.append(ts(
    "p95 RPC latency",
    [target(f"chainmon:rpc_latency_seconds:p95_5m{CH}", "{{chain}} / {{provider}}")],
    0, y, 12, 8, "s", steps=[["green", None], ["red", 2]], thresh_style="dashed"))
panels.append(ts(
    "Probe error ratio (5m)",
    [target(f"chainmon:probe_error_ratio:rate5m{CH}", "{{chain}} / {{provider}}")],
    12, y, 12, 8, "percentunit"))
y += 8

# ---- SLOs ----
panels.append(row("SLOs (30-day window)", y)); y += 1
panels.append(stat(
    "Chain freshness SLO (target 99.9%)",
    f"avg_over_time(chainmon:chain_fresh{CH}[30d])", "{{chain}}", 0, y, 8, 6, "percentunit",
    [["red", None], ["yellow", 0.999], ["green", 0.9995]], decimals=3,
    desc="Share of the last 30 days the chain head was fresh."))
panels.append(stat(
    "Provider availability SLO (target 99%)",
    f"1 - (sum by (chain, provider) (increase(chainmon_probes_total{{chain=~\"$chain\", result!=\"success\"}}[30d])) "
    f"or sum by (chain, provider) (increase(chainmon_probes_total{CH}[30d])) * 0) "
    f"/ sum by (chain, provider) (increase(chainmon_probes_total{CH}[30d]))",
    "{{chain}} / {{provider}}", 8, y, 8, 6, "percentunit",
    [["red", None], ["yellow", 0.99], ["green", 0.995]], decimals=2))
panels.append(stat(
    "Error budget remaining (1% budget)",
    f"clamp_min(1 - ((sum by (chain, provider) (increase(chainmon_probes_total{{chain=~\"$chain\", result!=\"success\"}}[30d])) "
    f"or sum by (chain, provider) (increase(chainmon_probes_total{CH}[30d])) * 0) "
    f"/ sum by (chain, provider) (increase(chainmon_probes_total{CH}[30d]))) / 0.01, 0)",
    "{{chain}} / {{provider}}", 16, y, 8, 6, "percentunit",
    [["red", None], ["yellow", 0.25], ["green", 0.5]], decimals=0,
    desc="100% = no budget used. 0% = SLO breached for the window."))
y += 6

# ---- Logs ----
panels.append(row("Events (Loki)", y)); y += 1
panels.append({
    "id": nid(), "type": "logs", "title": "Exporter warnings: probe errors, providers falling behind / recovering",
    "datasource": LOKI, "gridPos": {"x": 0, "y": y, "w": 24, "h": 10},
    "targets": [{"datasource": LOKI, "refId": "A",
                 "expr": '{app="chain-health-exporter"} | json | chain=~"$chain" | level=~"WARNING|INFO" | msg!="exporter started"'}],
    "options": {"showTime": True, "wrapLogMessage": True, "sortOrder": "Descending",
                "enableLogDetails": True, "prettifyLogMessage": False},
})

dashboard = {
    "uid": "chain-health",
    "title": "Chain Health",
    "description": "External synthetic monitoring of blockchains across multiple RPC providers",
    "tags": ["chainmon", "slo"],
    "timezone": "browser",
    "schemaVersion": 39,
    "version": 1,
    "editable": True,
    "refresh": "10s",
    "time": {"from": "now-1h", "to": "now"},
    "templating": {"list": [{
        "name": "chain", "label": "Chain", "type": "query", "datasource": PROM,
        "query": {"query": "label_values(chainmon_head_block, chain)", "refId": "chain"},
        "definition": "label_values(chainmon_head_block, chain)",
        "refresh": 2, "multi": True, "includeAll": True,
        "current": {"selected": True, "text": ["All"], "value": ["$__all"]},
    }]},
    "annotations": {"list": [{
        "name": "Alerts", "datasource": PROM, "enable": True, "iconColor": "red",
        "expr": 'ALERTS{alertstate="firing", alertname=~"Chain.*|Provider.*"}',
        "titleFormat": "{{alertname}}", "textFormat": "{{chain}} {{provider}}", "step": "30s",
    }]},
    "panels": panels,
}

out = pathlib.Path(__file__).resolve().parent.parent / "dashboards" / "chain-health.json"
out.write_text(json.dumps(dashboard, indent=2) + "\n")
print(f"wrote {out}")
