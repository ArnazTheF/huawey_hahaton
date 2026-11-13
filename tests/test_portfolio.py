import copy,json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from baseline.core import Task,MODELS
from baseline.task_features import task_features,screen_task,family_id
from baseline.portfolio import Portfolio,settings,quantile

CONFIG=dict(response_protocol='unified',input_estimator='calibrated',budget_policy='reserve',max_steps=12,max_output_tokens=1500,task_budget=8000,finish_output_tokens=256,finish_seconds=20)
FEATURES=dict(task_type='coding',instruction_chars=100,file_count=3,workspace_bytes=200,test_files=1)
def row(family,model=MODELS[0],mode='state',success=True,cost=100):
    return dict(family=family,model=model,mode=mode,settings=CONFIG.copy(),features=FEATURES.copy(),success=success,cost=cost,prefixes=[{'calls':0,'spent':0},{'calls':1,'spent':25}])

def portfolio(rows):return Portfolio({'schema':1,'kind':'empirical-family-baseline','rows':rows})

class PortfolioTests(unittest.TestCase):
    def test_all_four_models_are_candidates_and_unseen_pairs_abstain(self):
        p=portfolio([row(str(i),MODELS[0]) for i in range(3)])
        result=p.recommend(FEATURES,CONFIG,MODELS,['history','state','hybrid'],1000)
        self.assertEqual(len(result['candidates']),12)
        self.assertEqual(result['recommendation']['model'],MODELS[0])
        self.assertTrue(all(not r['supported'] for r in result['candidates'] if r['model']!=MODELS[0]))
        self.assertTrue(p.recommend(FEATURES,CONFIG,[MODELS[-1]],['state'],1000)['fallback'])

    def test_duplicate_attempts_cannot_supply_independent_support(self):
        p=portfolio([row('same') for _ in range(30)])
        self.assertTrue(p.recommend(FEATURES,CONFIG,[MODELS[0]],['state'],1000)['fallback'])

    def test_family_held_out_and_config_shift_abstain(self):
        p=portfolio([row(str(i)) for i in range(3)])
        self.assertTrue(p.recommend(FEATURES,CONFIG,[MODELS[0]],['state'],1000,exclude_family='0')['fallback'])
        different={**CONFIG,'budget_policy':'off'}
        self.assertTrue(p.recommend(FEATURES,different,[MODELS[0]],['state'],1000)['fallback'])

    def test_cost_utility_and_success_are_separate(self):
        rows=[row(str(i),MODELS[0],cost=200) for i in range(4)]
        rows += [row(str(i),MODELS[1],cost=100) for i in range(4)]
        p=portfolio(rows)
        result=p.recommend(FEATURES,CONFIG,MODELS[:2],['state'],1000)
        self.assertEqual(result['recommendation']['model'],MODELS[1])
        self.assertTrue(p.recommend(FEATURES,CONFIG,MODELS[:2],['state'],50)['fallback'])
        self.assertFalse(result['recommendation']['calibrated'])

    def test_failed_censored_attempts_are_not_successful_completion_costs(self):
        p=portfolio([row('fail'+str(i),success=False,cost=10) for i in range(4)])
        r=p.recommend(FEATURES,CONFIG,[MODELS[0]],['state'],1000)
        self.assertTrue(r['fallback']);self.assertIsNone(r['candidates'][0]['successful_cost_p90'])

    def test_remaining_forecast_is_shadow_and_uses_prefix_progress(self):
        p=portfolio([row(str(i)) for i in range(3)])
        r=p.remaining_forecast(FEATURES,CONFIG,MODELS[0],'state',1,25)
        self.assertEqual(r['remaining_p50'],75);self.assertFalse(r['auto_stop'])
        self.assertFalse(p.remaining_forecast(FEATURES,CONFIG,MODELS[1],'state',1,25)['supported'])

    def test_out_of_distribution_task_abstains(self):
        p=portfolio([row(str(i)) for i in range(3)])
        unseen={**FEATURES,'workspace_bytes':10**12,'file_count':10000}
        self.assertTrue(p.recommend(unseen,CONFIG,[MODELS[0]],['state'],10000)['fallback'])

    def test_unknown_model_in_artifact_is_rejected(self):
        with self.assertRaises(ValueError):portfolio([row('x','not-permitted')])

    def test_off_policy_config_ignores_unused_finish_parameters(self):
        c=SimpleNamespace(**{**CONFIG,'budget_policy':'off'})
        self.assertIsNone(settings(c)['finish_output_tokens'])
        self.assertEqual(quantile([10,20,30],.9),30)

class FeaturesAndScreeningTests(unittest.TestCase):
    def test_features_ignore_labels_and_screens_never_claim_impossible(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'workspace').mkdir()
            (root/'workspace/data.csv').write_text('v\n1\n')
            task=Task(root,'any','generic','Read missing.csv; create answer.txt.',1)
            before=task_features(task)
            (root/'task.json').write_text(json.dumps({'expected':'secret','check':'exact_str'}))
            self.assertEqual(task_features(task),before)
            report=screen_task(task)
            self.assertFalse(report['auto_reject']);self.assertEqual(report['verdict'],'unknown')
            self.assertEqual([r['path'] for r in report['findings']],['missing.csv'])
            task.instruction='Create fresh.csv from data.csv'
            self.assertFalse(screen_task(task)['auto_reject'])

    def test_family_grouping_normalizes_instance_numbers(self):
        a=Task(Path('/tmp/a'),'a','math','Compute 7 + 9',1)
        b=Task(Path('/tmp/b'),'b','math','Compute 14 + 31',5)
        self.assertEqual(family_id(a),family_id(b))

class TrainingDataTests(unittest.TestCase):
    def test_only_external_labels_and_initial_features_are_used(self):
        from scripts.train_portfolio import collect
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);folder=root/'experiment'/'state';taskdir=folder/'tasks'/'case'
            (taskdir/'workspace').mkdir(parents=True)
            (taskdir/'task.json').write_text(json.dumps({'task_id':'case','task_type':'coding','instruction':'Fix this','reward':1}))
            (taskdir/'workspace'/'solution_after_run.py').write_text('x'*10000)
            logs=folder/'tasks'/'.baseline';logs.mkdir()
            (logs/'run.json').write_text(json.dumps({'model':MODELS[0]}))
            request={'event':'request','task_id':'case','model':MODELS[0],'messages':[{'role':'system','content':'rules'},{'role':'user','content':'Fix this\nWorkspace files:\noriginal.py\ntest_original.py'}]}
            (logs/'run.jsonl').write_text(json.dumps(request)+'\n')
            result={'mode':'state','task_id':'case','status':'submitted','passed':False,'cost':100}
            (root/'experiment'/'results.json').write_text(json.dumps([result]))
            rows,_=collect(root)
            self.assertEqual(len(rows),1);self.assertFalse(rows[0]['success'])
            self.assertEqual(rows[0]['features']['file_count'],2)
            self.assertIsNone(rows[0]['features']['workspace_bytes'])
            del result['passed'];(root/'experiment'/'results.json').write_text(json.dumps([result]))
            rows,_=collect(root);self.assertEqual(rows,[])

class RoutingIntegrationTests(unittest.TestCase):
    @unittest.skipUnless(__import__('importlib.util',fromlist=['find_spec']).find_spec('openjiuwen'),'openJiuwen not installed')
    def test_learned_selection_switches_real_client_payload_and_logs_risk(self):
        import asyncio,os,sys
        from unittest.mock import patch
        import run_agent
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);task=root/'tasks'/'math';task.mkdir(parents=True)
            (task/'task.json').write_text(json.dumps({'task_id':'math','task_type':'math','instruction':'Compute 6*7. missing.csv is absent.','reward':1}))
            rows=[row(str(i),MODELS[1]) for i in range(3)]
            for r in rows:r['features']=task_features(Task(task,'math','math','Compute 6*7. missing.csv is absent.',1))
            artifact=root/'artifact.json';artifact.write_text(json.dumps({'schema':1,'kind':'empirical-family-baseline','rows':rows}))
            with patch.object(sys,'argv',['run_agent.py','--tasks-dir',str(root/'tasks'),'--selector-artifact',str(artifact),'--selection-policy','learned','--budget','1000']):args=run_agent.arguments()
            class Response:
                def __enter__(self):return self
                def __exit__(self,*args):pass
                def read(self,limit):return json.dumps({'choices':[{'message':{'content':'{"action":{"action":"final","answer":"42"}}'}}],'usage':{'prompt_tokens':100,'completion_tokens':20}}).encode()
            with patch.dict(os.environ,{'LLM_BASE_URL':'https://example.invalid/v1','LLM_API_KEY':'private-key'}),patch('urllib.request.urlopen',return_value=Response()) as request:
                code=asyncio.run(run_agent.main(args))
            self.assertEqual(code,0)
            self.assertEqual(json.loads(request.call_args.args[0].data)['model'],MODELS[1])
            summary=json.loads(next((root/'tasks'/'.baseline').glob('*.json')).read_text())
            self.assertEqual(summary['tasks'][0]['model'],MODELS[1])
            self.assertEqual(summary['tasks'][0]['context_mode'],'state')
            logs=[json.loads(line) for f in (root/'tasks'/'.baseline').glob('*.jsonl') for line in f.read_text().splitlines()]
            self.assertTrue(any(e['event']=='screening' and e['findings'] and not e['auto_reject'] for e in logs))
            self.assertEqual((task/'answer.txt').read_text(),'42\n')
