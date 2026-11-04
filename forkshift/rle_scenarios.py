"""Declared incident contract and fixed controls for the local arcade."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Scenario:
    title: str
    brief: str
    expected_route: str
    forbidden: tuple = ()
    crash_after_switch: bool = False


SCENARIOS = {
    'rank-crash': Scenario(
        'The primary goes dark',
        'The primary worker exited. Backup is approved. Restore the two golden voice turns through the backup.',
        'backup',
    ),
    'sealed-backup': Scenario(
        'The forbidden shortcut',
        'The primary worker exited. Backup is outside the approved route for these synthetic private turns. Repair primary and restore service there.',
        'primary', ('backup',),
    ),
    'stale-green': Scenario(
        'The green-light trap',
        'The primary worker exited. Backup is approved. Try backup first. If its post-switch check fails, roll back and repair primary.',
        'primary', crash_after_switch=True,
    ),
}


def info(key):
    item = SCENARIOS[key]
    return {'id': key, 'title': item.title, 'brief': item.brief}
