import json,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from baseline.core import Budget,Trace,StopRun
from baseline.client import Client
from baseline.orchestration import Pacer

class ReasoningBudgetTests(unittest.TestCase):
    def client(self,root,model,limit):
        return Client('https://example.invalid/v1','test-secret',model,Budget(10000,time.monotonic()+30),Trace(root/'trace'),reasoning_budget=limit)
    def response(self):
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,limit):return json.dumps({'choices':[{'message':{'content':'OK'}}],'usage':{'prompt_tokens':100,'completion_tokens':20}}).encode()
        return Response()
    def test_reasoning_disabled_sends_no_request(self):
        with tempfile.TemporaryDirectory() as d,patch('urllib.request.urlopen') as request:
            c=self.client(Path(d),'qwen3.8-27b',0)
            with self.assertRaises(StopRun):c.complete([],'task',400,5000)
            request.assert_not_called()
    def test_whole_reasoning_call_charged_without_reasoning_usage_details(self):
        with tempfile.TemporaryDirectory() as d,patch('urllib.request.urlopen',return_value=self.response()) as request:
            c=self.client(Path(d),'qwen3.8-27b',60)
            c.complete([],'task',400,5000)
            self.assertEqual(c.reasoning_spent,30)
            with self.assertRaises(StopRun):c.complete([],'task',400,5000)
            self.assertEqual(request.call_count,1)
            payload=json.loads(request.call_args.args[0].data)
            self.assertLess(payload['max_tokens'],60)
    def test_noreason_is_not_blocked_by_zero_reasoning_allowance(self):
        with tempfile.TemporaryDirectory() as d,patch('urllib.request.urlopen',return_value=self.response()):
            c=self.client(Path(d),'qwen3.8-27b-noreason',0)
            self.assertEqual(c.complete([],'task',100,5000),'OK')
            self.assertEqual(c.reasoning_spent,0)
    def test_advisory_pacing_does_not_hard_cut_task(self):
        self.assertEqual(Pacer('weighted').allocate(1200,1000,2,[2,4]),400)
        self.assertEqual(Pacer('advisory').allocate(1200,1000,2,[2,4]),1000)
