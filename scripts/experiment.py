"""Bounded, sequential, real-API experiment on isolated task copies."""
import itertools
import argparse, json, os, shutil, subprocess, sys, time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.evaluate import grade
from baseline.core import MODELS

ROOT=Path(__file__).resolve().parents[1]
def main():
    p=argparse.ArgumentParser();p.add_argument('--reference',type=Path,required=True);p.add_argument('--agent-root',type=Path,default=ROOT);p.add_argument('--packaged',action='store_true',help='Use the image recommended entrypoint without source mounts');p.add_argument('--output-format',choices=['text','json_object','json_schema'],default='text');p.add_argument('--schema-accounting',choices=['conservative','messages'],default='conservative');p.add_argument('--edit-tool',action='store_true');p.add_argument('--edit-domains',nargs='+',choices=['coding','data_analysis','math','search','generic']);p.add_argument('--progress-state',action='store_true');p.add_argument('--progress-domains',nargs='+',choices=['coding','data_analysis','math','search','generic']);p.add_argument('--evidence-policy',choices=['off','precise'],default='off');p.add_argument('--out',type=Path,required=True);p.add_argument('--image',default='huawei-baseline:tested');p.add_argument('--modes',nargs='+',choices=['history','state','hybrid'],default=['state']);p.add_argument('--mode-budget',type=int,default=4000);p.add_argument('--task-budget',type=int,default=1600);p.add_argument('--max-steps',type=int,default=8);p.add_argument('--max-output-tokens',type=int,default=600);p.add_argument('--task-seconds',type=int,default=100);p.add_argument('--response-protocol',choices=['legacy','unified'],default='unified');p.add_argument('--input-estimator',choices=['legacy','calibrated'],default='calibrated');p.add_argument('--budget-policy',choices=['off','reserve'],default='reserve');p.add_argument('--finish-output-tokens',type=int,default=256);p.add_argument('--finish-seconds',type=float,default=20);p.add_argument('--models',nargs='+',choices=MODELS,default=['qwen3.8-27b-noreason']);p.add_argument('--orchestration',choices=['off','boundary'],default='off');p.add_argument('--experience-file',type=Path);p.add_argument('--pacing',choices=['off','weighted','advisory'],default='off');p.add_argument('--loop-policy',choices=['off','finish'],default='off');p.add_argument('--reasoning-budget',type=float,default=0);p.add_argument('--tool-output-chars',type=int,default=12000);p.add_argument('--observation-memory',choices=['off','bounded'],default='off');p.add_argument('--observation-memory-chars',type=int,default=3000);a=p.parse_args()
    if a.tool_output_chars<=0:p.error('--tool-output-chars must be positive')
    if a.observation_memory_chars<1024:p.error('--observation-memory-chars must be >=1024')
    if a.observation_memory!='off' and (a.response_protocol!='unified' or 'history' in a.modes or a.orchestration!='off'):p.error('Bounded observation memory requires unified state/hybrid without routing')
    a.out=a.out.resolve();a.reference=a.reference.resolve();a.agent_root=a.agent_root.resolve();a.out.mkdir(parents=True,exist_ok=False)
    all_rows=[]
    for selected_model,mode in itertools.product(a.models,a.modes):
        label=mode if len(a.models)==1 else selected_model+'__'+mode
        dest=a.out/label/'tasks'
        subprocess.run([sys.executable,str(ROOT/'scripts/prepare_run.py'),'--source',str(a.reference),'--dest',str(dest)],check=True)
        command=['docker','run','--rm','--env-file',str(ROOT/'.env'),'-e','LLM_BASE_URL=https://api.neuraldeep.ru/v1',
            '--read-only','--tmpfs','/tmp:rw,size=2g','-e','HOME=/tmp','--cap-drop','ALL','--security-opt','no-new-privileges','--cpus','4','--memory','16g','--pids-limit','512']
        if not a.packaged:
            command.extend(['-v',f'{a.agent_root}/baseline:/app/baseline:ro','-v',f'{a.agent_root}/run_agent.py:/app/run_agent.py:ro','-v',f'{ROOT}/models:/app/models:ro'])
        command.extend(['-v',f'{dest}:/data/tasks:rw','--entrypoint','python',a.image,
            '/app/run_solution.py' if a.packaged else '/app/run_agent.py',
            '--tasks-dir','/data/tasks','--observation-memory',a.observation_memory,'--observation-memory-chars',str(a.observation_memory_chars),'--tool-output-chars',str(a.tool_output_chars),'--orchestration',a.orchestration,'--pacing',a.pacing,'--loop-policy',a.loop_policy,'--model',selected_model,'--reasoning-budget',str(a.reasoning_budget),'--context-mode',mode,'--response-protocol',a.response_protocol,'--input-estimator',a.input_estimator,'--budget-policy',a.budget_policy,'--finish-output-tokens',str(a.finish_output_tokens),'--finish-seconds',str(a.finish_seconds),'--budget',str(a.mode_budget),'--task-budget',str(a.task_budget),'--max-steps',str(a.max_steps),'--max-output-tokens',str(a.max_output_tokens),'--task-seconds',str(a.task_seconds),'--time-limit',str(a.task_seconds*len(list(a.reference.glob('*/task.json')))+30)])
        if a.output_format!='text':command.extend(['--output-format',a.output_format])
        if a.schema_accounting!='conservative':command.extend(['--schema-accounting',a.schema_accounting])
        if a.edit_tool:command.append('--edit-tool')
        if a.edit_domains:command.extend(['--edit-domains',*a.edit_domains])
        if a.progress_state:command.append('--progress-state')
        if a.progress_domains:command.extend(['--progress-domains',*a.progress_domains])
        if a.evidence_policy!='off':command.extend(['--evidence-policy',a.evidence_policy])
        if a.experience_file:
            # Artifact must live in models, mounted read-only; avoid mounting reference data.
            relative=a.experience_file.resolve().relative_to((ROOT/'models').resolve())
            command.extend(['--experience-file',str(Path('/app/models')/relative)])
        print(f'RUN {selected_model}/{mode}: total budget {a.mode_budget}',flush=True)
        with (a.out/label/'console.log').open('w') as log:
            result=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=a.task_seconds*len(list(a.reference.glob('*/task.json')))+90)
        summaries=list((dest/'.baseline').glob('*.json'))
        if not summaries: raise RuntimeError(f'{mode}: no summary; see console.log')
        summary=json.loads(summaries[0].read_text());records={r['task_id']:r for r in summary['tasks']}
        events=[json.loads(line) for f in (dest/'.baseline').glob('*.jsonl') for line in f.read_text().splitlines()]
        for ref in sorted(a.reference.glob('*/task.json')):
            meta=json.loads(ref.read_text());record=records.get(meta['task_id'],{})
            impossible=meta.get('impossible',False)
            passed,detail=(False,'impossible') if impossible else grade(ref.parent,dest/ref.parent.name,20)
            if passed and (ref.parent/'hidden_test.py').is_file():
                import tempfile
                from baseline.tools import run_command
                with tempfile.TemporaryDirectory() as directory:
                    work=Path(directory)
                    shutil.copytree(dest/ref.parent.name/'workspace',work,dirs_exist_ok=True)
                    shutil.copy2(ref.parent/'hidden_test.py',work/'hidden_test.py')
                    hidden=run_command('python3 hidden_test.py',work,20)
                    passed=hidden['returncode']==0 and not hidden['timeout']
                    detail={'hidden_test':hidden}
            responses=[e for e in events if e['event']=='response' and e.get('task_id')==meta['task_id']]
            row={'schema_accounting':a.schema_accounting,'output_format':a.output_format,'edit_tool':a.edit_tool,'edit_domains':a.edit_domains,'progress_state':a.progress_state,'progress_domains':a.progress_domains,'evidence_policy':a.evidence_policy,'observation_memory':a.observation_memory,'observation_memory_chars':a.observation_memory_chars,'tool_output_chars':a.tool_output_chars,'reasoning_budget':a.reasoning_budget,'settings':record.get('settings',summary.get('settings',{})),'orchestration':a.orchestration,'pacing':a.pacing,'experience_file':str(a.experience_file) if a.experience_file else None,'mode':mode,'model':record.get('model',selected_model),'selected_mode':record.get('context_mode',mode),'run_folder':label,'input_estimator':a.input_estimator,'budget_policy':a.budget_policy,'completion_phases':{phase:sum(e['event']=='completion_policy' and e.get('phase')==phase for e in events if e.get('task_id')==meta['task_id']) for phase in ['work','verify','submit']},'response_protocol':a.response_protocol,'response_errors':sum(e['event']=='response_error' for e in events if e.get('task_id')==meta['task_id']),'task_id':meta['task_id'],'type':meta['task_type'],'impossible':impossible,'passed':passed,'reward':meta['reward'],'score':meta['reward'] if passed else 0,'status':record.get('status','not_attempted'),'reason':record.get('reason'),'check_detail':detail,'correct_skip':impossible and record.get('status')=='skipped','cost':record.get('cost',0),'calls':len(responses),'uncertain_reservation_cost':sum(e.get('cost',0) for e in events if e.get('task_id')==meta['task_id'] and e['event']=='uncertain_request'),'input_tokens':sum(e['input_tokens'] for e in responses),'output_tokens':sum(e['output_tokens'] for e in responses),'seconds':record.get('seconds',0),'state_errors':sum(e['event']=='tool' and 'error' in e.get('result',{}) for e in events if e.get('task_id')==meta['task_id'])}
            for feature in ('output_format','schema_accounting','edit_tool','edit_domains','progress_state','progress_domains','evidence_policy'):
                if feature in row['settings']:row[feature]=row['settings'][feature]
            row['launch_source']='packaged_image' if a.packaged else str(a.agent_root)
            policies=[e for e in events if e.get('event')=='memory_policy' and e.get('task_id')==meta['task_id']]
            if policies:row['memory_policy']=policies[0]
            all_rows.append(row)
        (a.out/'results.json').write_text(json.dumps(all_rows,indent=2))
        print(json.dumps({'mode':mode,'spent':summary['spent'],'status':summary['status'],'score':sum(r['score'] for r in all_rows if r.get('run_folder')==label)}),flush=True)
        if result.returncode and any('proxy_' in r.get('reason','') for r in records.values()):
            print('Stopping experiment after proxy error; no further API calls',flush=True);break
    print(f'Results: {a.out}/results.json',flush=True)
if __name__=='__main__':main()
