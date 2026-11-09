# Interview walkthrough (5–7 minutes)

## The 30-second pitch

**Healthcare or general SRE roles (e.g. TherapyNotes):**
> "I built external synthetic monitoring for a set of critical dependencies I don't control, with SLOs and burn-rate alerting. The point is that it tells you whether the dependency is down or just one route to it is down, so on-call fails over instead of declaring an outage. I used public blockchains as the test subject because they're always on and produce real incidents for free. The same design applies to an EHR's dependencies: e-prescribing, the clearinghouse, payments, or your own API from several regions. It's synthetic probing only, so no patient data is ever touched."

**Crypto roles (Alpen, Coinbase, Kraken, P2P.org):**
> "Exchanges and wallets need to know within minutes when a chain halts, so they can pause deposits. Equally, they need to avoid pausing a healthy chain because one RPC provider fell behind. This monitors five chains through two providers each. It alerts on a chain halt only when every provider agrees, and alerts on a single provider separately."

## Live demo

Open the dashboard. Have a terminal with `mock-rpc` reachable (local: port 8545; cluster: `kubectl -n chainmon port-forward svc/mock-rpc 8545:8545`).

1. **Top row:** "Freshness per chain, healthy providers, firing alerts. Green is the normal state."
2. **Break one provider:** `curl "localhost:8545/control?provider=bravo&mode=lag"`
   - "Watch Head age: one line climbs and the other stays flat. The chain is fine; bravo is behind."
   - The Loki panel shows `provider behind` within seconds. The alert waits 5 minutes on purpose, so a brief blip doesn't page anyone.
3. **Halt the chain:** `curl "localhost:8545/control?chain=halt"`
   - "Now every line climbs together. That pattern is a chain halt, and it pages as critical."
   - "Alertmanager inhibits provider alerts on the same chain, so on-call gets one page, not five."
4. **Recover:** `curl "localhost:8545/control?chain=run"` and `...provider=bravo&mode=ok`. Show the recovery log line and the alert annotation on the graph.
5. **Show the tests:** `promtool test rules prometheus/rules_test.yml`. "The alert logic has unit tests in CI, so a rule change can't silently break detection."

Start the halt early if you need the alert to actually be firing on screen: it takes 3–4 minutes.

## Questions to expect, and honest answers

**Why two providers per chain?**
One source can't distinguish "the chain stopped" from "my source stopped." In June 2026, block explorers showed no new Zcash blocks for hours, and infrastructure providers said the network was fine; the explorers were stale. A single-source monitor would have raised a false halt.

**What went wrong while building it?** (Use this one. Interviewers like it.)
"My first version kept a failed provider's last block number as a metric. Its frozen value stayed in the 'best provider' calculation, which distorted lag and freshness. My smoke test caught it. Now a failed probe removes that provider's head metrics, and there's a separate `ChainNoHealthyProviders` alert so 'we're blind' isn't confused with 'the chain halted.'"

**Why burn-rate alerts instead of "error rate > X"?**
A fixed threshold either pages on harmless blips or misses slow leaks. Burn rate ties the alert to how fast the monthly error budget is being spent. The two windows make it both reliable (the long window) and quick to resolve (the short window).

**Why both a timestamp check and a block-height check?**
Timestamps give "how stale" in seconds, but Solana doesn't always return a block time for the newest slot. Height not advancing works for every chain.

**How would you run this in production?**
Exporters in at least two regions, HA Prometheus and Alertmanager, long-term storage (Thanos or Mimir), provider API keys instead of public endpoints, and synthetic transactions to measure write-path latency, not just reads.

**What did the real data show?** *(Fill this in after it has run for 48 hours. Check the error-ratio panel for rate limiting on free endpoints, which is a real finding worth mentioning.)*

## Before the interview

- Read `exporter/app.py` and `prometheus/rules.yml` top to bottom, and be able to explain every rule out loud.
- Take a screenshot of the dashboard during the halt demo, in case the live demo fails.
- Make sure it has been running for at least 24 hours, so the SLO panels have data.
