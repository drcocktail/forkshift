# Disaster Director

**[Play the level Muse wrote. Race its ghost.](https://drcocktail.github.io/forkshift/director/)** A floating night market loses gravity. Pip is hit by a runaway lantern, and Boba goes offline during fireworks. Save live orders, keep sealed recipes with Pip, and spend your three sparks where they count. Rewind any completed turn to see what one different move changes.

[Moonlight Meltdown](https://drcocktail.github.io/forkshift/director/?level=moonlight) is the original concert level and remains playable from the level menu.

## A director and a rival

A live **Muse Spark 1.3** request turned the night-market pitch into [twelve playable turns](director/level.json), including incoming traffic, worker capacities, and event captions. A second Muse request saw that exact level and chose [twelve moves](director/muse-ghost.json). The browser runs those moves through the same engine used for the human player and calculates the score.

| Same 47-packet tape | On time | Missed | Private leaks | Points |
| --- | ---: | ---: | ---: | ---: |
| Autopilot | 43 | 4 | 10 | −39 |
| Muse Spark ghost | 44 | 3 | 0 | 161 |
| Best clean route found by exhaustive search | 47 | 0 | 0 | 185 |

[Recorded inputs and replay comparison](director/evidence/replay-comparison.json). Delivered counts include packets sent to the wrong worker, which are counted separately as leaks and penalized in the score. The [original incomplete Muse attempt](director/evidence/muse-attempt-1.json) is also retained. Moonlight Meltdown was authored with local Meta Llama 3.1 8B.

## Author another storm

Start Ollama with `llama3.1:8b` installed, launch the local server, and enter a pitch at http://127.0.0.1:8792/director/.

```sh
python3 -m forkshift serve --port 8792
```

The CLI can save tapes for the in-game importer. With `MODEL_API_KEY` already set in your shell, an explicit Muse authoring or ghost command makes one Model API request each.

```sh
python3 -m forkshift.director --backend muse --brief 'A storm hits a midnight bakery' --output /tmp/bakery-tape.json
python3 -m forkshift.director --ghost-for /tmp/bakery-tape.json --output /tmp/bakery-ghost.json
node --test director/engine.test.mjs
node director/solve.mjs
```

The hosted game uses the saved recordings and runs in the browser. Its packet traffic and capacities are simulated. The separate Rescue Arcade runs real local worker processes.
