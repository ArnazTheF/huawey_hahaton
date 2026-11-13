"""Capability check, not a task-quality benchmark; at most two short API calls."""
import argparse,json,os,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from baseline.client import Client
from baseline.core import Budget,Trace,StopRun
from baseline.input_estimator import InputEstimator
from baseline.protocol import parse_json,validate_response
from baseline.wire import response_format


def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);args=p.parse_args()
    args.out.mkdir(parents=True,exist_ok=False);rows=[]
    for mode in ('json_schema','json_object'):
        budget=Budget(1500,time.monotonic()+45,estimator=InputEstimator('calibrated'))
        client=Client(os.environ['LLM_BASE_URL'],os.environ['LLM_API_KEY'],'qwen3.8-27b-noreason',budget,Trace(args.out/(mode+'.jsonl')),timeout=35,reasoning_budget=0,response_format=response_format(mode))
        row={'mode':mode,'observed_usable':False}
        try:
            raw=client.complete([{'role':'system','content':'Return one JSON object: {"action":{"action":"final","answer":"OK"},"state_patch":{}}. No other text.'},{'role':'user','content':'Finish now with the answer OK.'}],'wire_capability',128,1500)
            action,patch=validate_response(parse_json(raw))
            row.update(observed_usable=action=={'action':'final','answer':'OK'},finish_reason=client.last_finish_reason)
        except (StopRun,ValueError) as exc:
            row['error']=str(exc)
        row['cost']=budget.spent;rows.append(row)
        (args.out/'results.json').write_text(json.dumps(rows,indent=2))
        print(json.dumps(row),flush=True)
        if row['observed_usable']:break
        if 'error'in row and not any(token in row['error'] for token in ('proxy_http_400','proxy_http_422')):break
    return 0 if any(r['observed_usable'] for r in rows) else 2


if __name__=='__main__':sys.exit(main())
