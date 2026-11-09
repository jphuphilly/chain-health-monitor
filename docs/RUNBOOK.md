# Runbook

Every alert links here. The first question is always: **is it the chain, a provider, or us?**

Useful queries:

```promql
chainmon:head_age_seconds{chain="X"}        # per provider: one line rising = provider, all lines = chain
chainmon:provider_lag_seconds{chain="X"}
chainmon_probe_success
```
```logql
{app="chain-health-exporter"} | json | chain="X"
```

---

## ChainHeadStale
**Severity:** critical. **Meaning:** no provider has seen a new block for at least `max(10 × block time, 60s)`.
`ChainHeightNotAdvancing` is the same check based on block height instead of timestamps. It's the one that works for Solana when block times aren't available.

1. **Rule out "us" first.** Are other chains fresh? If every chain is stale, the problem is our network or the exporter. Go to [ChainNoHealthyProviders](#chainnohealthyproviders).
2. **Confirm outside our stack.** Check the chain's public status page and official X account, plus a third RPC or explorer we don't use. Don't trust a single explorer alone: explorer lag can look exactly like a halt.
3. **Check timing.** Did the last block arrive right before a planned upgrade or hard fork? Planned halts usually come with an announcement.
4. **Act.** In a real exchange or wallet, this is when you pause deposits and withdrawals for that chain and post on the status page. Record the start time; the dashboard annotation marks it.
5. **Recovery.** Once blocks flow again, watch for reorgs: deposits credited just before the halt need re-checking.

Provider alerts for the same chain are inhibited while this fires, so you won't get a page storm.

## ChainNoHealthyProviders
**Severity:** critical. **Meaning:** every provider for a chain is failing. We can't see the chain.

1. Is it every chain? Then the problem is our egress, DNS or exporter: `kubectl -n chainmon logs deploy/chain-health-exporter`.
2. Is it one chain? Both providers may be rate-limiting us (public endpoints do this), or the endpoint URLs changed. Run `./scripts/check-endpoints.sh` from somewhere else.
3. Fix: add or replace a provider in `exporter/config.yaml` and redeploy.

## ProviderBehind
**Severity:** warning. **Meaning:** the chain is advancing, but this provider is more than `lag_alert_seconds` behind the best one.

1. Look at its line in "Provider lag": is it steady, growing, or spiky? Growing means its node has stopped syncing.
2. Check the provider's status page.
3. Act: route traffic to the healthy provider. If it lasts more than an hour, open a ticket with the provider and attach the lag graph.

## ProviderDown
**Severity:** warning. **Meaning:** every probe to this provider failed for 3 minutes.

1. Read the error: `{app="chain-health-exporter"} | json | provider="NAME" | msg="probe error"`.
   - HTTP 429 → we're rate-limited. Lower the probe frequency or use an API key.
   - HTTP 5xx or timeout → the provider is having an incident.
   - DNS or connection refused → the endpoint moved or was retired.
2. Fail over; same as ProviderBehind.

## ProviderSlow
**Severity:** warning. p95 latency over 2s for 10 minutes. Compare against the other provider for the same chain. If both are slow, suspect our network path.

## Error budget burn
**ProviderErrorBudgetFastBurn** (critical): errors are running at 14.4× the 1% budget. That's 2% of the monthly budget per hour, so the whole budget is gone in about 2 days.
**ProviderErrorBudgetSlowBurn** (warning): 6× the budget over 6 hours.

1. Check the probe error ratio panel: is it constant errors or bursts?
2. Constant errors at a low level from a free public endpoint usually mean rate limiting. That's a capacity decision (pay for a plan or probe less often), not an incident.
3. If the budget is exhausted, freeze risky changes to whatever depends on this provider until it recovers. That's the point of an error budget.

## Postmortem template
- **Impact:** which chain or provider, start and end time (UTC), duration
- **Detection:** which alert fired, and how long after the problem started
- **Root cause:** chain, provider, or us, with the evidence (graphs and log lines)
- **What went well / what didn't**
- **Action items:** owner and date for each
