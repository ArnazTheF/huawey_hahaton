"""Docker/API quality benchmark. All registered tasks by default; named outcomes."""
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.benchmark_report import write_report
from scripts.build_benchmark_suite import validate_catalog


def solution_features(profile):
    """Read algorithm flags; benchmark model/caps remain identical in both arms."""
    flags=profile['flags'];result=[];index=0
    feature_sizes={'--output-format':1,'--schema-accounting':1,'--edit-tool':0,
                   '--edit-domains':None,'--progress-state':0,'--progress-domains':None,
                   '--evidence-policy':1}
    fixed={'--model':'qwen3.8-27b-noreason','--reasoning-budget':'0','--context-mode':'state',
           '--response-protocol':'unified','--input-estimator':'calibrated','--budget-policy':'reserve',
           '--observation-memory':'off','--orchestration':'off','--selection-policy':'fixed','--pacing':'off'}
    caps={'--task-budget','--max-steps','--max-output-tokens','--task-seconds'}
    if not isinstance(flags,list) or not all(isinstance(f,str) for f in flags):raise ValueError('Invalid profile flags')
    while index<len(flags):
        key=flags[index];index+=1
        if key in feature_sizes:
            size=feature_sizes[key];start=index
            if size is None:
                while index<len(flags) and not flags[index].startswith('--'):index+=1
                if index==start:raise ValueError('Missing domain list: '+key)
            else:index+=size
            if index>len(flags) or any(v.startswith('--') for v in flags[start:index]):raise ValueError('Missing value: '+key)
            result.extend([key,*flags[start:index]])
        elif key in fixed or key in caps:
            if index>=len(flags):raise ValueError('Missing value: '+key)
            value=flags[index];index+=1
            if key in fixed and value!=fixed[key]:raise ValueError('Profile requires a different comparison protocol: '+key)
        else:raise ValueError('Unsupported profile option; update benchmark explicitly: '+key)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite',choices=['all','successful'],default='all',
                        help='successful is the explicitly requested one-time replay; later quality runs use all')
    parser.add_argument('--catalog',type=Path,default=ROOT/'benchmarks/all-v1/catalog.json')
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--comparison',choices=['memory','solution'],default='memory')
    parser.add_argument('--profile',type=Path,default=ROOT/'configs/recommended.json')
    parser.add_argument('--resume',action='store_true',help='Reuse completed cohorts; never repeat their paid calls')
    parser.add_argument('--repetitions',type=int,default=2)
    parser.add_argument('--task-budget',type=int,default=2500)
    parser.add_argument('--budget-per-arm',type=int)
    parser.add_argument('--max-steps',type=int,default=24)
    parser.add_argument('--max-output-tokens',type=int,default=900)
    parser.add_argument('--task-seconds',type=int,default=180)
    args=parser.parse_args()
    if any(getattr(args,k)<=0 for k in ('repetitions','task_budget','max_steps','max_output_tokens','task_seconds')):
        parser.error('All limits and repetitions must be positive')
    if args.suite=='successful':
        reference=ROOT/'experiments/combined-v1/eval'
    else:
        if not args.catalog.is_file():
            parser.error('Build the all-task catalog with scripts/build_benchmark_suite.py first')
        try:catalog=validate_catalog(args.catalog)
        except (ValueError,OSError) as exc:parser.error(str(exc))
        reference=(args.catalog.parent/catalog['reference']).resolve()
        if len(list(reference.glob('*/task.json'))) != len(catalog['cases']):
            parser.error('Reference case count does not match frozen catalog')
    tasks=sorted(reference.glob('*/task.json'))
    if not tasks:parser.error('Empty suite')
    budget=args.budget_per_arm if args.budget_per_arm is not None else (5000 if args.suite=='successful' else args.task_budget*len(tasks))
    if budget<=0:parser.error('--budget-per-arm must be positive')
    if args.suite=='all' and budget<args.task_budget*len(tasks):
        parser.error('Full-suite budget must cover all per-task caps; reduce --task-budget uniformly instead of starving later cases')
    feature_flags=[];profile=None
    if args.comparison=='solution':
        try:
            profile=json.loads(args.profile.read_text());feature_flags=solution_features(profile)
        except (ValueError,OSError,KeyError,TypeError) as exc:parser.error(str(exc))
    out=args.out.resolve()
    if args.resume:
        if not (out/'manifest.json').is_file():parser.error('--resume requires an existing manifest')
    else:
        out.mkdir(parents=True,exist_ok=False)
    variants=('baseline','recommended') if args.comparison=='solution' else ('off','bounded')
    order=[{'name':f'r{rep}_{variant}','repetition':rep,'memory':variant if args.comparison=='memory' else 'off','variant':variant}
           for rep in range(1,args.repetitions+1)
           for variant in (variants if rep%2 else tuple(reversed(variants)))]
    sources=[*sorted((ROOT/'baseline').glob('*.py')),ROOT/'run_agent.py',ROOT/'scripts/experiment.py',Path(__file__).resolve()]
    manifest={'suite':args.suite,'comparison':args.comparison,'profile':profile,'feature_flags':feature_flags,'reference':str(reference),'tasks':[json.loads(p.read_text())['task_id'] for p in tasks],
              'cohort_order':order,'repetitions':args.repetitions,'model':'qwen3.8-27b-noreason',
              'budget_per_arm':budget,'task_budget':args.task_budget,'max_steps':args.max_steps,
              'max_output_tokens':args.max_output_tokens,'task_seconds':args.task_seconds,
              'max_total_cost':budget*len(order),'reasoning_budget':0,'observation_memory_chars':3000,
              'protocol':'unified','input_estimator':'calibrated','budget_policy':'reserve',
              'notes':'Same reference, caps and model for every arm. Comparison: '+args.comparison+'. Each cohort has a fresh estimator. Alternating order; provider-default sampling. Profile caps are replaced by the common benchmark caps.',
              'hashes_before_run':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
              'reference_hashes':{str(p.relative_to(reference)):hashlib.sha256(p.read_bytes()).hexdigest() for p in reference.rglob('*') if p.is_file() and '__pycache__' not in p.parts}}
    manifest['case_sources']=({c['task_id']:c['sources'] for c in catalog['cases']} if args.suite=='all'
                              else {json.loads(p.read_text())['task_id']:[str(p.parent.relative_to(ROOT))] for p in tasks})
    if args.resume:
        previous=json.loads((out/'manifest.json').read_text())
        for key in ('suite','reference','tasks','cohort_order','budget_per_arm','task_budget','max_steps','max_output_tokens','task_seconds','reference_hashes','comparison','profile','feature_flags'):
            if previous[key]!=manifest[key]:parser.error(f'Resume configuration differs: {key}')
        for path,digest in previous['hashes_before_run'].items():
            if path!='scripts/benchmark.py' and manifest['hashes_before_run'].get(path)!=digest:
                parser.error(f'Agent source changed since first cohort: {path}')
        previous.setdefault('runner_revisions',[]).append({'sha256':manifest['hashes_before_run']['scripts/benchmark.py'],
            'reason':'Resume completed cohorts without paid repetition; budget stops no longer abort independent cohorts. Agent, model, data and caps unchanged.'})
        manifest=previous
    (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
    guard_hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    profile_digest=hashlib.sha256(args.profile.read_bytes()).hexdigest() if profile else None
    print(json.dumps({'tasks':len(tasks),'cohorts':len(order),'max_cost':manifest['max_total_cost'],'suite':args.suite}),flush=True)
    cohorts=[]
    for cohort in order:
        file=out/cohort['name']/'results.json'
        command=[sys.executable,str(ROOT/'scripts/experiment.py'),'--reference',str(reference),'--out',str(out/cohort['name']),
                 '--models',manifest['model'],'--modes','state','--mode-budget',str(budget),'--task-budget',str(args.task_budget),
                 '--max-steps',str(args.max_steps),'--max-output-tokens',str(args.max_output_tokens),
                 '--task-seconds',str(args.task_seconds),'--reasoning-budget','0','--observation-memory',cohort['memory']]
        if args.comparison=='solution' and cohort['variant']=='recommended':command.extend(feature_flags)
        if args.resume and file.is_file():
            print('REUSE completed '+cohort['name']+'; no API calls',flush=True)
            returncode=0
        else:
            print('REAL API '+cohort['name'],flush=True)
            result=subprocess.run(command,cwd=ROOT,timeout=args.task_seconds*len(tasks)+120)
            returncode=result.returncode
        if not file.is_file():
            print('No results; stopping without additional API calls',flush=True);return returncode or 2
        rows=json.loads(file.read_text())
        if {r['task_id'] for r in rows} != set(manifest['tasks']):
            raise RuntimeError('Missing case rows: benchmark coverage is incomplete')
        cohorts.append({**cohort,'rows':rows})
        report=write_report(out,cohorts,manifest)
        print(json.dumps({'cohort':cohort['name'],**report['summary'][cohort['name']]}),flush=True)
        if returncode or any(r.get('status')=='error' or (r.get('status')=='stopped' and str(r.get('reason','')).startswith('proxy_')) for r in rows):
            print('Infrastructure error; report retains all task rows, further API calls stopped',flush=True);return 2
        if any(hashlib.sha256(p.read_bytes()).hexdigest()!=guard_hashes[str(p.relative_to(ROOT))] for p in sources):
            print('Agent source changed: stop further calls',flush=True);return 2
        if profile_digest and hashlib.sha256(args.profile.read_bytes()).hexdigest()!=profile_digest:
            print('Profile changed: stop further calls',flush=True);return 2
    print('REPORT '+str(out/'report.md'),flush=True)
    return 0


if __name__=='__main__':sys.exit(main())
