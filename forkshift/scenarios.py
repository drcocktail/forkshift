"""Synthetic replay specifications. Times are integer simulated seconds."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Incident:
    title: str
    brief: str
    fault_at: int
    recover_at: int
    primary: int
    degraded: int
    secondary: int
    arrivals: tuple
    min_interactive: float
    min_batch: float
    max_alternate: float


INCIDENTS = {
    'rank-drop': Incident(
        'A worker dies during the voice rush',
        'At 00:12 a primary inference rank stops serving during an interactive voice rush. '
        'Voice may spill into the alternate pool. Keep at least 97% of voice turns on deadline '
        'and complete at least 25% of batch work. The alternate model is approved for voice only. '
        'Use reservation, overflow and batch admission as needed. Restore regular admission after recovery.',
        12, 44, 18, 3, 10, (8, 7, 10, 7), .97, .25, .78,
    ),
    'secondary-budget': Incident(
        'The backup has a strict budget',
        'The primary slows under a long generation burst. The alternate model is approved for '
        'voice and batch. At least 96% of voice turns and 70% of batch jobs must meet their deadlines. '
        'The alternate pool can serve at most 35% of completed requests. Avoid an unnecessary blanket reroute.',
        12, 39, 19, 8, 9, (6, 8, 8, 9), .96, .70, .35,
    ),
    'no-crossing': Incident(
        'An incident inside a restricted pool',
        'This service cannot move regulated traffic to the alternate pool. Leave overflow off. '
        'The primary retains reduced capacity. Keep 96% of voice turns within deadline and finish '
        'at least 36% of batch jobs. It is acceptable to temporarily reject batch jobs during the fault.',
        10, 45, 18, 8, 12, (6, 9, 7, 11), .96, .36, 0,
    ),
}


def incident_info(key):
    spec = INCIDENTS[key]
    return {
        'id': key, 'title': spec.title, 'brief': spec.brief,
        'fault_at': spec.fault_at, 'recover_at': spec.recover_at,
        'primary_capacity': spec.primary, 'degraded_capacity': spec.degraded,
        'alternate_capacity': spec.secondary,
        'targets': {'interactive': spec.min_interactive, 'batch': spec.min_batch,
                    'alternate_max': spec.max_alternate},
    }
