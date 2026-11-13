"""Two live test cohorts; 5000 cost units each, reference never mounted."""
import hashlib,json,subprocess,sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]
base=[sys.executable,str(root/'scripts/experiment.py'),'--reference','experiments/combined-v1/eval','--modes','state','--mode-budget','5000','--task-budget','2500','--max-steps','24','--max-output-tokens','900','--task-seconds','180']
manifest={'reference':'experiments/combined-v1/eval','seed':20261114,'max_new_cost':20000,
          'cohorts':['baseline','combined'],'cohort_budget':5000,'task_budget':2500,
          'notes':'Single repetition, same families with changed data; not broad generalization. Router/experience/pacing changed jointly; attribution requires ablations.',
          'hashes':{str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [*root.glob('baseline/*.py'),root/'run_agent.py',root/'models/experience-combined-v1.json']}}
(root/'runs/combined-v1/manifest.json').write_text(json.dumps(manifest,indent=2))
for label,extra in [('baseline',[]),('combined',['--orchestration','boundary','--experience-file','models/experience-combined-v1.json','--pacing','weighted','--loop-policy','finish'])]:
    print('REAL API COHORT '+label,flush=True)
    p=subprocess.run(base+['--out','runs/combined-v1/'+label]+extra,cwd=root,timeout=700)
    if p.returncode:sys.exit(p.returncode)
    output=root/'runs/combined-v1'/label/'results.json'
    rows=json.loads(output.read_text())
    if any(r['status']=='stopped' and str(r.get('reason','')).startswith('proxy_') for r in rows):
        print('Proxy error; stopping further generations',flush=True);sys.exit(2)
