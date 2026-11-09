"""chain-health-exporter

Probes several public blockchains through more than one RPC provider each and
exposes Prometheus metrics, so you can tell three situations apart:

  1. One provider is slow, failing, or behind  -> provider problem
  2. All providers agree the chain stopped     -> chain halt
  3. Everything is fine

Metrics (all labelled chain, provider unless noted):
  chainmon_head_block                 latest block/slot number the provider reports
  chainmon_head_timestamp_seconds     unix time of that block (EVM) / slot (Solana)
  chainmon_probe_success              1 if the last probe worked, else 0
  chainmon_probes_total{result}       counter of probes by result (success|error|timeout)
  chainmon_rpc_duration_seconds       histogram of probe latency
  chainmon_expected_block_time_seconds{chain}  from config, used by alert rules
  chainmon_lag_alert_seconds{chain}            from config, used by alert rules

Logs are one JSON object per line on stdout (Loki picks them up).
"""

import asyncio
import json
import logging
import os
import sys
import time

import httpx
import yaml
from prometheus_client import Counter, Gauge, Histogram, start_http_server

# ---------- logging: JSON lines ----------


class JsonFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
            "level": record.levelname,
            "msg": record.getMessage(),
        }
        payload.update(getattr(record, "fields", {}))
        return json.dumps(payload)


log = logging.getLogger("chainmon")
_h = logging.StreamHandler(sys.stdout)
_h.setFormatter(JsonFormatter())
log.addHandler(_h)
log.setLevel(os.environ.get("LOG_LEVEL", "INFO"))


def event(level, msg, **fields):
    log.log(level, msg, extra={"fields": fields})


# ---------- metrics ----------

LABELS = ["chain", "provider"]
HEAD_BLOCK = Gauge("chainmon_head_block", "Latest block or slot reported by provider", LABELS)
HEAD_TS = Gauge("chainmon_head_timestamp_seconds", "Unix timestamp of the latest block", LABELS)
PROBE_OK = Gauge("chainmon_probe_success", "1 if the last probe succeeded", LABELS)
PROBES = Counter("chainmon_probes", "Probes by result", LABELS + ["result"])
LATENCY = Histogram(
    "chainmon_rpc_duration_seconds",
    "RPC probe latency",
    LABELS,
    buckets=(0.05, 0.1, 0.2, 0.3, 0.5, 0.75, 1, 1.5, 2, 3, 5, 10),
)
EXPECTED_BT = Gauge(
    "chainmon_expected_block_time_seconds", "Configured normal block time", ["chain"]
)
LAG_ALERT = Gauge(
    "chainmon_lag_alert_seconds", "Configured provider-lag alert threshold", ["chain"]
)


# ---------- probes ----------


class ProbeError(Exception):
    pass


async def rpc(client, url, method, params):
    r = await client.post(
        url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    )
    r.raise_for_status()
    body = r.json()
    if "error" in body:
        raise ProbeError(f"{method}: {body['error']}")
    return body["result"]


async def probe_evm(client, url):
    blk = await rpc(client, url, "eth_getBlockByNumber", ["latest", False])
    if not blk:
        raise ProbeError("eth_getBlockByNumber returned null")
    return int(blk["number"], 16), int(blk["timestamp"], 16)


async def probe_solana(client, url):
    slot = await rpc(client, url, "getSlot", [{"commitment": "confirmed"}])
    try:
        ts = await rpc(client, url, "getBlockTime", [slot])
    except ProbeError:
        ts = None  # block time not always available for the newest slot
    return int(slot), (int(ts) if ts else None)


PROBES_BY_TYPE = {"evm": probe_evm, "solana": probe_solana}


# ---------- main loop ----------


class ChainState:
    """Remembers which providers are currently 'behind' so we log transitions, not spam."""

    def __init__(self):
        self.behind = set()
        self.heads = {}


def mark_failed(chain, name, state, result, msg, **fields):
    """A failed provider must drop out of the head/lag maths.

    Otherwise its last (frozen) head lingers and can look like the 'best' view
    of the chain, which skews lag and freshness.
    """
    labels = dict(chain=chain, provider=name)
    PROBES.labels(result=result, **labels).inc()
    PROBE_OK.labels(**labels).set(0)
    for g in (HEAD_BLOCK, HEAD_TS):
        try:
            g.remove(chain, name)
        except KeyError:
            pass
    state.heads.pop(name, None)
    event(logging.WARNING, msg, chain=chain, provider=name, **fields)


async def probe_one(client, chain, prov, ctype, state):
    name, url = prov["name"], prov["url"]
    labels = dict(chain=chain, provider=name)
    start = time.perf_counter()
    try:
        head, ts = await PROBES_BY_TYPE[ctype](client, url)
    except httpx.TimeoutException:
        mark_failed(chain, name, state, "timeout", "probe timeout")
        return
    except Exception as e:  # noqa: BLE001 - we want every failure counted
        mark_failed(chain, name, state, "error", "probe error",
                    error=(str(e).splitlines() or ["?"])[0][:300])
        return
    finally:
        LATENCY.labels(**labels).observe(time.perf_counter() - start)

    PROBES.labels(result="success", **labels).inc()
    PROBE_OK.labels(**labels).set(1)
    HEAD_BLOCK.labels(**labels).set(head)
    if ts:
        HEAD_TS.labels(**labels).set(ts)
    state.heads[name] = head


def check_lag(chain, cfg, state):
    """Log when a provider falls behind the best provider, and when it recovers."""
    if len(state.heads) < 2:
        return
    best = max(state.heads.values())
    threshold_blocks = max(1, int(cfg["lag_alert_seconds"] / cfg["block_time_seconds"]))
    for name, head in state.heads.items():
        lag = best - head
        if lag >= threshold_blocks and name not in state.behind:
            state.behind.add(name)
            event(logging.WARNING, "provider behind", chain=chain, provider=name,
                  lag_blocks=lag, best_head=best)
        elif lag < threshold_blocks and name in state.behind:
            state.behind.discard(name)
            event(logging.INFO, "provider recovered", chain=chain, provider=name,
                  lag_blocks=lag)


async def chain_loop(client, chain, cfg, interval):
    state = ChainState()
    EXPECTED_BT.labels(chain=chain).set(cfg["block_time_seconds"])
    LAG_ALERT.labels(chain=chain).set(cfg["lag_alert_seconds"])
    while True:
        await asyncio.gather(
            *(probe_one(client, chain, p, cfg["type"], state) for p in cfg["providers"])
        )
        check_lag(chain, cfg, state)
        await asyncio.sleep(interval)


async def main():
    path = os.environ.get("CONFIG_PATH", "config.yaml")
    with open(path) as f:
        conf = yaml.safe_load(f)
    port = int(os.environ.get("PORT", conf.get("port", 9105)))
    interval = float(conf.get("interval_seconds", 10))
    timeout = float(conf.get("timeout_seconds", 5))

    start_http_server(port)
    event(logging.INFO, "exporter started", port=port, chains=list(conf["chains"]))

    async with httpx.AsyncClient(
        timeout=timeout, headers={"User-Agent": "chain-health-exporter/1.0"}
    ) as client:
        await asyncio.gather(
            *(chain_loop(client, name, c, interval) for name, c in conf["chains"].items())
        )


if __name__ == "__main__":
    asyncio.run(main())
