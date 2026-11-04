# Forkshift release

- [Public source](https://github.com/drcocktail/forkshift)
- [Interactive demo and walkthrough](https://drcocktail.github.io/forkshift/)
- [Direct three-minute video](https://drcocktail.github.io/forkshift/Forkshift-Rescue-Arcade.mp4)
- [Disaster Director game](https://drcocktail.github.io/forkshift/director/)
- [Rescue Arcade](https://drcocktail.github.io/forkshift/Forkshift-Arcade.html)
- [Redshift Branch Garden](https://drcocktail.github.io/forkshift/Forkshift-Branch-Garden.html)

The hosted demos replay recorded episodes. Run the Python server to start new local episodes. A fresh Redshift trial requires access to a compatible Redshift v2 checkout. The public release includes the Forkshift adapter, public receipt data and verification UI.

## Disaster Director

The browser game plays a saved model-authored level without a key. Rewind from any completed turn, compare your run with its ghost, or load an imported tape. The local cockpit can author a new storm from a short pitch. [Game guide and evidence](DIRECTOR.md)

## What the worker drill establishes

Forkshift runs a process-level inference incident with two private Ollama servers and synthetic golden requests. A recovery can pass the task check and fail the separate routing safety check. The green-light trap kills the backup worker after its canary and route switch. The runtime rolls back on the failed request, and the recorded Llama agent chooses to repair the primary.

For the same trap, Redshift v2 runs the full recovery trace and an incomplete shortcut in isolated local branches. The terminal verifier passes the full trace and rejects the shortcut. Both native receipt signatures verify. The successful reuse path removes two planner calls in this recorded incident. The result is scoped to the tested local environment, with manually authored cartridges and local branch selection. End-to-end speed, unseen faults and registry promotion are follow-on work.

## Verification

```sh
python3 -m unittest discover -s tests -v
python3 -m forkshift.arcade verify arcade_evidence/final/*.json
```

[Arcade contract and evidence](ARCADE.md) · [Redshift reproduction](REDSHIFT.md)
