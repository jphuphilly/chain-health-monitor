"""Fake EVM JSON-RPC chain for testing and live demos.

Serves one fake chain ("demo") through several fake providers:
    http://localhost:8545/alpha
    http://localhost:8545/bravo

A new block appears every 2 seconds. You can break things on purpose:

    curl "localhost:8545/control?provider=bravo&mode=lag"    # bravo falls 60 blocks behind
    curl "localhost:8545/control?provider=bravo&mode=down"   # bravo returns HTTP 500
    curl "localhost:8545/control?provider=bravo&mode=slow"   # bravo answers in 3s
    curl "localhost:8545/control?provider=bravo&mode=ok"     # bravo back to normal
    curl "localhost:8545/control?chain=halt"                 # the whole chain stops
    curl "localhost:8545/control?chain=run"                  # chain resumes
    curl "localhost:8545/control"                            # show current state

Standard library only, so it runs anywhere with Python 3.
"""

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

BLOCK_TIME = float(os.environ.get("BLOCK_TIME", "2"))
GENESIS = time.time() - 1_000_000 * BLOCK_TIME  # start around block 1,000,000

state = {"halted_at": None, "providers": {"alpha": "ok", "bravo": "ok"}}
lock = threading.Lock()


def chain_head():
    now = state["halted_at"] or time.time()
    number = int((now - GENESIS) / BLOCK_TIME)
    return number, int(GENESIS + number * BLOCK_TIME)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # keep output quiet
        pass

    def _send(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urlparse(self.path)
        if url.path != "/control":
            return self._send(404, {"error": "not found"})
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        with lock:
            if q.get("chain") == "halt" and not state["halted_at"]:
                state["halted_at"] = time.time()
            elif q.get("chain") == "run" and state["halted_at"]:
                # resume without a gap: shift genesis forward by the halted time
                global GENESIS
                GENESIS += time.time() - state["halted_at"]
                state["halted_at"] = None
            if "provider" in q and "mode" in q:
                state["providers"][q["provider"]] = q["mode"]
            self._send(200, {"halted": bool(state["halted_at"]), "providers": state["providers"],
                             "head": chain_head()[0]})

    def do_POST(self):
        provider = urlparse(self.path).path.strip("/")
        mode = state["providers"].get(provider)
        if mode is None:
            return self._send(404, {"error": "unknown provider"})
        length = int(self.headers.get("content-length", 0))
        req = json.loads(self.rfile.read(length) or b"{}")
        if mode == "down":
            return self._send(500, {"error": "simulated outage"})
        if mode == "slow":
            time.sleep(3)
        number, ts = chain_head()
        if mode == "lag":
            number -= 60
            ts -= int(60 * BLOCK_TIME)
        method = req.get("method")
        if method == "eth_blockNumber":
            result = hex(number)
        elif method == "eth_getBlockByNumber":
            result = {"number": hex(number), "timestamp": hex(ts)}
        else:
            return self._send(200, {"jsonrpc": "2.0", "id": req.get("id"),
                                    "error": {"code": -32601, "message": "method not found"}})
        self._send(200, {"jsonrpc": "2.0", "id": req.get("id"), "result": result})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8545"))
    print(f"mock chain on :{port}  providers={list(state['providers'])}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
