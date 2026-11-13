"""Build verified procedural cards; paired behavior uses no correctness labels."""
import argparse,collections,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from baseline.core import load_tasks
from baseline.task_features import family_id


def build(runs, seed=None):
    cards={}
    for file in sorted(runs.rglob('results.json')):
        if not isinstance(json.loads(file.read_text()),list):continue
        for result in json.loads(file.read_text()):
            if not isinstance(result,dict) or result.get('passed') is not True:continue
            folder=file.parent/result.get('run_folder',result.get('mode',''))/'tasks'
            if not folder.is_dir():continue
            task=next((t for t in load_tasks(folder) if t.task_id==result['task_id']),None)
            if task is None:continue
            lessons={
                'coding':'Inspect requirements and tests together. Preserve tests. Implement documented edge cases, use exact integer arithmetic where required, and run provided unittest tests before DONE. Save a verified candidate rather than repeating unchanged reads.',
                'data_analysis':'Inspect column names and a few rows only. Compute filtering, joins and aggregates in a Python script; avoid printing entire tables into the model context. Missing join matches need an explicit rule.',
                'search':'Use a short Python traversal for many linked files. Track visited identifiers and apply revision/status rules before following links. Ignore unrelated terminal values.',
                'math':'Compute in Python, preserve integer rounding and operation order. Submit the calculated value without an extra command to write answer.txt.',
            }
            if task.task_type not in lessons:continue
            family=family_id(task)
            cards[family]={'id':'lesson-'+family,'family':family,'description':task.instruction[:500],
                'lesson':lessons[task.task_type],'verification':'external_grader',
                'derivation':'deterministic procedural template; not LLM-distilled EET','source':str(file)}
    behaviors={}
    if seed:
        # Read raw summary+answers only. Do NOT consult seed/results.json grades.
        for summary_path in sorted(seed.glob('*/tasks/.baseline/*.json')):
            summary=json.loads(summary_path.read_text());folder=summary_path.parent.parent
            tasks={t.task_id:t for t in load_tasks(folder)}
            for record in summary['tasks']:
                task=tasks[record['task_id']];family=family_id(task)
                item=behaviors.setdefault(family,{'family':family,'description':task.instruction[:500],'observations':[]})
                answer=task.directory/'answer.txt'
                item['observations'].append({'model':record.get('model',summary['model']),
                    'mode':record.get('context_mode',summary['context_mode']),
                    'answer':answer.read_text().strip()[:120] if answer.is_file() else None,
                    'status':record['status'],'cost':round(record['cost'],1),'seconds':round(record['seconds'],1)})
                item['observations']=item['observations'][:8]
    return {'schema':1,'cards':list(cards.values()),'behaviors':list(behaviors.values())}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--runs',type=Path,default=Path('runs'));p.add_argument('--seed',type=Path);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    result=build(a.runs,a.seed);a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps({'cards':len(result['cards']),'behavior_groups':len(result['behaviors']),'output':str(a.out)}))
