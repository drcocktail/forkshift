import io
import json
import os
import unittest
from unittest.mock import patch

from forkshift.__main__ import run
from forkshift.canary import PROBE_ID, canary
from forkshift.model import MUSE_ENDPOINT
from forkshift.scenarios import INCIDENTS
from forkshift.sim import BASELINE, FALLBACK, REPLAYS, compare, search, traffic, validate_plan


class ReplayTests(unittest.TestCase):
    def test_search_satisfies_all_replays_for_every_incident(self):
        for key in INCIDENTS:
            with self.subTest(incident=key):
                runs = compare(key, {'search': search(key), 'unchanged': BASELINE, 'panic': FALLBACK})
                self.assertTrue(runs['search']['eligible'])
                self.assertFalse(runs['unchanged']['eligible'])
                self.assertFalse(runs['panic']['eligible'])
                self.assertEqual(set(runs['search']['replays']), set(REPLAYS))

    def test_each_request_is_accounted_for(self):
        for key, spec in INCIDENTS.items():
            plan = compare(key, {'search': search(key)})['search']
            for name, metrics in plan['replays'].items():
                requests, _ = traffic(spec, name)
                self.assertEqual(len(requests), metrics['voice']['offered'] + metrics['batch']['offered'])
                for kind in ('voice', 'batch'):
                    row = metrics[kind]
                    self.assertEqual(row['offered'], row['on_time'] + row['shed'] + row['expired'])

    def test_plan_types_and_unexpected_keys_fail_closed(self):
        for bad in (BASELINE | {'reserve_pct': True}, BASELINE | {'overflow': 'batch'}, BASELINE | {'extra': 1}):
            with self.assertRaises(ValueError):
                validate_plan(bad)

    def test_planner_revision_sees_failures_and_is_gated_independently(self):
        key = 'rank-drop'
        with patch('forkshift.__main__.propose', side_effect=[
            (FALLBACK, 'unsafe', {}),
            (search(key), 'fixed', {}),
        ]) as proposer:
            result = run(key, 'llama')
        self.assertFalse(result['branches']['llama']['eligible'])
        self.assertTrue(result['branches']['revision']['eligible'])
        self.assertIn('Batch is prohibited on the alternate pool',
                      proposer.call_args.args[1]['replays'][0]['failures'])


class MuseTests(unittest.TestCase):
    def test_missing_key_avoids_network(self):
        with patch.dict(os.environ, {'MODEL_API_KEY': ''}), patch('forkshift.model.urlopen') as remote:
            result = run('rank-drop', 'muse')
        self.assertIn('MODEL_API_KEY', result['model_error'])
        self.assertNotIn('llama', result['branches'])
        remote.assert_not_called()

    def test_muse_proposal_uses_schema_and_same_gate(self):
        good = search('rank-drop')
        answer = json.dumps(good | {'reason': 'Keep voice on an approved pool.'})
        response = {'choices': [{'finish_reason': 'stop', 'message': {'content': answer}}],
                    'model': 'muse-spark-1.3', 'usage': {'prompt_tokens': 222}}
        with patch.dict(os.environ, {'MODEL_API_KEY': 'test-key'}), patch(
            'forkshift.model.urlopen', return_value=io.BytesIO(json.dumps(response).encode())
        ) as remote:
            result = run('rank-drop', 'muse')
        self.assertTrue(result['branches']['llama']['eligible'])
        self.assertEqual(result['model']['provider'], 'meta-model-api')
        request = remote.call_args.args[0]
        self.assertEqual(request.full_url, MUSE_ENDPOINT)
        body = json.loads(request.data)
        self.assertTrue(body['response_format']['json_schema']['strict'])


class CanaryTests(unittest.TestCase):
    @staticmethod
    def stub(model, prompt, **kwargs):
        return json.dumps({'status': 'acknowledged', 'probe_id': PROBE_ID}), {'model': model}

    def test_real_loopback_fault_and_restoration(self):
        key = 'rank-drop'
        candidate = compare(key, {'search': search(key)})['search']
        probe = canary(candidate, inference=self.stub)
        self.assertEqual([a['status'] for a in probe['attempts']], [200, 503, 200, 200])
        self.assertEqual(probe['attempts'][1]['transport'], 'loopback-http')
        self.assertEqual(probe['outcome'], 'served-by-alternate')

    def test_policy_prohibits_alternate_probe(self):
        key = 'no-crossing'
        candidate = compare(key, {'search': search(key)})['search']
        probe = canary(candidate, inference=self.stub)
        self.assertEqual([a['status'] for a in probe['attempts']], [200, 503, 200])
        self.assertEqual(probe['outcome'], 'blocked-by-policy')

    def test_failed_gate_blocks_before_network_or_inference(self):
        key = 'rank-drop'
        candidate = compare(key, {'panic': FALLBACK})['panic']
        with patch('forkshift.canary.HTTPServer') as gateway, self.assertRaises(ValueError):
            canary(candidate, inference=self.stub)
        gateway.assert_not_called()


if __name__ == '__main__':
    unittest.main()
