"""Chronological, no-API replay of prompt estimation against recorded usage."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from baseline.input_estimator import InputEstimator


def main():
    p=argparse.ArgumentParser();p.add_argument('--traces',type=Path,required=True);p.add_argument('--out',type=Path,required=True);args=p.parse_args()
    rows=[]
    for file in sorted(args.traces.rglob('*.jsonl')):
        estimator=InputEstimator('calibrated');legacy=InputEstimator();pending={}
        for line in file.read_text().splitlines():
            event=json.loads(line)
            if event['event']=='request':pending[event['task_id']]=event
            elif event['event']=='response' and event.get('usage'):
                request=pending.pop(event['task_id'],None)
                if not request:continue
                usage=event['usage'];actual=usage.get('prompt_tokens',usage.get('input_tokens'))
                if not isinstance(actual,(int,float)) or actual<=0:continue
                model=request['model'];messages=request['messages']
                rows.append({'trace':str(file),'task_id':event['task_id'],'actual':actual,'legacy':legacy.estimate(messages,model),'calibrated':estimator.estimate(messages,model),'cold_start':not bool(estimator.ratios[model])})
                estimator.observe(messages,actual,model)
    report={'note':'Retrospective descriptive replay; no future usage used at each prediction. Not an independent validation dataset; no budget/quality conclusions.', 'calls':len(rows),'cold_starts':sum(r['cold_start'] for r in rows),'metrics':{},'rows':rows}
    for method in ('legacy','calibrated'):
        report['metrics'][method]={'mae':sum(abs(r[method]-r['actual']) for r in rows)/max(1,len(rows)),'underestimates':sum(r[method]<r['actual'] for r in rows)}
    args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(report,indent=2))
    print(json.dumps({k:v for k,v in report.items() if k!='rows'},indent=2))
if __name__=='__main__':main()
