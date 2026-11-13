"""Build a transparent empirical artifact from externally graded experiments.
Only results.json labels train success. Submitted alone is never a success label.
"""
import argparse, hashlib, json, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from baseline.core import load_tasks
from baseline.task_features import family_id, task_features
from baseline.portfolio import Portfolio, SETTINGS, normalize_settings


def collect(root):
    rows=[];seen=set();skipped=0
    for file in sorted(root.rglob('results.json')):
        manifest_path=file.parent/'manifest.json'
        manifest=json.loads(manifest_path.read_text()) if manifest_path.is_file() else {}
        results=json.loads(file.read_text())
        # Benchmark aggregates are dictionaries; their cohort lists are collected
        # separately below. Never train on the same attempts a second time.
        if not isinstance(results,list):continue
        for result in results:
            if not isinstance(result,dict):
                skipped+=1;continue
            if result.get('tool_output_chars',12000)!=12000 or result.get('orchestration','off')!='off' or result.get('experience_file') or result.get('pacing','off')!='off':
                skipped+=1;continue
            if not isinstance(result.get('passed'),bool):
                skipped+=1;continue
            folder=file.parent/result.get('run_folder',result['mode'])
            if not folder.is_dir():skipped+=1;continue
            tasks={t.task_id:t for t in load_tasks(folder/'tasks')}
            task=tasks.get(result['task_id'])
            if task is None or result.get('status') in ('not_attempted','existing_answer','error','stopped'):
                skipped+=1;continue
            summaries=list((folder/'tasks'/'.baseline').glob('*.json'))
            if len(summaries)!=1:skipped+=1;continue
            summary=json.loads(summaries[0].read_text())
            config={k:result.get('settings',{}).get(k,summary.get('settings',{}).get(k,summary.get(k,result.get(k,manifest.get(k))))) for k in SETTINGS}
            # These original experiments predate their CLI flags; their verified defaults are explicit here.
            config['response_protocol']=config['response_protocol'] or 'legacy'
            config['input_estimator']=config['input_estimator'] or 'legacy'
            config['budget_policy']=config['budget_policy'] or 'off'
            config=normalize_settings(config)
            if config['budget_policy']=='off':config['finish_output_tokens']=None;config['finish_seconds']=None
            model=result.get('model',summary['model'])
            key=(str(folder.resolve()),task.task_id)
            if key in seen:continue
            seen.add(key)
            tracefiles=list((folder/'tasks'/'.baseline').glob('*.jsonl'))
            events=[json.loads(line) for f in tracefiles for line in f.read_text().splitlines()]
            prefixes=[{'calls':0,'spent':0}];spent=0;calls=0
            for e in events:
                if e.get('task_id')==task.task_id and e['event']=='response':
                    spent+=e['cost'];calls+=1;prefixes.append({'calls':calls,'spent':spent})
            # Use initial snapshots, never the patched workspace after a run.
            starts=[e for e in events if e['event']=='task_start' and e.get('task_id')==task.task_id]
            if starts:
                features=starts[0]['features'];feature_source='task_start'
            else:
                requests=[e for e in events if e['event']=='request' and e.get('task_id')==task.task_id]
                if not requests:skipped+=1;continue
                initial=requests[0]['messages'][1]['content']
                listing=initial.split('Workspace files:\n',1)[-1].splitlines() if 'Workspace files:\n' in initial else []
                features={'task_type':task.task_type,'instruction_chars':len(task.instruction),
                    'file_count':len(listing),'workspace_bytes':None,
                    'test_files':sum(Path(name).name.startswith('test') and name.endswith('.py') for name in listing)}
                feature_source='initial_request; original byte sizes unavailable'
            rows.append({'family':family_id(task),'features':features,'feature_source':feature_source,'model':model,
                'mode':result['mode'],'settings':config,'success':bool(result['passed']),
                'cost':float(result['cost']),'reason':result.get('reason'),
                'censored':result.get('status')=='skipped','prefixes':prefixes,
                'source':str(file),'task_id':task.task_id,'label_source':'external_grader'})
    return rows,skipped


def main():
    p=argparse.ArgumentParser();p.add_argument('--runs',type=Path,default=Path('runs'));p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    rows,skipped=collect(a.runs)
    artifact={'schema':1,'kind':'empirical-family-baseline','rows':rows,'min_groups':3}
    model=Portfolio(artifact);evaluations=[]
    for row in rows:
        pred=model.recommend(row['features'],row['settings'],[row['model']],[row['mode']],float('inf'),exclude_family=row['family'])
        if pred['recommendation']:
            guess=pred['recommendation'];evaluations.append({'family':row['family'],'success':row['success'],'probability':guess['success_probability_estimate'],'actual_cost':row['cost'],'predicted_cost':guess['expected_attempt_cost']})
    report={'attempts':len(rows),'families':len({r['family'] for r in rows}),'models':sorted({r['model'] for r in rows}),
            'skipped_records':skipped,'leave_family_out_predictions':len(evaluations),'leave_family_out_abstentions':len(rows)-len(evaluations),
            'note':'Groups are number-normalized instruction templates, not verified semantic families. Whole-group holdout; sparse pairs abstain. No generalization claim.', 'evaluation':evaluations}
    a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(artifact,indent=2))
    a.out.with_suffix('.report.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({k:v for k,v in report.items() if k!='evaluation'},indent=2))
if __name__=='__main__':main()
