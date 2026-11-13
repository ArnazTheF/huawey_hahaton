import copy,json,tempfile,time,unittest
from pathlib import Path
from types import SimpleNamespace
from baseline.core import Task,Budget,Trace,StopRun,MODELS
from baseline.experience import Experience
from baseline.orchestration import Pacer,route
from baseline.task_features import family_id

class OrchestrationTests(unittest.TestCase):
    def test_pacing_retains_global_limit_and_reallocates_unused_budget(self):
        p=Pacer('weighted')
        self.assertEqual(p.allocate(1200,1000,2,[2,4]),400)
        self.assertEqual(p.allocate(1000,1000,4,[4]),1000)
        self.assertEqual(p.allocate(100,1000,4,[4]),100)
        self.assertEqual(Pacer().allocate(500,1000,1,[1,2]),500)

    def test_experience_excludes_same_family_and_never_includes_answers(self):
        task=Task(Path('/tmp/a'),'a','coding','Fix integer allocation errors preserving exact arithmetic.',1)
        cards=[{'id':'self','family':family_id(task),'description':task.instruction,'lesson':'ignore me','verification':'external_grader'},
               {'id':'other','family':'different','description':'Fix exact integer arithmetic errors.','lesson':'Use integer division.','verification':'external_grader','answer':'secret'}]
        memory=Experience({'schema':1,'cards':cards,'behaviors':[]})
        note=memory.lesson(task)
        self.assertEqual(note['id'],'other');self.assertNotIn('secret',json.dumps(note))
        with self.assertRaises(ValueError):Experience({'schema':1,'cards':[{**cards[0],'verification':'model_said_so'}]})

    def test_router_only_selects_strategy_and_all_calls_are_charged(self):
        with tempfile.TemporaryDirectory() as directory:
            budget=Budget(1000,time.monotonic()+30);trace=Trace(Path(directory)/'trace')
            config=SimpleNamespace(light_model=MODELS[-1],router_model=MODELS[-1],model=MODELS[1],light_steps=6,light_budget=500,max_steps=24,task_budget=900,router_budget=400)
            class Fake:
                model=MODELS[1]
                def complete(self,messages,task_id,cap,available):
                    self.seen_model=self.model;self.available=available;budget.spent+=25
                    return '{"strategy":"light"}'
            client=Fake();result=route(Task(Path(directory),'a','math','Compute 2+2',1),{},client,budget,trace,config,Experience())
            self.assertEqual(result['strategy'],'light');self.assertEqual(result['cost'],25)
            self.assertEqual(client.model,MODELS[1]);self.assertEqual(client.seen_model,MODELS[-1])
            self.assertLessEqual(client.available,config.task_budget-320)

    def test_router_invalid_output_falls_back_without_leaking_model(self):
        with tempfile.TemporaryDirectory() as directory:
            budget=Budget(1000,time.monotonic()+30)
            config=SimpleNamespace(light_model=MODELS[-1],router_model=MODELS[-1],model=MODELS[1],light_steps=6,light_budget=500,max_steps=24,task_budget=900,router_budget=400)
            class Fake:
                model=MODELS[1]
                def complete(self,*args):budget.spent+=20;return '{"strategy":"use-unknown-model"}'
            client=Fake();result=route(Task(Path(directory),'a','math','Compute 2+2',1),{},client,budget,Trace(Path(directory)/'trace'),config,None)
            self.assertTrue(result['fallback']);self.assertEqual(result['cost'],20);self.assertEqual(client.model,MODELS[1])

    def test_unlabeled_observations_do_not_expose_grade(self):
        memory=Experience({'schema':1,'cards':[],'behaviors':[{'family':'other','description':'Compute a total','observations':[{'model':MODELS[1],'answer':'42','cost':10,'passed':True,'expected':'secret'}],'passed':True,'expected':'42'}]})
        result=memory.observations(Task(Path('/tmp'),'a','math','Compute a total amount',1))
        self.assertTrue(result);self.assertNotIn('passed',json.dumps(result));self.assertNotIn('expected',json.dumps(result))

class LivePathIntegrationTests(unittest.TestCase):
    @unittest.skipUnless(__import__('importlib.util',fromlist=['find_spec']).find_spec('openjiuwen'),'openJiuwen not installed')
    def test_router_and_solver_share_budget_and_use_state_and_experience(self):
        import asyncio,os,sys
        from unittest.mock import patch
        import run_agent
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);task=root/'tasks'/'task';task.mkdir(parents=True)
            (task/'task.json').write_text(json.dumps({'task_id':'task','task_type':'math','instruction':'Compute the integer total 6*7','reward':3}))
            memory=root/'experience.json'
            memory.write_text(json.dumps({'schema':1,'behaviors':[],'cards':[{'id':'lesson','family':'other','description':'Compute integer total using arithmetic','lesson':'Calculate with Python before submission.','verification':'external_grader'}]}))
            with patch.object(sys,'argv',['run_agent.py','--tasks-dir',str(root/'tasks'),'--budget','1000','--orchestration','boundary','--experience-file',str(memory),'--pacing','weighted']):args=run_agent.arguments()
            outputs=iter(['{"strategy":"full"}','{"action":{"action":"final","answer":"42"}}'])
            class Response:
                def __enter__(self):return self
                def __exit__(self,*args):pass
                def read(self,limit):return json.dumps({'choices':[{'message':{'content':next(outputs)}}],'usage':{'prompt_tokens':100,'completion_tokens':20}}).encode()
            with patch.dict(os.environ,{'LLM_BASE_URL':'https://example.invalid/v1','LLM_API_KEY':'private'}),patch('urllib.request.urlopen',return_value=Response()) as request:
                code=asyncio.run(run_agent.main(args))
            self.assertEqual(code,0)
            payloads=[json.loads(call.args[0].data) for call in request.call_args_list]
            self.assertEqual([p['model'] for p in payloads],[args.router_model,args.model])
            self.assertIn('Calculate with Python',json.dumps(payloads[1]['messages']))
            logs=task.parent/'.baseline';summary=json.loads(next(logs.glob('*.json')).read_text())
            self.assertEqual(summary['spent'],60)
            self.assertEqual(summary['tasks'][0]['cost'],60)
            self.assertEqual(summary['tasks'][0]['context_mode'],'state')
            self.assertEqual(summary['tasks'][0]['settings']['task_budget'],970)
            events=[json.loads(line) for f in logs.glob('*.jsonl') for line in f.read_text().splitlines()]
            self.assertTrue(any(e['event']=='routing' and e['cost']==30 for e in events))
