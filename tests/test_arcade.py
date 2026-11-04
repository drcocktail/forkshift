import copy
import unittest
from unittest.mock import patch

from forkshift.arcade import run
from forkshift.rle_oracle import judge
from forkshift.rle_scenarios import SCENARIOS
from forkshift.rle_workers import WorkerFleet


class ArcadeTests(unittest.TestCase):
    @staticmethod
    def rejudge(record, events):
        spec = SCENARIOS[record['scenario']['id']]
        return judge(events, forbidden=spec.forbidden, expected_route=spec.expected_route,
                     requires_rollback=spec.crash_after_switch)

    def test_real_fixture_worker_exit_rollback_and_repair(self):
        record = run('stale-green', 'policy', 'fixture')
        self.assertEqual(record['verdict'], 'passed')
        self.assertTrue(record['summary']['recovered'])
        self.assertTrue(record['summary']['safe'])
        self.assertEqual(record['summary']['corrections'], 1)
        self.assertEqual(record['summary']['failed_probes'], 1)
        events = record['events']
        workers = events[0]['data']['workers']
        self.assertNotEqual(workers['primary']['pid'], workers['backup']['pid'])
        self.assertEqual([e['data']['pool'] for e in events if e['type'] == 'fault'], ['primary', 'backup'])
        self.assertTrue(all(e['data']['killed'] for e in events if e['type'] == 'fault'))
        restart = next(e for e in events if e['type'] == 'restart')
        self.assertNotEqual(restart['data']['pid'], workers['primary']['pid'])

    def test_unsafe_recovery_is_not_a_pass_and_noop_is_safe_but_offline(self):
        unsafe = run('sealed-backup', 'unsafe', 'fixture')
        noop = run('stale-green', 'noop', 'fixture')
        self.assertEqual((unsafe['verdict'], unsafe['summary']['recovered'], unsafe['summary']['safe']),
                         ('failed', True, False))
        self.assertEqual((noop['verdict'], noop['summary']['recovered'], noop['summary']['safe']),
                         ('failed', False, True))

    def test_rejected_action_sends_no_traffic_and_agent_can_repair(self):
        def chooser(agent, brief, observations):
            self.assertIn('outside the approved route', brief)
            if observations:
                self.assertIn('authorization denied', observations[-1]['outcome'])
            return {'action': 'try_backup' if not observations else 'repair_primary', 'reason': 'test decision'}

        record = run('sealed-backup', 'llama', 'fixture', chooser=chooser)
        self.assertEqual(record['verdict'], 'passed')
        self.assertTrue(any(event['type'] == 'blocked' for event in record['events']))
        self.assertFalse(any(event['type'] == 'dispatch' and event['data']['pool'] == 'backup'
                             for event in record['events']))

    def test_missing_dispatch_stale_pid_and_missing_rollback_are_caught(self):
        record = run('stale-green', 'policy', 'fixture')
        for mutation in ('missing-dispatch', 'stale-pid', 'missing-rollback', 'false-golden', 'wrong-worker', 'post-recovery-exit'):
            with self.subTest(mutation=mutation):
                events = copy.deepcopy(record['events'])
                if mutation == 'missing-dispatch':
                    events = [e for e in events if not (e['type'] == 'dispatch' and e['data']['phase'] == 'canary')]
                if mutation == 'stale-pid':
                    next(e for e in events if e['type'] == 'commit')['data']['pid'] = -1
                if mutation == 'missing-rollback':
                    events = [e for e in events if e['type'] != 'rollback']
                if mutation == 'false-golden':
                    next(e for e in reversed(events) if e['type'] == 'probe')['data']['ack']['probe_id'] = 'wrong-id'
                if mutation == 'wrong-worker':
                    next(e for e in reversed(events) if e['type'] == 'probe')['data']['worker_pid'] = -99
                if mutation == 'post-recovery-exit':
                    events.insert(-1, {'type': 'fault', 'data': {'pool': 'primary'}})
                self.assertEqual(self.rejudge(record, events)[1], 'failed')

    def test_startup_failure_is_ungraded(self):
        with patch.object(WorkerFleet, 'start', side_effect=RuntimeError('fixture startup failed')):
            result = run('rank-crash', 'policy', 'fixture')
        self.assertEqual(result['verdict'], 'ungraded')
        self.assertIsNone(result['summary']['safe'])


if __name__ == '__main__':
    unittest.main()
