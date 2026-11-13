from __future__ import annotations

import json
import math
import os
import tempfile
import time
from dataclasses import dataclass, field
from .input_estimator import InputEstimator
from pathlib import Path

MODELS = ('qwen3.8-27b', 'qwen3.8-27b-noreason',
          'qwen3.6-35b-a3b', 'qwen3.6-35b-a3b-noreason')


class StopRun(RuntimeError):
    """Stop the entire run: budget, deadline, or unavailable proxy."""


@dataclass
class Task:
    directory: Path
    task_id: str
    task_type: str
    instruction: str
    reward: float

    @property
    def workspace(self):
        return self.directory / 'workspace'


def load_tasks(root: Path):
    tasks = []
    for file in sorted(root.glob('*/task.json')):
        raw = json.loads(file.read_text())
        # Deliberately do not retain expected/check in the solver data model.
        tasks.append(Task(file.parent, str(raw['task_id']), raw.get('task_type', 'generic'),
                          raw['instruction'], float(raw['reward'])))
    if not tasks:
        raise ValueError(f'No */task.json found in {root}')
    return tasks


def priority(task):
    # Initial heuristic only; replace with measured costs later.
    cost = {'math': 1, 'search': 2, 'data_analysis': 2, 'coding': 5}.get(task.task_type, 5)
    return (-task.reward / cost, task.task_id)


def atomic_write(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.baseline-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as out:
            out.write(content)
            out.flush()
            os.fsync(out.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


class Trace:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, event, **fields):
        with self.path.open('a') as out:
            out.write(json.dumps({'time': time.time(), 'event': event, **fields},
                                 ensure_ascii=False) + '\n')


@dataclass
class Budget:
    limit: float | None
    deadline: float
    spent: float = 0
    estimated: bool = False
    estimator: InputEstimator = field(default_factory=InputEstimator)

    def remaining_seconds(self):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise StopRun('wall_time_limit')
        return remaining

    def allowance(self, messages, requested, task_remaining, model="default"):
        self.remaining_seconds()
        input_estimate = self.estimator.estimate(messages, model)
        remaining = task_remaining
        if self.limit is not None:
            remaining = min(remaining, self.limit - self.spent)
        available = math.floor(remaining - input_estimate / 10)
        if available < 32:
            raise StopRun('insufficient_budget_for_request')
        return min(requested, available), input_estimate

    def charge(self, usage, input_estimate, output_limit, reasoning_mode):
        usage = usage or {}
        inp = usage.get('prompt_tokens', usage.get('input_tokens'))
        out = usage.get('completion_tokens', usage.get('output_tokens'))
        estimated = inp is None or out is None
        # Missing usage: reserve the entire requested completion allowance.
        inp = input_estimate if inp is None else inp
        out = output_limit if out is None else out
        details = usage.get('completion_tokens_details') or usage.get('output_tokens_details') or {}
        reasoning = details.get('reasoning_tokens', usage.get('reasoning_tokens', 0)) or 0
        if reasoning_mode == 'separate' and not estimated:
            out += reasoning
        cost = float(inp) / 10 + float(out)
        if not math.isfinite(cost) or cost < 0:
            raise StopRun('invalid_usage')
        self.spent += cost
        self.estimated |= estimated
        return {'cost': cost, 'input_tokens': inp, 'output_tokens': out,
                'reasoning_tokens': reasoning, 'estimated': estimated}
