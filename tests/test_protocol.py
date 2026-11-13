import copy
import hashlib
import json
import unittest
from pathlib import Path
from baseline.context import Context
from baseline.legacy_context import Context as LegacyContext
from baseline.protocol import parse_json, validate_response
from baseline.solver import SYSTEM, UNIFIED_SYSTEM

MODES = ('history', 'state', 'hybrid')

class ProtocolTests(unittest.TestCase):
    def test_common_system_instructions_and_optional_patch(self):
        systems = []
        for mode in MODES:
            c = Context(mode)
            systems.append(c.messages(UNIFIED_SYSTEM, {'role':'user','content':'goal'}, {}, 24000)[0])
            for response in ({'action':{'action':'read','path':'x'}},
                             {'action':{'action':'read','path':'x'},'state_patch':{}}):
                self.assertEqual(c.accept(response), {'action':'read','path':'x'})
            self.assertFalse(any(c.state.values()))
        self.assertEqual(systems[0], systems[1])
        self.assertEqual(systems[1], systems[2])
        self.assertNotIn('\nActions:', systems[0]['content'])

    def test_all_actions_share_the_same_schema(self):
        actions = [{'action':'bash','command':'echo ok'}, {'action':'read','path':'x'},
                   {'action':'write','path':'x','content':'hello'},
                   {'action':'skip','reason':'no inputs'}, {'action':'final','answer':'42'}]
        for mode in MODES:
            for action in actions:
                with self.subTest(mode=mode, action=action):
                    c = Context(mode)
                    self.assertEqual(c.accept(c.parse(json.dumps({'action':action}))), action)

    def test_bad_action_cannot_commit_valid_patch(self):
        bad = [None, [], {}, {'action':'bash'}, {'action':'read','path':7},
               {'action':'final','answer':''}, {'action':'final','answer':' '*5},
               {'action':'unknown'}, {'action':'skip','reason':3},
               {'action':'write','path':'x','content':'ok','surprise':True}]
        for mode in MODES:
            for action in bad:
                c=Context(mode); before=copy.deepcopy(c.state)
                with self.subTest(mode=mode, action=action), self.assertRaises(ValueError):
                    c.accept({'action':action,'state_patch':{'facts':{'x':'would be committed'}}})
                self.assertEqual(c.state,before)
                self.assertEqual(c.revision,0)

    def test_bad_envelopes_and_patches_rejected_equally(self):
        bad = [{'action':'read','path':'x'}, {'action':{'action':'read','path':'x'},'state_patch':None},
               {'action':{'action':'read','path':'x'},'extra':1},
               {'action':{'action':'read','path':'x'},'state_patch':{'runtime':{'cost':'0'}}}]
        for response in bad:
            errors=[]
            for mode in MODES:
                with self.assertRaises(ValueError) as error:
                    Context(mode).accept(response)
                errors.append(str(error.exception))
            self.assertEqual(len(set(errors)),1)

    def test_parser_consistent_fences_duplicates_and_prose(self):
        raw='{"action":{"action":"final","answer":"42"}}'
        self.assertEqual(parse_json(raw),parse_json('```json\n'+raw+'\n```'))
        for bad in ('[]','hello '+raw,raw+' trailing','{"action":{},"action":{}}','```json\n{}'):
            with self.subTest(bad=bad), self.assertRaises(ValueError): parse_json(bad)

    def test_history_has_no_persistent_state(self):
        c=Context('history')
        c.accept({'action':{'action':'read','path':'x'},'state_patch':{'facts':{'x':'note'}}})
        self.assertFalse(any(c.state.values()))
        c.observe({'action':'read','path':'x'},{'content':'evidence'},0)
        frame=c.messages(UNIFIED_SYSTEM, {'role':'user','content':'goal'}, {},24000)
        self.assertNotIn('"state":',frame[-1]['content'])
        self.assertEqual(json.loads(c.history[0]['content']),{'action':{'action':'read','path':'x'}})

    def test_state_merges_identically_to_control(self):
        c=Context('state');control=LegacyContext('state')
        for patch in ({'facts':{'a':'o1: found'}}, {}, {'facts':{'b':'o2: found'}}, {'facts':{'a':None}}):
            response={'action':{'action':'read','path':'x'},'state_patch':patch}
            self.assertEqual(c.accept(response),control.accept(response))
            self.assertEqual(c.state,control.state)
            self.assertEqual(c.revision,control.revision)

    def test_validation_feedback_retains_evidence_without_fake_actions(self):
        for mode in MODES:
            c=Context(mode); c.observe({'action':'read','path':'x'},{'content':'evidence'},0)
            before=copy.deepcopy(c.history)
            c.observe({'action':'invalid_response'},{'error':'bad JSON'},1)
            self.assertEqual(c.latest['result']['content'],'evidence')
            self.assertEqual(c.history,before)
            messages=c.messages(UNIFIED_SYSTEM,{'role':'user','content':'goal'},{},24000)
            self.assertIn('bad JSON',messages[-1]['content'])

    def test_legacy_control_fingerprints(self):
        root=Path(__file__).resolve().parents[1]
        manifest=json.loads((root/'tests/fixtures/legacy_protocol.json').read_text())
        self.assertEqual(hashlib.sha256((root/'baseline/legacy_context.py').read_bytes()).hexdigest(),manifest['context_sha256'])
        self.assertEqual(hashlib.sha256(SYSTEM.encode()).hexdigest(),manifest['system_sha256'])
        self.assertEqual(LegacyContext('history').accept({'action':'final','answer':'42'}),{'action':'final','answer':'42'})
        with self.assertRaises(ValueError): LegacyContext('state').accept({'action':{'action':'final','answer':'42'}})

    def test_replay_successful_state_run_without_state_regression(self):
        root=Path(__file__).resolve().parents[1]
        fixture=json.loads((root/'tests/fixtures/state_replay.json').read_text())
        contexts={}
        for record in fixture['records']:
            c=contexts.setdefault(record['task_id'],Context('state'))
            c.accept(c.parse(record['response']))
            self.assertEqual(c.state,record['state'])
