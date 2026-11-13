import copy
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from baseline.context import Context
from baseline.core import Budget, Task, Trace
from baseline.observation_memory import ObservationMemory, encoded, workspace_fingerprint
from baseline.portfolio import Portfolio
from baseline.solver import UNIFIED_SYSTEM, solve


class ObservationMemoryTests(unittest.TestCase):
    def test_computed_result_survives_read_without_model_patch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'data.csv').write_text('amount\n42\n')
            context = Context('state')
            memory = ObservationMemory(root)
            context.observations = memory
            for step, action, result in [
                (0, {'action':'bash','command':'python3 solve.py'}, {'returncode':0,'timeout':False,'output':'438293\n','truncated':False}),
                (1, {'action':'read','path':'data.csv'}, {'content':'amount\n42\n','truncated':False}),
            ]:
                context.accept({'action': action})
                memory.observe(action, result, step)
                context.observe(action, result, step)
            messages = context.messages(UNIFIED_SYSTEM, {'role':'user','content':'Compute total'}, {}, 24000)
            frame = json.loads(messages[-1]['content'])
            record = frame['observation_memory']['records'][0]
            self.assertEqual(record['id'], 'o1')
            self.assertEqual(record['result']['output'], '438293\n')
            self.assertEqual(record['freshness'], 'unchanged')
            self.assertFalse(any(context.state.values()))
            self.assertEqual(context.history, [])
            # Latest read is already in latest_observation and is not duplicated.
            self.assertEqual(len(frame['observation_memory']['records']), 1)

    def test_model_cannot_modify_observations_and_copies_are_defensive(self):
        with tempfile.TemporaryDirectory() as directory:
            memory = ObservationMemory(directory)
            result = {'output':'42', 'returncode':0, 'timeout':False, 'truncated':False}
            action = {'action':'bash','command':'compute'}
            memory.observe(action, result, 0)
            action['command'] = 'forged'; result['output'] = 'forged'
            context = Context('state'); context.observations = memory
            before = copy.deepcopy(memory.frame())
            with self.assertRaises(ValueError):
                context.accept({'action':{'action':'read','path':'x'}, 'state_patch':{'observation_memory':{'o1':'forged'}}})
            mutated = memory.frame(); mutated['records'][0]['result']['output'] = 'forged'
            self.assertEqual(memory.frame(), before)

    def test_file_change_stales_result_even_when_size_and_mtime_match(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); path = root/'data'
            path.write_text('12'); original = path.stat()
            memory = ObservationMemory(root)
            memory.observe({'action':'bash','command':'compute'}, {'output':'12','returncode':0}, 0)
            path.write_text('99'); os.utime(path, ns=(original.st_atime_ns, original.st_mtime_ns))
            memory.observe({'action':'write','path':'data','content':'99'}, {'written':'data'}, 1)
            old = memory.frame()['records'][0]
            self.assertEqual(old['freshness'], 'stale')
            self.assertEqual(old['result']['output'], '12')
            self.assertTrue(memory.frame()['records'][1]['workspace_changed_during_action'])

    def test_bash_file_mutation_and_restoration_are_detected(self):
        from baseline.tools import run_command
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); (root/'x').write_text('old')
            memory=ObservationMemory(root)
            memory.observe({'action':'read','path':'x'}, {'content':'old','truncated':False}, 0)
            action={'action':'bash','command':"printf new > x"}
            result=run_command(action['command'], root, 2)
            memory.observe(action, result, 1)
            self.assertEqual(memory.frame()['records'][0]['freshness'], 'stale')
            # A return to identical audited content can restore the old observation.
            (root/'x').write_text('old')
            memory.observe({'action':'write','path':'x','content':'old'}, {'written':'x'}, 2)
            self.assertEqual(memory.frame()['records'][0]['freshness'], 'unchanged')

    def test_unknown_snapshot_never_reports_fresh(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch('baseline.observation_memory.workspace_fingerprint', return_value=None):
                memory = ObservationMemory(directory)
                memory.observe({'action':'bash','command':'compute'}, {'output':'42'}, 0)
            self.assertEqual(memory.frame()['snapshot_status'], 'unknown')
            self.assertEqual(memory.frame()['records'][0]['freshness'], 'unknown')

    def test_failures_timeouts_and_truncation_remain_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            memory=ObservationMemory(directory)
            result={'output':'x'*1500,'returncode':-9,'timeout':True,'truncated':True}
            memory.observe({'action':'bash','command':'compute'},result,0)
            record=memory.frame()['records'][0]
            self.assertEqual(record['result']['returncode'],-9)
            self.assertTrue(record['result']['timeout'])
            self.assertTrue(record['result']['truncated'])
            self.assertIn('result.output',record['excerpted_fields'])
            self.assertNotIn('verified',record)

    def test_limits_hold_for_escaped_unicode_and_commands_survive_many_reads(self):
        with tempfile.TemporaryDirectory() as directory:
            memory=ObservationMemory(directory)
            memory.observe({'action':'bash','command':'calculate'}, {'output':'42'}, 0)
            for step in range(1,40):
                memory.observe({'action':'read','path':'x'}, {'content':'\x00😀"\\'*5000,'truncated':False},step)
                self.assertLessEqual(len(memory.records),4)
                self.assertLessEqual(len(encoded(memory.frame())),3000)
            self.assertTrue(any(r['result'].get('output')=='42' for r in memory.frame()['records']))
            self.assertGreater(memory.evicted,0)
            small=ObservationMemory(directory,max_chars=1024)
            small.observe({'action':'read','path':'x'}, {'content':'x'*5000},0)
            self.assertLessEqual(len(encoded(small.frame())),1024)

    def test_snapshot_bounds_links_special_files_and_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); path=root/'x'; path.write_text('123')
            initial=workspace_fingerprint(root)
            self.assertIsNotNone(initial)
            self.assertIsNone(workspace_fingerprint(root,max_bytes=2))
            self.assertIsNone(workspace_fingerprint(root,max_entries=0))
            path.chmod(0o700)
            self.assertNotEqual(initial,workspace_fingerprint(root))
            link=root/'link';link.symlink_to(path)
            self.assertIsNone(workspace_fingerprint(root))
            link.unlink();os.mkfifo(root/'pipe')
            self.assertIsNone(workspace_fingerprint(root))

    def test_off_and_history_keep_control_context(self):
        for mode in ('history','state'):
            context=Context(mode)
            context.observe({'action':'read','path':'x'},{'content':'x'},0)
            self.assertNotIn('observation_memory',context.messages(UNIFIED_SYSTEM,{'role':'user','content':'task'},{},24000)[-1]['content'])

    def test_old_portfolio_does_not_mix_memory_configurations(self):
        from test_portfolio import CONFIG, FEATURES, row
        artifact=Portfolio({'schema':1,'kind':'empirical-family-baseline','rows':[row(str(i)) for i in range(3)]})
        model = artifact.rows[0]['model']
        self.assertFalse(artifact.recommend(FEATURES,CONFIG,[model],['state'],10000)['fallback'])
        changed={**CONFIG,'observation_memory':'bounded','observation_memory_chars':3000}
        self.assertTrue(artifact.recommend(FEATURES,changed,[model],['state'],10000)['fallback'])

    def test_solver_records_only_executed_tools_and_keeps_value_until_final(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); task_dir=root/'task'; (task_dir/'workspace').mkdir(parents=True)
            (task_dir/'workspace/data').write_text('42')
            task=Task(task_dir,'case','math','Compute 6*7',1)
            budget=Budget(5000,time.monotonic()+20)
            class Client:
                timeout=10
                def __init__(self): self.messages=[]
                def complete(self,messages,*args):
                    self.messages.append(messages); budget.spent+=10
                    responses=[{'action':{'action':'bash','command':"python3 -c 'print(6*7)'"}},
                               {'action':{'action':'read','path':'data'}},
                               {'action':{'action':'read','path':'data'},'state_patch':{'observation_memory':{'fake':'42'}}},
                               {'action':{'action':'final','answer':'42'}}]
                    return json.dumps(responses[len(self.messages)-1])
            client=Client()
            config=SimpleNamespace(context_mode='state',response_protocol='unified',observation_memory='bounded',
                observation_memory_chars=3000,task_seconds=15,task_budget=5000,max_steps=6,
                history_chars=24000,max_output_tokens=900,tool_seconds=2,tool_output_chars=12000)
            trace=Trace(root/'trace.jsonl')
            outcome=solve(task,client,budget,trace,config)
            self.assertEqual(outcome['status'],'submitted')
            frame=json.loads(client.messages[-1][-1]['content'])
            records=frame['observation_memory']['records']
            self.assertEqual([r['id'] for r in records],['o1'])
            self.assertEqual(records[0]['result']['output'],'42\n')
            events=[json.loads(line) for line in (root/'trace.jsonl').read_text().splitlines()]
            self.assertEqual(sum(e['event']=='observation_memory' for e in events),2)
            self.assertEqual((task_dir/'answer.txt').read_text(),'42\n')

    def test_failed_runtime_validation_survives_later_read(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); task_dir=root/'task'; work=task_dir/'workspace';work.mkdir(parents=True)
            (work/'library.py').write_text('x=1\n')
            (work/'test_mylib.py').write_text('import unittest\nclass T(unittest.TestCase):\n def test_broken(self):self.assertEqual(1,2)\nif __name__=="__main__":unittest.main()\n')
            task=Task(task_dir,'case','coding','Fix library.py and run tests',1)
            budget=Budget(5000,time.monotonic()+20)
            class Client:
                timeout=10
                def __init__(self):self.messages=[]
                def complete(self,messages,*args):
                    self.messages.append(messages);budget.spent+=10
                    actions=[{'action':'final','answer':'DONE'},{'action':'read','path':'library.py'},{'action':'skip','reason':'not fixed'}]
                    return json.dumps({'action':actions[len(self.messages)-1]})
            client=Client()
            config=SimpleNamespace(context_mode='state',response_protocol='unified',observation_memory='bounded',
                observation_memory_chars=3000,task_seconds=15,task_budget=5000,max_steps=3,
                history_chars=24000,max_output_tokens=900,tool_seconds=2,tool_output_chars=12000)
            outcome=solve(task,client,budget,Trace(root/'trace.jsonl'),config)
            self.assertEqual(outcome['status'],'skipped')
            frame=json.loads(client.messages[-1][-1]['content'])
            record=frame['observation_memory']['records'][0]
            self.assertEqual(record['action']['command'],'python3 test_mylib.py')
            self.assertEqual(record['result']['returncode'],1)
            self.assertIn('AssertionError',record['result']['output'])
            self.assertFalse((task_dir/'answer.txt').exists())
