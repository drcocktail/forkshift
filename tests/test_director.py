import json
from pathlib import Path
import unittest
from unittest.mock import patch

from forkshift import director


TAPE = json.loads((Path(__file__).resolve().parent.parent / 'director' / 'level.json').read_text())['level']


class DirectorTests(unittest.TestCase):
    def test_published_tape_is_valid(self):
        self.assertIs(director.validate(TAPE, showcase=True), TAPE)

    def test_invalid_input_does_not_call_model(self):
        with patch.object(director, 'generate') as generate:
            with self.assertRaises(ValueError):
                director.author('')
        generate.assert_not_called()

    def test_one_model_response_becomes_the_playable_tape(self):
        with patch.object(director, 'generate') as generate:
            generate.return_value = json.dumps(TAPE), {'model': 'test'}
            result = director.author('A tiny outage')
        generate.assert_called_once()
        self.assertEqual(result['level'], TAPE)
        self.assertEqual(result['origin'], 'llama')
        self.assertEqual(result['metadata']['calls'], 1)

    def test_custom_tapes_need_not_copy_the_showcase_fault_sequence(self):
        custom = {**TAPE, 'turns': [{**row, 'boba': 3} for row in TAPE['turns']]}
        self.assertIs(director.validate(custom), custom)
        with self.assertRaises(ValueError):
            director.validate(custom, showcase=True)

    def test_bool_and_missing_turn_are_rejected(self):
        broken = {**TAPE, 'turns': [{**TAPE['turns'][0], 'pip': False}, *TAPE['turns'][1:]]}
        with self.assertRaises(ValueError):
            director.validate(broken)
        with self.assertRaises(ValueError):
            director.validate({**TAPE, 'turns': TAPE['turns'][:-1]})


if __name__ == '__main__':
    unittest.main()
