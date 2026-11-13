import json
import tempfile
import unittest
import contextlib
import io
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path

from scripts.benchmark_report import outcome, summarize, write_report
from scripts.build_benchmark_suite import build, validate_catalog


class BenchmarkTests(unittest.TestCase):
    def test_exact_duplicates_keep_aliases_but_data_and_grader_variants_stay_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'source';source.mkdir()
            for name, data, gold in [('a','42','42'),('b','42','42'),('c','43','43'),('d','42','different')]:
                case=source/name;(case/'workspace').mkdir(parents=True)
                (case/'task.json').write_text(json.dumps({'task_id':name,'task_type':'math','instruction':'Read data','reward':1,'expected':gold,'check':'exact_str'}))
                (case/'workspace/data.txt').write_text(data)
            catalog=build([source],root/'suite')
            self.assertEqual(catalog['unique_cases'],3)
            self.assertEqual(catalog['source_cases'],4)
            self.assertEqual(sorted(len(c['sources']) for c in catalog['cases']),[1,1,2])
            self.assertEqual(len(list((root/'suite/reference').glob('*/task.json'))),3)

    def test_statuses_never_turn_skip_or_unattempted_into_success(self):
        rows=[{'task_id':'a','passed':True,'status':'submitted','score':5,'reward':5,'cost':100},
              {'task_id':'b','passed':False,'status':'submitted','score':0,'reward':4,'cost':20},
              {'task_id':'c','passed':False,'status':'not_attempted','score':0,'reward':3,'cost':0},
              {'task_id':'d','passed':False,'status':'skipped','correct_skip':True,'score':0,'reward':2,'cost':10}]
        self.assertEqual([outcome(r) for r in rows],['SOLVED','WRONG_ANSWER','NOT_ATTEMPTED','IMPOSSIBLE_SKIP'])
        result=summarize(rows)
        self.assertEqual((result['solved'],result['attempts'],result['score'],result['not_attempted']),(1,4,5,1))
        self.assertEqual(result['solved_tasks'],['a'])
        self.assertEqual(result['unsolved_tasks'],['b','c','d'])

    def test_workspace_resource_named_task_json_is_copied_not_discovered_as_a_case(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);case=root/'source'/'case';(case/'workspace').mkdir(parents=True)
            (case/'task.json').write_text(json.dumps({'task_id':'case','task_type':'search','instruction':'Read resource','reward':1,'expected':'ok','check':'exact_str'}))
            (case/'workspace/task.json').write_text('[1,2,3]')
            catalog=build([root/'source'],root/'suite')
            self.assertEqual(catalog['unique_cases'],1)
            resource=root/'suite/reference'/catalog['cases'][0]['task_id']/'workspace/task.json'
            self.assertEqual(resource.read_text(),'[1,2,3]')

    def test_new_cases_or_changed_frozen_files_require_catalog_refresh(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);case=root/'source'/'a';case.mkdir(parents=True)
            meta={'task_id':'a','task_type':'math','instruction':'Compute','reward':1,'expected':'2','check':'exact_int'}
            (case/'task.json').write_text(json.dumps(meta))
            catalog=build([root/'source'],root/'suite');path=root/'suite/catalog.json'
            self.assertEqual(validate_catalog(path)['unique_cases'],1)
            other=root/'source'/'b';other.mkdir()
            (other/'task.json').write_text(json.dumps({**meta,'task_id':'b','expected':'3'}))
            with self.assertRaisesRegex(ValueError,'corpus changed'):validate_catalog(path)
            (other/'task.json').unlink();other.rmdir()
            frozen=root/'suite/reference'/catalog['cases'][0]['task_id']/'task.json'
            frozen.write_text('{}')
            with self.assertRaisesRegex(ValueError,'Frozen reference'):validate_catalog(path)

    def test_report_includes_every_case_and_each_repeat_without_hiding_partial_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            rows=[{'task_id':'case','passed':True,'status':'submitted','score':1,'reward':1,'cost':10},
                  {'task_id':'missing','passed':False,'status':'not_attempted','score':0,'reward':2,'cost':0}]
            cohorts=[{'name':'r1_off','memory':'off','repetition':1,'rows':rows}]
            manifest={'suite':'all','model':'test','budget_per_arm':100,'task_budget':50,'max_steps':3,'cohort_order':[1,2]}
            report=write_report(root,cohorts,manifest)
            self.assertEqual(len(report['tasks']),2)
            text=(root/'report.md').read_text()
            self.assertIn('missing',text);self.assertIn('NOT_ATTEMPTED',text)
            self.assertIn('ещё не завершён',text)

    def test_portfolio_collector_skips_aggregate_reports(self):
        from scripts.train_portfolio import collect
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'results.json').write_text(json.dumps({'suite':'all','summary':{},'tasks':[]}))
            self.assertEqual(collect(root),([],0))

    def test_budget_stop_does_not_cancel_other_cohorts_and_resume_never_repeats_calls(self):
        from scripts import benchmark
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();(root/'scripts').mkdir()
            for name in ['scripts/benchmark.py','scripts/experiment.py','run_agent.py']:
                (root/name).write_text('# fixture\n')
            case=root/'experiments/combined-v1/eval/case';case.mkdir(parents=True)
            (case/'task.json').write_text(json.dumps({'task_id':'case','task_type':'math','instruction':'Compute','reward':1}))
            out=root/'run';calls=[]
            def fake_run(command,**kwargs):
                calls.append(command)
                folder=Path(command[command.index('--out')+1]);folder.mkdir()
                row={'task_id':'case','passed':False,'status':'stopped','reason':'insufficient_budget_for_request','score':0,'reward':1,'cost':5}
                (folder/'results.json').write_text(json.dumps([row]))
                return SimpleNamespace(returncode=0)
            argv=['benchmark','--suite','successful','--out',str(out),'--repetitions','2']
            with patch.object(benchmark,'ROOT',root),patch.object(benchmark,'__file__',str(root/'scripts/benchmark.py')),patch.object(benchmark.subprocess,'run',side_effect=fake_run),patch('sys.argv',argv),contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(benchmark.main(),0)
            self.assertEqual(len(calls),4)
            self.assertEqual([c[c.index('--observation-memory')+1] for c in calls],['off','bounded','bounded','off'])
            report=json.loads((out/'results.json').read_text());self.assertEqual(len(report['tasks']),4)
            with patch.object(benchmark,'ROOT',root),patch.object(benchmark,'__file__',str(root/'scripts/benchmark.py')),patch.object(benchmark.subprocess,'run',side_effect=AssertionError('Must reuse paid calls')),patch('sys.argv',argv+['--resume']),contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(benchmark.main(),0)

    def test_full_suite_rejects_starvation_and_reports_all_registered_cases(self):
        from scripts import benchmark
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();(root/'scripts').mkdir()
            for name in ['scripts/benchmark.py','scripts/experiment.py','run_agent.py']:
                (root/name).write_text('# fixture\n')
            for name,gold in [('a','2'),('b','3')]:
                case=root/'source'/name;case.mkdir(parents=True)
                (case/'task.json').write_text(json.dumps({'task_id':name,'task_type':'math','instruction':'Compute','reward':1,'expected':gold,'check':'exact_int'}))
            catalog=build([root/'source'],root/'suite')
            out=root/'run'
            argv=['benchmark','--catalog',str(root/'suite/catalog.json'),'--out',str(out),'--task-budget','1','--budget-per-arm','1','--repetitions','1']
            def fake_run(command,**kwargs):
                folder=Path(command[command.index('--out')+1]);folder.mkdir()
                rows=[{'task_id':c['task_id'],'passed':True,'status':'submitted','score':1,'reward':1,'cost':1} for c in catalog['cases']]
                (folder/'results.json').write_text(json.dumps(rows))
                return SimpleNamespace(returncode=0)
            with patch.object(benchmark,'ROOT',root),patch.object(benchmark,'__file__',str(root/'scripts/benchmark.py')),patch.object(benchmark.subprocess,'run',side_effect=fake_run) as run,contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
                with patch('sys.argv',argv),self.assertRaises(SystemExit):benchmark.main()
                run.assert_not_called()
                argv[argv.index('--budget-per-arm')+1]='2'
                with patch('sys.argv',argv):self.assertEqual(benchmark.main(),0)
                self.assertEqual(run.call_count,2)
            report=json.loads((out/'results.json').read_text())
            self.assertEqual(report['suite'],'all')
            self.assertEqual(len(report['tasks']),4)
            self.assertEqual({r['task_id'] for r in report['tasks']},{c['task_id'] for c in catalog['cases']})

    def test_solution_comparison_forwards_profile_features_but_keeps_common_limits(self):
        from scripts import benchmark
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();(root/'scripts').mkdir();(root/'configs').mkdir()
            for name in ['scripts/benchmark.py','scripts/experiment.py','run_agent.py']:
                (root/name).write_text('# fixture\n')
            profile=root/'configs/recommended.json'
            profile.write_text(json.dumps({'flags':['--model','qwen3.8-27b-noreason','--task-budget','9999',
                '--output-format','json_schema','--progress-state','--progress-domains','math','generic']}))
            case=root/'source/case';case.mkdir(parents=True)
            (case/'task.json').write_text(json.dumps({'task_id':'case','task_type':'math','instruction':'Compute',
                'reward':1,'expected':'2','check':'exact_int'}))
            catalog=build([root/'source'],root/'suite');calls=[]
            def fake_run(command,**kwargs):
                calls.append(command);folder=Path(command[command.index('--out')+1]);folder.mkdir()
                (folder/'results.json').write_text(json.dumps([{'task_id':catalog['cases'][0]['task_id'],
                    'passed':True,'status':'submitted','score':1,'reward':1,'cost':1}]))
                return SimpleNamespace(returncode=0)
            argv=['benchmark','--catalog',str(root/'suite/catalog.json'),'--out',str(root/'run'),
                  '--comparison','solution','--profile',str(profile),'--task-budget','2','--repetitions','1']
            with patch.object(benchmark,'ROOT',root),patch.object(benchmark,'__file__',str(root/'scripts/benchmark.py')),patch.object(benchmark.subprocess,'run',side_effect=fake_run),patch('sys.argv',argv),contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(benchmark.main(),0)
            self.assertNotIn('--output-format',calls[0]);self.assertIn('--progress-state',calls[1])
            self.assertEqual([c[c.index('--task-budget')+1] for c in calls],['2','2'])
            report=json.loads((root/'run/results.json').read_text())
            self.assertEqual(set(report['by_variant']),{'baseline','recommended'})
            self.assertEqual(report['by_variant']['recommended']['solved'],1)
            with self.assertRaisesRegex(ValueError,'different comparison protocol'):
                benchmark.solution_features({'flags':['--reasoning-budget','100']})
            with self.assertRaisesRegex(ValueError,'Unsupported'):
                benchmark.solution_features({'flags':['--unknown','on']})


if __name__=='__main__':unittest.main()
