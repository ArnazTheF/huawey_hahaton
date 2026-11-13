"""One paired Docker/API diagnostic, same known tasks; at most 6400 cost units."""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT/'runs/observation-memory-v1')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    reference = out/'reference'
    reference.mkdir()
    for name in ('snapshot_revenue', 'stable_toposort'):
        shutil.copytree(ROOT/'experiments/state-broad-v1'/name, reference/name)
    sources = [*sorted((ROOT/'baseline').glob('*.py')), ROOT/'run_agent.py',
               ROOT/'scripts/experiment.py', Path(__file__).resolve()]
    manifest = {
        'model': 'qwen3.8-27b-noreason', 'mode': 'state', 'reasoning_budget': 0,
        'arms': ['off', 'bounded'], 'budget_per_arm': 3200, 'task_budget': 1600,
        'max_total_cost': 6400, 'observation_memory_chars': 3000,
        'max_steps': 16, 'max_output_tokens': 900, 'tool_output_chars': 12000,
        'task_seconds': 150, 'reference': str(reference),
        'notes': 'One repetition on known diagnostic/regression cases; not held-out validation. Fixed off-then-bounded order, provider sampling uncontrolled. Each arm starts with a fresh estimator and task copies. References are never mounted in the agent.',
        'hashes_before_run': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
    }
    (out/'manifest.json').write_text(json.dumps(manifest, indent=2))
    for arm in manifest['arms']:
        print('REAL API: observation memory '+arm, flush=True)
        command = [sys.executable, str(ROOT/'scripts/experiment.py'),
                   '--reference', str(reference), '--out', str(out/arm),
                   '--modes', 'state', '--models', manifest['model'],
                   '--mode-budget', '3200', '--task-budget', '1600',
                   '--max-steps', '16', '--max-output-tokens', '900',
                   '--tool-output-chars', '12000', '--task-seconds', '150',
                   '--reasoning-budget', '0', '--observation-memory', arm]
        result = subprocess.run(command, cwd=ROOT, timeout=420)
        if result.returncode:
            return result.returncode
        rows = json.loads((out/arm/'results.json').read_text())
        if any(str(row.get('reason', '')).startswith(('proxy_', 'http_', 'network_')) or row['status']=='error' for row in rows):
            print('Infrastructure error: stop further calls', flush=True)
            return 2
        if any(hashlib.sha256(p.read_bytes()).hexdigest() != manifest['hashes_before_run'][str(p.relative_to(ROOT))] for p in sources):
            print('Source changed: stop further calls', flush=True)
            return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
