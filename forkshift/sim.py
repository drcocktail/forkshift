"""Common-random-number traffic replays and an independent acceptance gate."""
import hashlib
import itertools
import json
import random
from dataclasses import asdict, dataclass

from .scenarios import INCIDENTS, Incident

DURATION = 60
DEADLINES = {'voice': 2, 'batch': 8}
OVERFLOW = ('off', 'voice', 'all')
ADMISSION = (0, 25, 50, 75, 100)
RESERVE = (0, 25, 50, 75, 100)
REPLAYS = ('reference', 'demand-spike', 'slow-recovery')
BASELINE = {'overflow': 'off', 'batch_admit_pct': 100, 'reserve_pct': 0}
FALLBACK = {'overflow': 'all', 'batch_admit_pct': 0, 'reserve_pct': 100}


@dataclass(frozen=True)
class Request:
    id: int
    kind: str
    arrival: int
    deadline: int
    admit_bucket: int


def validate_plan(plan):
    options = {'overflow': OVERFLOW, 'batch_admit_pct': ADMISSION, 'reserve_pct': RESERVE}
    if not isinstance(plan, dict) or set(plan) != set(options):
        raise ValueError('Plan must specify overflow, batch admission and voice reservation.')
    for name, choices in options.items():
        if type(plan[name]) is not type(choices[0]) or plan[name] not in choices:
            raise ValueError(f'Unsupported {name}.')
    return plan


def traffic(spec, replay):
    seed = REPLAYS.index(replay) + 27
    rng = random.Random(seed)
    recover = spec.recover_at + (5 if replay == 'slow-recovery' else 0)
    arrivals = []
    for tick in range(DURATION):
        incident = spec.fault_at <= tick < recover
        counts = spec.arrivals[2:] if incident else spec.arrivals[:2]
        requests = []
        for kind, count in zip(DEADLINES, counts):
            if replay == 'demand-spike' and spec.fault_at <= tick < spec.fault_at + 8:
                count += 1
            for _ in range(max(0, count + rng.choice((-1, 0, 0, 1)))):
                requests.append(Request(len(arrivals) + len(requests), kind, tick,
                                        tick + DEADLINES[kind], rng.randrange(100)))
        arrivals.extend(requests)
    return arrivals, recover


def simulate(spec: Incident, requests, recover_at, plan, *, include_trace=False):
    """Run one request-capacity model. Voice reservation is work-conserving."""
    validate_plan(plan)
    results = []
    queues = {'voice': [], 'batch': []}
    timeline = []
    cursor = 0

    def record(request, tick, outcome, pool=None):
        results.append((request, tick, outcome, pool))

    def serve(kind, capacity, tick, pool):
        selected = queues[kind][:capacity]
        del queues[kind][:capacity]
        for request in selected:
            record(request, tick, 'on_time', pool)
        return len(selected)

    for tick in range(DURATION + max(DEADLINES.values())):
        active = spec.fault_at <= tick < recover_at
        policy = plan if active else BASELINE
        while cursor < len(requests) and requests[cursor].arrival == tick:
            request = requests[cursor]
            cursor += 1
            if request.kind == 'batch' and request.admit_bucket >= policy['batch_admit_pct']:
                record(request, tick, 'shed')
            else:
                queues[request.kind].append(request)

        for queue in queues.values():
            while queue and queue[0].deadline <= tick:
                record(queue.pop(0), tick, 'deadline')

        capacity = spec.degraded if active else spec.primary
        reservation = (capacity * policy['reserve_pct'] + 99) // 100
        used = serve('voice', reservation, tick, 'primary')
        while used < capacity and any(queues.values()):
            # Oldest request first across queues, with voice breaking exact ties.
            kind = min((kind for kind, q in queues.items() if q), key=lambda k: queues[k][0].arrival)
            used += serve(kind, 1, tick, 'primary')

        alt_used = 0
        if policy['overflow'] != 'off':
            alt_used = serve('voice', spec.secondary, tick, 'alternate')
            if policy['overflow'] == 'all':
                alt_used += serve('batch', spec.secondary - alt_used, tick, 'alternate')

        if include_trace and tick < DURATION:
            timeline.append({
                't': tick, 'fault': active, 'primary': used, 'alternate': alt_used,
                'voice_queue': len(queues['voice']), 'batch_queue': len(queues['batch']),
            })

    summary = {}
    for kind in DEADLINES:
        rows = [row for row in results if row[0].kind == kind]
        waits = sorted(tick - req.arrival for req, tick, outcome, _ in rows if outcome == 'on_time')
        summary[kind] = {
            'offered': len(rows), 'on_time': len(waits), 'rate': round(len(waits) / len(rows), 6),
            'shed': sum(outcome == 'shed' for _, _, outcome, _ in rows),
            'expired': sum(outcome == 'deadline' for _, _, outcome, _ in rows),
            'p95_wait': waits[(len(waits) * 95 + 99) // 100 - 1] if waits else None,
        }
    alt = sum(pool == 'alternate' for _, _, _, pool in results)
    completed = sum(row['on_time'] for row in summary.values())
    summary['alternate_rate'] = round(alt / completed, 6) if completed else 0
    summary['alternate_batch'] = sum(req.kind == 'batch' and pool == 'alternate' for req, _, _, pool in results)
    if include_trace:
        summary['timeline'] = timeline
        summary['first_voice_miss'] = next((asdict(req) | {'outcome': outcome}
                                            for req, _, outcome, _ in results
                                            if req.kind == 'voice' and outcome != 'on_time'), None)
    return summary


def gate(key, spec, metrics, plan):
    failures = []
    if metrics['voice']['rate'] < spec.min_interactive:
        failures.append('Voice deadline target missed')
    if metrics['batch']['rate'] < spec.min_batch:
        failures.append('Batch completion floor missed')
    if metrics['alternate_rate'] > spec.max_alternate:
        failures.append('Alternate pool budget exceeded')
    if key == 'rank-drop' and plan['overflow'] == 'all':
        failures.append('Batch is prohibited on the alternate pool')
    if key == 'no-crossing' and plan['overflow'] != 'off':
        failures.append('Restricted traffic cannot leave the primary pool')
    return failures


def compare(key, candidates):
    spec = INCIDENTS[key]
    workloads = {name: traffic(spec, name) for name in REPLAYS}
    return {name: evaluate(key, spec, plan, workloads, include_trace=True)
            for name, plan in candidates.items()}


def plan_hash(plan):
    return hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()


def evaluate(key, spec, plan, workloads, *, include_trace=False):
    outcomes = {}
    for replay, (requests, recover_at) in workloads.items():
        metrics = simulate(spec, requests, recover_at, plan, include_trace=include_trace)
        outcomes[replay] = {**metrics, 'failures': gate(key, spec, metrics, plan)}
    return {'plan': plan, 'plan_sha256': plan_hash(plan), 'replays': outcomes,
            'eligible': all(not row['failures'] for row in outcomes.values())}


def search(key):
    """Strong baseline: enumerate the full finite plan space with the verifier."""
    spec = INCIDENTS[key]
    workloads = {name: traffic(spec, name) for name in REPLAYS}
    best = None
    best_score = None
    for overflow, admit, reserve in itertools.product(OVERFLOW, ADMISSION, RESERVE):
        plan = {'overflow': overflow, 'batch_admit_pct': admit, 'reserve_pct': reserve}
        result = evaluate(key, spec, plan, workloads)
        runs = result['replays'].values()
        score = (result['eligible'], min(r['voice']['rate'] for r in runs),
                 min(r['batch']['rate'] for r in runs), -max(r['alternate_rate'] for r in runs))
        if best_score is None or score > best_score:
            best, best_score = plan, score
    return best
