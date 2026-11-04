# Redshift Branch Garden

**A branch of agent work should carry the evidence that earns it a merge.** Branch Garden uses the local Redshift v2 Completion Engine to run and grade two isolated candidates for the same inference failure. The complete candidate can be replayed without calling the planner again.

Start with [Branch Garden](Forkshift-Branch-Garden.html) and [Rescue Arcade](Forkshift-Arcade.html). Both are standalone HTML files. The Branch Garden’s **Verify signatures** button checks the embedded Ed25519 receipts using Web Crypto. **Test a changed receipt** flips the verdict on a temporary copy and verifies that the viewer rejects it.

## What Redshift actually did

1. Read the checked-in green-light episode, where local Llama chose `try_backup` and then `repair_primary` in response to rollback. Bind the source ledger digest and ordered action digest to the candidate.
2. Prepare a signed Redshift Execution Cartridge for that trace and another for an incomplete, single-action shortcut. Each branch gets a separate subprocess, private Redshift event store, signing identity, and independently started workers. The v2 Completion Kernel selects the cartridge via a deterministic adapter and the Execution Runtime calls the typed Arcade connector.
3. Apply the same terminal oracle to both. It checks route commits, worker identity and exact golden response bodies. Redshift issues a signed completion receipt for each outcome. Forkshift selects the branch whose terminal verifier and receipt both pass.

| Live native branch | Outcome | Receipt signature | Planner calls |
| --- | --- | --- | --- |
| Try backup → repair primary | Completed, terminal check passed | Verified | 0 |
| Try backup only | Failed, terminal check rejected | Verified | 0 |

The originating local Llama episode made two planner calls, taking about 3.8 seconds in that recording. Reuse eliminated those planner calls. The live workers still performed Llama inference for the probes. The trial establishes neither an end-to-end speedup nor a general correctness improvement.

The bridge authors bounded cartridges from the supported recorded action trace and runs the native Redshift Completion Kernel and Execution Runtime. Automatic ExecutionMaker compilation and registry promotion were outside this trial. Local eligibility applies to the single tested incident contract. The private Redshift checkout and signing keys stay outside the distribution.

## Run it

From this directory, with a working Redshift v2 checkout and virtual environment:

```sh
export REDSHIFT_V2_ROOT=/absolute/path/to/redshift/v2
python3 -m forkshift.redshift_bridge --engine fixture --output /tmp/forkshift-fixture.json
python3 -m forkshift.redshift_bridge --engine ollama --output /tmp/forkshift-live.json
```

The second command needs `ollama` and the installed `llama3.2:3b` weights. Both paths use local components. The standalone demo includes the [live Redshift trial](redshift_evidence/live-branch-trial.json) and the bundle also contains the [fixture trial](redshift_evidence/branch-trial.json) and initial integration attempt. The bridge validates the receipt signatures before selecting a branch.

## Pitch

> People already know how to branch files. Forkshift branches a piece of agent work. One timeline turns green and then drops the next request. The other recovers, respects the routing contract, and earns a signed receipt. Redshift can replay the verified action sequence without asking the planner again.

For the next release, run a predeclared cohort of unseen faults, measure paired planning and execution latency, and pin the contract and input snapshot in a reusable promotion record. Then evaluate whether an approved cartridge still holds when live scheduler behavior and topology change.
