# Forkshift

**Play [Disaster Director](https://drcocktail.github.io/forkshift/director/).** Muse Spark authors the storm and plays it as your rival. Rewind any turn to see how a different move changes the outcome. [Play guide and evidence](DIRECTOR.md)

**Start with the [hosted demo](https://drcocktail.github.io/forkshift/) or [Rescue Arcade](Forkshift-Arcade.html)** for the process-level incident environment, then open [Redshift Branch Garden](Forkshift-Branch-Garden.html) to inspect the native signed branch receipts. [Arcade contract](ARCADE.md) · [Redshift integration](REDSHIFT.md)

Forkshift is an incident control room for an inference service. An operator can see how a worker failure changes the queue, compare recovery plans on identical traffic, and run a gated canary before touching a deployment.

## Try the interactive demo

The [narrated three-minute walkthrough](Forkshift-Narrated.mp4) starts in the game and follows the worker replay and Redshift runs. Read the [transcript](Forkshift-Narration.txt) or [download the PowerPoint with a voice clip on each slide](https://github.com/drcocktail/forkshift/releases/download/v1.2.1/Forkshift-Narrated.pptx). The [91-second earlier walkthrough](Forkshift-Demo.mp4) focuses on the synthetic queue simulator.

Open [Forkshift-Demo.html](Forkshift-Demo.html) directly. It bundles three recorded incidents and runs without a server or model download. On **A worker dies during the voice rush**, select **Meta Llama proposal**, click **Play replay**, then switch to **Emergency reroute**. Both plans rescue simulated voice traffic. The gate blocks the emergency reroute because it opens the alternate pool to batch traffic. The saved canary shows four real HTTP outcomes.

## Run locally

Python 3.10 or later. The simulator and recording viewer use the standard library.

```sh
python3 -m forkshift serve --port 8790
```

Open **http://127.0.0.1:8790**. For fresh planning and canaries, start Ollama and install both local model tags.

```sh
ollama pull llama3.1:8b
ollama pull llama3.2:3b
python3 -m forkshift run --incident rank-drop --mode llama --canary llama
```

With a Meta API key already set in `MODEL_API_KEY`, use `--mode muse` or the **Ask Muse Spark** button for a named Muse Spark proposal. That path has mocked adapter coverage. The saved recordings use local Llama.

The planner receives a human-authored incident brief and capacity summary. It proposes a plan using three typed controls for overflow, batch admission, and primary voice reservation. If the first candidate fails, the model gets one revision with the failed metrics and no answer from search. The unchanged policy, emergency reroute, and exhaustive 75-plan search are always visible.

The gate checks voice deadline attainment, batch completion, alternate usage, and traffic restrictions on three deterministic replays. A permitted canary starts a temporary primary HTTP gateway and probes it with Llama 3.1 8B, injects an HTTP 503, routes the probe to Llama 3.2 3B when approved, then probes the restored primary. It requires the same probe ID in every successful acknowledgment. The server recomputes the gate and binds the canary request to the selected plan hash.

```sh
python3 -m unittest discover -s tests -v
python3 export_demo.py
```

## Recorded evidence

| Incident | First Llama plan | One revision | Exhaustive search |
| --- | --- | --- | --- |
| Rank drop | Eligible across 3/3 replays | Unneeded | Eligible across 3/3 |
| Alternate pool budget | Blocked by the batch floor | Blocked by the voice target | Eligible across 3/3 |
| Restricted pool | Blocked by the slow-recovery batch floor | Blocked by the same floor | Eligible across 3/3 |

On the rank-drop reference trace, on-time voice rose from **39.6% to 100%** with the Llama plan. On-time batch was **50.6%**, above the 25% floor. The search plan also reached **100%** voice and completed **60.9%** of batch. The real local canary produced **200 → 503 → 200 → 200** across healthy primary, injected fault, alternate, and restored primary. [Full rank-drop recording](evidence/rank-drop.json)

The trace workload and service capacities are synthetic. A tick represents one simulated second and work is measured in fixed requests, without continuous batching or GPU kernels. The two model tags share one local Ollama instance. The canary validates the request path and response contract. GPU recovery, throughput, production safety, and model advantage over search require separate evidence.

## Contest path

**Push the Frontier** is the proposed problem statement. See [the release notes](RELEASE.md) for public links, claim scope, and verification.


## Recreate the narration

On macOS, install the local Kokoro-ONNX model and voice files described by [kokoro-onnx](https://github.com/thewh1teagle/kokoro-onnx). Then run this from the repository with their paths:

```sh
uv run --python 3.13 --with kokoro-onnx==0.6.1 --with soundfile python make_narration.py \
  --model /path/to/kokoro-v1.0.onnx --voices /path/to/voices-v1.0.bin --replace
```

The published voice is Kokoro’s `af_sarah`. The script fits each paragraph in `narration.json` to its slide and writes a new MP4 and WebVTT captions.
