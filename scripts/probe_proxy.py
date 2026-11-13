#!/usr/bin/env python3
"""Make ONE billed request to verify the configured proxy contract."""
import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from baseline.client import Client
from baseline.core import Budget, MODELS, StopRun, Trace


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', choices=MODELS, default='qwen3.8-27b-noreason')
    parser.add_argument('--log', type=Path, default=Path('runs/proxy-probe.jsonl'))
    parser.add_argument('--max-tokens-field', choices=('max_tokens', 'max_completion_tokens'), default='max_tokens')
    parser.add_argument('--reasoning-usage', choices=('included', 'separate'), default='included')
    args = parser.parse_args()
    base, key = os.getenv('LLM_BASE_URL'), os.getenv('LLM_API_KEY')
    if not base or not key:
        parser.error('Export LLM_BASE_URL and LLM_API_KEY first')
    budget = Budget(500, time.monotonic()+30)
    client = Client(base, key, args.model, budget, Trace(args.log), timeout=25,
                    reasoning_mode=args.reasoning_usage, max_tokens_field=args.max_tokens_field)
    try:
        content = client.complete([{'role': 'user', 'content': 'Reply with only the word OK.'}],
                                  'proxy-probe', 64, 500)
    except StopRun as exc:
        print(f'Probe failed: {exc}', file=sys.stderr)
        return 2
    print(json.dumps({'content': content, 'cost': budget.spent,
                      'usage_estimated': budget.estimated, 'log': str(args.log)}, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
