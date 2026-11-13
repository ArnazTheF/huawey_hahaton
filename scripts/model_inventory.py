"""GET model catalog only; no generations, no credential output."""
import json,os,sys,urllib.request,urllib.error
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from baseline.core import MODELS
base=os.getenv('LLM_BASE_URL','').rstrip('/')
key=os.getenv('LLM_API_KEY','')
if not base or not key:
    print('Set LLM_BASE_URL and LLM_API_KEY',file=sys.stderr);sys.exit(2)
try:
    request=urllib.request.Request(base+'/models',headers={'Authorization':'Bearer '+key})
    with urllib.request.urlopen(request,timeout=15) as response: data=json.load(response)
    listed={item['id'] for item in data['data']}
    print(json.dumps({'models':{name:{'listed':name in listed,'generation_verified':False} for name in MODELS},'note':'Catalog visibility alone does not prove generation permission or quota.'},indent=2))
except urllib.error.HTTPError as exc:
    print(json.dumps({'error':'HTTP','status':exc.code}));sys.exit(2)
except Exception:
    print('Catalog check failed; details omitted to avoid exposing endpoint or credentials',file=sys.stderr);sys.exit(2)
