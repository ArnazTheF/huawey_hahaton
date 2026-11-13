"""Controlled live recall probe after real tools; not an end-to-end solve score.

Run inside Docker with baseline/scripts source mounts and an env file. Fixed tool
prefix intentionally supplies a correct computation, then obscures it with a read.
Only the final model call is live; reference answers are never loaded here.
"""
import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from baseline.client import Client
from baseline.context import Context
from baseline.core import Budget, StopRun, Trace
from baseline.input_estimator import InputEstimator
from baseline.observation_memory import ObservationMemory
from baseline.solver import UNIFIED_SYSTEM
from baseline.tools import execute


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tasks-dir',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--arms',nargs='+',choices=['off','bounded'],default=['off','bounded'])
    parser.add_argument('--budget',type=float,default=1000,help='Shared ceiling across all requested arms')
    args=parser.parse_args()
    if not 0 < args.budget <= 1000:parser.error('--budget must be in (0,1000]')
    args.out.mkdir(parents=True,exist_ok=False)
    task_dir=args.tasks_dir/'snapshot_revenue'
    meta=json.loads((task_dir/'task.json').read_text())
    rows=[]
    spent=0
    with tempfile.TemporaryDirectory(prefix='memory-recall-') as directory:
        root=Path(directory)
        shutil.copytree(task_dir/'workspace',root,dirs_exist_ok=True)
        action={'action':'bash','command':'''python3 - <<'PY'
import csv
best={}
with open('snapshots.csv',newline='') as f:
    for row in csv.DictReader(f):
        key=row['order_id']
        if key not in best or int(row['revision']) >= int(best[key]['revision']):
            best[key]=row
print(sum(int(row['units'])*int(row['unit_cents']) for row in best.values() if row['status']=='open'))
PY'''}
        result=execute(action,root,5,12000)
        if result['returncode'] or result['timeout']:
            raise RuntimeError('Controlled computation failed')
        read={'action':'read','path':'snapshots.csv'}
        content=execute(read,root,5,500)
        for arm in args.arms:
            context=Context('state')
            memory=ObservationMemory(root) if arm=='bounded' else None
            context.observations=memory
            for step,act,res in [(0,action,result),(1,read,content)]:
                if memory:memory.observe(act,res,step)
                context.observe(act,res,step)
            runtime={'steps_remaining':1,'task_budget_remaining':500,
                     'completion':{'phase':'submit','instruction':'Return only final with an evidence-supported answer, or skip. No tools.'}}
            initial={'role':'user','content':meta['instruction']+'\nWorkspace files:\nsnapshots.csv'}
            messages=context.messages(UNIFIED_SYSTEM,initial,runtime,24000)
            remaining=args.budget-spent
            budget=Budget(remaining,time.monotonic()+60,estimator=InputEstimator('calibrated'))
            client=Client(os.environ['LLM_BASE_URL'],os.environ['LLM_API_KEY'],'qwen3.8-27b-noreason',budget,Trace(args.out/(arm+'.jsonl')),45,reasoning_budget=0)
            row={'arm':arm,'model':'qwen3.8-27b-noreason',
                 'computed_result_visible':result['output'].strip() in messages[-1]['content'],
                 'visible_memory_chars':len(json.dumps(memory.frame('o2'),ensure_ascii=False,separators=(',',':'))) if memory else 0}
            try:
                row['completion_cap'],row['input_estimate']=budget.allowance(messages,128,remaining,client.model)
                raw=client.complete(messages,'snapshot_revenue',128,remaining)
                response=context.parse(raw)
                terminal=context.accept(response)
                if terminal['action'] not in ('final','skip'):
                    raise ValueError('Submission permits only final/skip')
                row['action']=terminal
            except ValueError as exc:
                row['error']=str(exc)
            except StopRun as exc:
                row['send_error']=str(exc)
            row['cost']=budget.spent
            spent+=budget.spent
            rows.append(row)
            print(json.dumps(row,ensure_ascii=False),flush=True)
            (args.out/'results.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
            if 'send_error' in row:break


if __name__=='__main__':main()
