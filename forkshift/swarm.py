"""Run independent Muse scouts, then fork one route at a measured mistake."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

from .director import GHOST_ACTIONS, validate
from .model import MUSE_MODEL, generate_muse

DIRECTOR = Path(__file__).resolve().parents[1] / 'director'
SCOUTS = (
    ('sentinel', 'Lantern Keeper', 'Protect sealed recipes and forecast pressure on Pip.'),
    ('radio', 'Radio Runner', 'Track live orders turn by turn and prioritize the oldest calls.'),
    ('engineer', 'Spark Mechanic', 'Plan the three sparks around future worker outages.'),
    ('quartermaster', 'Dumpling Courier', 'Track backlog and maximize all deliveries without leaks.'),
)
REPAIRERS = (
    ('rewind', 'Rewind Ranger', 'Work through the failure and trace which packet will expire next.'),
    ('crosscheck', 'Crosscheck Fox', 'Check the remaining capacities and preserve sparks where possible.'),
    ('reroute', 'Detour Cat', 'Find a different route from the parent that fixes the concrete failure.'),
)
RULES = """Each turn appends voice, private and bulk packets in that order. Pip processes first, then Boba.
Voice expires at the end of the next turn; private after two extra turns; bulk after three extra turns.
All packets left after the final turn expire. Prioritize zero private leaks, then total points.
auto serves FIFO and can leak private packets to Boba.
rescue prioritizes voice, private, bulk. guard prioritizes private, voice, bulk.
For rescue and guard, Boba only takes public voice or bulk. Within a kind, earliest deadlines first.
boost is guard with two extra Pip slots even when Pip is offline. There are only three boosts.
Voice is worth 4 points, private 6, bulk 1. Expiries cost 2; leaks cost 20.
You choose the moves. An independent engine executes and scores them."""
SCHEMA = {
    'type': 'object',
    'properties': {
        'actions': {'type': 'array', 'items': {'type': 'string', 'enum': list(GHOST_ACTIONS)}},
        'analysis': {'type': 'string'},
    },
    'required': ['actions', 'analysis'],
    'additionalProperties': False,
}


def score_route(level, actions):
    process = subprocess.run(
        ['node', str(DIRECTOR / 'swarm-score.mjs')],
        input=json.dumps({'level': level, 'actions': actions}),
        capture_output=True, text=True, check=True, timeout=10,
    )
    return json.loads(process.stdout)


def run_agent(level, spec, prefix=(), diagnosis=None, trial=1, tokens=6000):
    role, label, guidance = spec
    phase = 'repair' if diagnosis else 'scout'
    count = len(level['turns']) - len(prefix)
    remaining = 3 - prefix.count('boost')
    prompt = (f'You are {label}, a rescue agent. {guidance}\n{RULES}\n'
              f'This is trial {trial}. Level tape (turns are in order): {json.dumps(level)}\n')
    if diagnosis:
        prompt += ('The engine found this counterexample in a previous route. You inherit the exact '
                   'state and cannot change the frozen prefix. Propose a new suffix.\n'
                   + json.dumps(diagnosis) + '\n')
    prompt += (f'Return exactly {count} ordered action IDs starting at turn {len(prefix) + 1}, '
               f'with at most {remaining} boost moves. Explain your choice in one short sentence.')
    row = {'role': role, 'label': label, 'phase': phase, 'status': 'failed',
           'promptSha256': hashlib.sha256(prompt.encode()).hexdigest()}
    try:
        answer, meta = generate_muse(prompt, schema=SCHEMA, schema_name='ForkshiftSwarmRoute',
                                     tokens=tokens, reasoning_effort='low', timeout=95)
        row.update(model=meta['model'], latencyMs=meta['latency_ms'],
                   usage={'promptTokens': meta['prompt_tokens'], 'outputTokens': meta['output_tokens']},
                   responseSha256=hashlib.sha256(answer.encode()).hexdigest())
        result = json.loads(answer)
        if not isinstance(result, dict) or set(result) != set(SCHEMA['required']):
            raise ValueError('Muse did not return a route and explanation.')
        actions = result['actions']
        if (not isinstance(actions, list) or len(actions) != count
                or any(action not in GHOST_ACTIONS for action in actions)
                or actions.count('boost') > remaining):
            raise ValueError('Muse returned a route with invalid moves, length, or spark use.')
        if not isinstance(result['analysis'], str):
            raise ValueError('Muse returned an invalid explanation.')
        actions = [*prefix, *actions]
        evaluated = score_route(level, actions)
        row.update(status='complete', actions=actions, analysis=result['analysis'].strip()[:240],
                   score=evaluated['score'], history=evaluated['history'])
    except (ValueError, subprocess.SubprocessError) as exc:
        row['error'] = ('Muse did not return valid JSON.' if isinstance(exc, json.JSONDecodeError)
                        else 'The engine could not execute the route.' if isinstance(exc, subprocess.SubprocessError)
                        else str(exc))
    print(f"{phase} {label}: {row.get('score', row.get('error'))}", flush=True)
    return row


def failure_row(run):
    return next((row for row in run['history'] if row['leaks']),
                next((row for row in run['history'] if row['dropped']), None))


def evaluate(path, trial=1, tokens=6000):
    tape_bytes = path.read_bytes()
    tape = json.loads(tape_bytes)
    level = validate(tape['level'])
    auto_actions = ['auto'] * len(level['turns'])
    baseline = score_route(level, auto_actions)
    with ThreadPoolExecutor(max_workers=4) as pool:
        runs = list(pool.map(lambda spec: run_agent(level, spec, trial=trial, tokens=tokens), SCOUTS))
        complete = [(index, run) for index, run in enumerate(runs) if run['status'] == 'complete']
        parents = [(index, run) for index, run in complete if failure_row(run)]
        fork = None
        if parents:
            # Prefer a leaking scout when available, so the fork tests whether a leak can be repaired.
            parent_index, parent = max(parents, key=lambda item: (
                bool(item[1]['score']['leaks']), item[1]['score']['points']))
            failure = failure_row(parent)
            after = failure['turn'] - 1
            prefix = parent['actions'][:after]
            state = score_route(level, prefix)
            diagnosis = {'parentActions': parent['actions'], 'frozenPrefix': prefix,
                         'startState': {'turnsPlayed': after, 'queue': state['queue'], **state['score']},
                         'engineFailure': failure}
            repairs = list(pool.map(lambda spec: run_agent(level, spec, prefix, diagnosis, trial, tokens),
                                    REPAIRERS))
            fork = {'afterTurn': after, 'parentIndex': parent_index, 'parentScore': parent['score'],
                    'failure': failure, 'startState': diagnosis['startState'],
                    'branches': [{'index': index, 'label': run['label'], 'score': run.get('score')}
                                 for index, run in enumerate(repairs, len(runs))]}
            runs.extend(repairs)
    safe = [index for index, run in enumerate(runs)
            if run['status'] == 'complete' and run['score']['leaks'] == 0]
    winner = max(safe, key=lambda index: (runs[index]['score']['points'],
                                          runs[index]['score']['delivered']), default=None)
    oracle_result = subprocess.run(['node', str(DIRECTOR / 'solve.mjs'), str(path.resolve())],
                                   capture_output=True, text=True, check=True, timeout=20)
    oracle = json.loads(oracle_result.stdout)['best_clean']
    return {'model': next((run['model'] for run in runs if 'model' in run), MUSE_MODEL),
            'levelId': path.name, 'tapeTitle': level['title'], 'trial': trial,
            'generatedAt': datetime.now(timezone.utc).isoformat(),
            'tapeSha256': hashlib.sha256(tape_bytes).hexdigest(),
            'maxCompletionTokens': tokens,
            'baseline': baseline['score'], 'baselineHistory': baseline['history'],
            'oracle': {'delivered': oracle['delivered'], 'leaks': oracle['leaks'],
                       'dropped': oracle['missed'], 'queued': 0, 'points': oracle['score']},
            'runs': runs, 'winnerIndex': winner, 'fork': fork, 'calls': len(runs)}


def summarize(paths):
    report = {'trials': 0, 'attempts': 0, 'completed': 0, 'zeroLeak': 0,
              'repairedForks': 0, 'oracleMatches': 0, 'entries': []}
    for path in paths:
        record = json.loads(path.read_text())
        complete = [run for run in record['runs'] if run['status'] == 'complete']
        safe = [run for run in complete if not run['score']['leaks']]
        winner_index = record['winnerIndex']
        winner = record['runs'][winner_index]['score'] if winner_index is not None else None
        fork = record['fork']
        improved = bool(fork and any(
            branch['score'] and not branch['score']['leaks'] and
            (fork['parentScore']['leaks'] or branch['score']['points'] > fork['parentScore']['points'])
            for branch in fork['branches']))
        report['trials'] += 1
        report['attempts'] += record['calls']
        report['completed'] += len(complete)
        report['zeroLeak'] += len(safe)
        report['repairedForks'] += improved
        report['oracleMatches'] += bool(winner and winner['points'] == record['oracle']['points'])
        report['entries'].append({
            'level': record['tapeTitle'], 'trial': record['trial'], 'attempts': record['calls'],
            'completed': len(complete), 'winner': winner, 'oracle': record['oracle'],
            'filename': path.resolve().relative_to(DIRECTOR).as_posix(),
        })
    return report


def write_evidence(path, evidence):
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                     prefix='.swarm-', delete=False) as stream:
        temporary = Path(stream.name)
        json.dump(evidence, stream, indent=2, ensure_ascii=False)
        stream.write('\n')
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--level', type=Path, default=DIRECTOR / 'level.json')
    parser.add_argument('--out', type=Path)
    parser.add_argument('--trial', type=int, default=1)
    parser.add_argument('--tokens', type=int, default=6000)
    parser.add_argument('--summarize', nargs='+', type=Path, metavar='RECORD')
    args = parser.parse_args()
    if args.summarize:
        report = summarize(args.summarize)
        write_evidence(args.out or DIRECTOR / 'swarm-benchmark.json', report)
        print(f"{report['attempts']} Muse attempts across {report['trials']} trials", flush=True)
        return
    if args.trial < 1:
        parser.error('--trial must be positive')
    if not 500 <= args.tokens <= 8000:
        parser.error('--tokens must be between 500 and 8000')
    evidence = evaluate(args.level, args.trial, args.tokens)
    output = args.out or DIRECTOR / 'swarm-evidence.json'
    write_evidence(output, evidence)
    print(f"{evidence['calls']} Muse attempts recorded in {output}", flush=True)


if __name__ == '__main__':
    main()
