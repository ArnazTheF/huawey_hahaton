#!/usr/bin/env python3
"""Run the measured recommended profile; user-supplied flags take precedence."""
import argparse,asyncio,json,sys
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(add_help=False)
    parser.add_argument('--profile',choices=['recommended','baseline'],default='recommended')
    known,remaining=parser.parse_known_args()
    root=Path(__file__).resolve().parent
    if known.profile=='baseline':flags=[]
    else:
        path=root/'configs/recommended.json'
        if not path.is_file():raise ValueError('Recommended profile has not been selected by evaluation yet')
        profile=json.loads(path.read_text())
        flags=profile['flags']
        if not isinstance(flags,list) or not all(isinstance(v,str) for v in flags):raise ValueError('Invalid profile flags')
    import run_agent
    sys.argv=[str(root/'run_agent.py'),*flags,*remaining]
    return asyncio.run(run_agent.main(run_agent.arguments()))


if __name__=='__main__':
    try:sys.exit(main())
    except (ValueError,RuntimeError) as exc:
        print(f'Error: {exc}',file=sys.stderr);sys.exit(2)
