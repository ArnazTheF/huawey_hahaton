import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from baseline.core import Budget, Task, Trace
from baseline.input_estimator import InputEstimator, prompt_bytes
from baseline.completion import CompletionPolicy
from baseline.solver import solve


class InputEstimatorTests(unittest.TestCase):
    def test_legacy_and_cold_start_preserved(self):
        messages=[{'role':'user','content':'x'*5000}]
        for mode in ('legacy','calibrated'):
            self.assertEqual(InputEstimator(mode).estimate(messages,'m'),prompt_bytes(messages)+256)

    def test_calibration_uses_past_usage_and_isolates_models(self):
        messages=[{'role':'user','content':'x'*5000}]
        estimator=InputEstimator('calibrated')
        old=estimator.estimate(messages,'m')
        estimator.observe(messages,1250,'m')
        self.assertLess(estimator.estimate(messages,'m'),old)
        self.assertGreater(estimator.estimate(messages,'m'),1250)
        self.assertEqual(estimator.estimate(messages,'other'),old)
        for invalid in (None,-1,0,float('nan'),True,'100'):
            estimator.observe(messages,invalid,'m')
        self.assertEqual(len(estimator.ratios['m']),1)

    def test_dense_numeric_input_has_independent_guard(self):
        estimator=InputEstimator('calibrated')
        prose=[{'role':'user','content':'ordinary prose ' * 100}]
        estimator.observe(prose,300,'m')
        dense=[{'role':'user','content':'1234567890,' * 1000}]
        self.assertGreater(estimator.estimate(dense,'m'),10000)

    def test_guard_uses_recent_high_ratio(self):
        messages=[{'role':'user','content':'text'}]
        estimator=InputEstimator('calibrated')
        estimator.observe(messages,1000,'m'); estimator.observe(messages,100,'m')
        self.assertGreater(estimator.estimate(messages,'m'),1000)
        self.assertLessEqual(len(estimator.ratios['m']),32)

    def test_calibration_can_admit_request_legacy_rejects(self):
        from baseline.core import StopRun
        messages=[{'role':'user','content':'x'*5000}]
        legacy=Budget(2000,time.monotonic()+10)
        with self.assertRaises(StopRun): legacy.allowance(messages,100,500,'m')
        estimator=InputEstimator('calibrated');estimator.observe(messages,1250,'m')
        calibrated=Budget(2000,time.monotonic()+10,estimator=estimator)
        cap,estimate=calibrated.allowance(messages,100,500,'m')
        self.assertEqual(cap,100); self.assertLess(estimate/10+cap,500)


class CompletionTests(unittest.TestCase):
    def config(self,**kwargs):
        values=dict(task_seconds=30,task_budget=8000,max_steps=3,history_chars=24000,
                    max_output_tokens=1500,tool_seconds=2,tool_output_chars=12000,
                    response_protocol='unified',context_mode='state',budget_policy='reserve',
                    finish_output_tokens=256,finish_seconds=1)
        values.update(kwargs);return SimpleNamespace(**values)

    def test_phase_transitions_and_reserve(self):
        policy=CompletionPolicy(self.config())
        work=policy.frame(8,100,2000,1000)
        self.assertEqual(work['phase'],'work')
        self.assertLess(policy.request_budget(work,2000),2000)
        self.assertEqual(policy.frame(2,100,2000,1000)['phase'],'verify')
        for steps,seconds,available in ((1,100,2000),(8,.5,2000),(8,100,400)):
            frame=policy.frame(steps,seconds,available,1000)
            self.assertEqual(frame['phase'],'submit')
            self.assertEqual(policy.request_budget(frame,available),available)
            with self.assertRaises(ValueError):policy.validate_action(frame,{'action':'write'})

    def run_case(self,actions,config,coding=False):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        root=Path(temp.name);taskdir=root/'task';taskdir.mkdir()
        task=Task(taskdir,'synthetic','coding' if coding else 'math','Compute/fix',1)
        if coding:
            task.workspace.mkdir()
            (task.workspace/'mylib.py').write_text('def add(a,b): return a-b\n')
            (task.workspace/'test_mylib.py').write_text('from mylib import add\nassert add(2,3)==5\n')
        budget=Budget(10000,time.monotonic()+30)
        frames=[]; allowances=[];responses=iter(actions)
        class Fake:
            timeout=10
            def complete(self,messages,task_id,cap,available):
                frame=json.loads(messages[-1]['content'])['runtime']['completion']
                frames.append(frame);allowances.append((cap,available))
                budget.spent+=10
                action=next(responses)
                return json.dumps({'action':action})
        trace=Trace(root/'trace')
        result=solve(task,Fake(),budget,trace,config)
        return result,frames,allowances,taskdir,trace

    def test_fix_verify_then_submit_in_reserved_last_step(self):
        result,frames,allowances,taskdir,trace=self.run_case([
            {'action':'write','path':'mylib.py','content':'def add(a,b): return a+b\n'},
            {'action':'bash','command':'python3 test_mylib.py'},
            {'action':'final','answer':'DONE'},
        ],self.config(),coding=True)
        self.assertEqual([f['phase'] for f in frames],['work','verify','submit'])
        self.assertEqual(result['status'],'submitted')
        self.assertEqual((taskdir/'answer.txt').read_text(),'DONE\n')
        self.assertEqual(allowances[-1][0],256)
        self.assertLess(allowances[0][1],8000)

    def test_no_automatic_done_when_tests_fail(self):
        result,frames,_,taskdir,_=self.run_case([{'action':'final','answer':'DONE'}],self.config(max_steps=1),coding=True)
        self.assertEqual(result['status'],'skipped')
        self.assertFalse((taskdir/'answer.txt').exists())

    def test_last_step_tool_and_patch_never_execute(self):
        result,frames,_,taskdir,trace=self.run_case([{'action':'bash','command':'touch should_not_exist'}],self.config(max_steps=1))
        self.assertEqual(result['status'],'skipped')
        events=[json.loads(line) for line in trace.path.read_text().splitlines()]
        self.assertFalse(any(e['event']=='tool' and 'returncode' in e['result'] for e in events))
        self.assertFalse((taskdir/'answer.txt').exists())

    def test_skip_in_completion_is_not_submitted(self):
        result,_,_,taskdir,_=self.run_case([{'action':'skip','reason':'no verified answer'}],self.config(max_steps=1))
        self.assertEqual(result['status'],'skipped');self.assertFalse((taskdir/'answer.txt').exists())
