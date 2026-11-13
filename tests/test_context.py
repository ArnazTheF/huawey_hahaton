import copy
import unittest
from baseline.context import Context

class ContextTests(unittest.TestCase):
    def update(self, c, patch):
        return c.accept({'state_patch':patch,'action':{'action':'read','path':'x'}})
    def test_merge_delete_and_atomic_rejection(self):
        c=Context('state'); self.update(c,{'facts':{'a':'o1: first'}})
        self.update(c,{'facts':{'b':'o2: second'}})
        self.assertEqual(len(c.state['facts']),2)
        before=copy.deepcopy(c.state)
        with self.assertRaises(ValueError): self.update(c,{'facts':{'c':'ok'},'runtime':{'budget':999}})
        self.assertEqual(c.state,before)
        self.update(c,{'facts':{'a':None}})
        self.assertNotIn('a',c.state['facts'])
    def test_bounds_and_action_validation(self):
        c=Context('state')
        with self.assertRaises(ValueError): self.update(c,{'facts':{str(i):'x' for i in range(9)}})
        with self.assertRaises(ValueError): self.update(c,{'facts':{'a':'x'*241}})
        with self.assertRaises(ValueError): c.accept({'state_patch':{'facts':{'a':'x'}},'action':{'action':'bash'}})
        self.assertFalse(c.state['facts'])
    def test_no_transcript_growth_and_latest_observation(self):
        c=Context('state')
        for i in range(100): c.observe({'action':'read','path':'x'},{'content':str(i)},i)
        self.assertEqual(c.history,[])
        self.assertEqual(c.latest['id'],'o100')
        self.assertLess(len(str(c.messages('rules',{'role':'user','content':'goal'},{},1000))),2000)
    def test_hybrid_bounded_history(self):
        c=Context('hybrid',hybrid_turns=1)
        for i in range(20): c.observe({'action':'read','path':'x'},{'content':str(i)},i)
        self.assertEqual(len(c.history),2)
    def test_hybrid_preserves_response_protocol_and_error_observation(self):
        import json
        c=Context('hybrid');c.observe({'action':'read','path':'x'},{'content':'important'},0)
        self.assertEqual(set(json.loads(c.history[0]['content'])),{'action'})
        c.observe({'action':'invalid_response'},{'error':'wrong schema'},1)
        self.assertEqual(c.latest['result']['content'],'important')
        self.assertEqual(c.latest['validation_error'],'wrong schema')
