# Disaster Director

**[Play the game](https://drcocktail.github.io/forkshift/director/).** A confetti cannon takes Pip offline during a moon concert. Save live audio, route sealed messages through Pip, and decide when to spend your three sparks. Rewind to any completed turn. Your old choices play alongside yours as a ghost on the same storm.

## Where the storm came from

We gave local Meta Llama 3.1 8B a short concert-disaster pitch. It returned the twelve packet waves, worker capacities and event captions in [the published tape](director/level.json). The game uses those numbers directly. Turn decisions and replays run in the browser with no inference calls. One Meta Model API authoring attempt ended without a usable level and is retained as [attempt evidence](director/evidence/muse-attempt-1.json).

Autopilot sends 33 packets on time and leaks two sealed messages. Searching the safe move choices on that exact tape finds a route that sends 39 packets on time with zero leaks and one missed packet. [Replay comparison](director/evidence/replay-comparison.json)

## Author another storm

Start Ollama with `llama3.1:8b` installed, then launch the local app:

```sh
python3 -m forkshift serve --port 8792
```

Open http://127.0.0.1:8792/director/ and enter a short pitch. To save a reusable tape from the command line:

```sh
python3 -m forkshift.director --backend llama --brief 'A storm hits a midnight bakery' --output /tmp/bakery-tape.json
node --test director/engine.test.mjs
node director/solve.mjs
```

Load the saved tape through the game's help panel. The game's packet traffic and capacities are simulated. The separate Rescue Arcade runs real local worker processes.
