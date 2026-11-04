import json
import shutil
import unittest
from unittest.mock import patch

from forkshift import swarm
from forkshift.rle_agent import decide


@unittest.skipUnless(shutil.which('node'), 'The arcade engine runs on Node')
class SwarmTests(unittest.TestCase):
    def test_failed_scout_is_preserved_and_repairs_inherit_the_exact_prefix(self):
        def fake_muse(prompt, **options):
            if 'You are Radio Runner' in prompt:
                return '{"actions":["boost"],"analysis":"Incomplete"}', meta
            if 'The engine found this counterexample' in prompt:
                diagnosis = json.loads(prompt.split('Propose a new suffix.\n')[1].splitlines()[0])
                remaining = 12 - len(diagnosis['frozenPrefix'])
                self.assertTrue(diagnosis['engineFailure']['leakedPackets'])
                actions = ['guard'] * remaining
            else:
                actions = ['auto'] * 12
            return json.dumps({'actions': actions, 'analysis': 'Recorded test route.'}), meta

        meta = {'model': 'test-muse', 'latency_ms': 1, 'prompt_tokens': 5, 'output_tokens': 8}
        with patch.object(swarm, 'generate_muse', side_effect=fake_muse) as provider:
            evidence = swarm.evaluate(swarm.DIRECTOR / 'level.json')
        self.assertEqual(provider.call_count, 7)
        self.assertEqual(evidence['runs'][1]['status'], 'failed')
        self.assertEqual(evidence['baseline']['leaks'], 10)
        fork = evidence['fork']
        parent = evidence['runs'][fork['parentIndex']]
        self.assertGreater(fork['afterTurn'], 0)
        for branch in fork['branches']:
            child = evidence['runs'][branch['index']]
            self.assertEqual(child['actions'][:fork['afterTurn']], parent['actions'][:fork['afterTurn']])
            self.assertEqual(child['score']['leaks'], 0)
        self.assertEqual(evidence['runs'][evidence['winnerIndex']]['phase'], 'repair')


class MuseWorkerTests(unittest.TestCase):
    def test_muse_worker_chooses_with_live_observations(self):
        observations = [{'action': 'try_backup', 'outcome': 'post-switch request failed; route rolled back'}]
        usage = {'model': 'test-muse'}
        with patch('forkshift.rle_agent.generate_muse',
                   return_value=('{"action":"repair_primary","reason":"Restart Pip."}', usage)) as provider:
            decision = decide('muse', 'Backup is approved.', observations)
        self.assertIn('route rolled back', provider.call_args.args[0])
        self.assertEqual(decision, {'action': 'repair_primary', 'reason': 'Restart Pip.',
                                    'model': usage, 'repeated': False})


if __name__ == '__main__':
    unittest.main()
