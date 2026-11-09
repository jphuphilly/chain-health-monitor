#!/usr/bin/env bash
# Hits every RPC URL in exporter/config.yaml once and prints the head block.
# Run this before deploying: public endpoints come and go.
set -u
CONFIG="${1:-exporter/config.yaml}"
python3 - "$CONFIG" <<'PY'
import json, sys, urllib.request, yaml
conf = yaml.safe_load(open(sys.argv[1]))
for chain, c in conf["chains"].items():
    for p in c["providers"]:
        method = "eth_blockNumber" if c["type"] == "evm" else "getSlot"
        req = urllib.request.Request(p["url"], data=json.dumps(
            {"jsonrpc": "2.0", "id": 1, "method": method, "params": []}).encode(),
            headers={"content-type": "application/json", "user-agent": "chain-health-exporter/1.0"})
        try:
            r = json.load(urllib.request.urlopen(req, timeout=8))
            res = r.get("result")
            head = int(res, 16) if isinstance(res, str) else res
            print(f"OK    {chain:10} {p['name']:12} head={head}")
        except Exception as e:
            print(f"FAIL  {chain:10} {p['name']:12} {e}")
PY
