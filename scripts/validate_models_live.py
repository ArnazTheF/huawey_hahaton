"""Four real short probes, no credential output; max 500 cost units per model."""
import json, subprocess
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from baseline.core import MODELS
root=Path(__file__).resolve().parents[1]
out=root/'runs'/'combined-v1'/'probes';out.mkdir(parents=True,exist_ok=False)
rows=[]
for model in MODELS:
    print('REAL API PROBE '+model,flush=True)
    cmd=['docker','run','--rm','--env-file',str(root/'.env'),'-e','LLM_BASE_URL=https://api.neuraldeep.ru/v1','--read-only','--tmpfs','/tmp:rw,size=2g','-e','HOME=/tmp',
         '-v',f'{root}/baseline:/app/baseline:ro','-v',f'{out}:/data:rw','--entrypoint','python','huawei-baseline:tested','/app/scripts/probe_proxy.py','--model',model,'--log',f'/data/{model}.jsonl']
    p=subprocess.run(cmd,capture_output=True,text=True,timeout=45)
    # Our probe emits only a fixed OK response/usage or a sanitized error.
    print(p.stdout or p.stderr,flush=True)
    rows.append({'model':model,'exit_code':p.returncode,'output':p.stdout,'error':p.stderr})
(out/'results.json').write_text(json.dumps(rows,indent=2))
