#!/usr/bin/env python3
"""Run the measured solution using the tested Docker dependencies and local sources."""
import argparse,subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--tasks-dir',type=Path,required=True)
    p.add_argument('--image',default='huawei-baseline:tested')
    p.add_argument('--env-file',type=Path,default=ROOT/'.env')
    p.add_argument('--base-url',default='https://api.neuraldeep.ru/v1')
    p.add_argument('--profile',choices=['recommended','baseline'],default='recommended')
    args,remaining=p.parse_known_args()
    tasks=args.tasks_dir.resolve()
    if not list(tasks.glob('*/task.json')):p.error('No task cases found; prepare a fresh run directory first')
    if not args.env_file.is_file():p.error('Env file missing; configure it locally without sharing the key')
    command=['docker','run','--rm','--env-file',str(args.env_file.resolve()),'-e','LLM_BASE_URL='+args.base_url,
             '--read-only','--tmpfs','/tmp:rw,size=2g','--cap-drop','ALL','--security-opt','no-new-privileges',
             '--cpus','4','--memory','16g','--pids-limit','512']
    for source,target in [('baseline','baseline'),('run_agent.py','run_agent.py'),('run_solution.py','run_solution.py'),('configs','configs'),('models','models')]:
        command.extend(['-v',f'{ROOT/source}:/app/{target}:ro'])
    command.extend(['-v',f'{tasks}:/data/tasks:rw','--entrypoint','python',args.image,'/app/run_solution.py',
                    '--profile',args.profile,'--tasks-dir','/data/tasks',*remaining])
    return subprocess.run(command).returncode


if __name__=='__main__':raise SystemExit(main())
