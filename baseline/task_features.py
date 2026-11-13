"""Zero-LLM task features and conservative screening. Never reads expected/check."""
import hashlib
import math
import re
from itertools import islice


def family_id(task):
    normalized = re.sub(r'\d+', '#', task.instruction.lower())
    return hashlib.sha256((task.task_type+'\n'+normalized).encode()).hexdigest()[:20]


def task_features(task):
    files = [p for p in islice(task.workspace.rglob('*'), 5000) if p.is_file() and not p.is_symlink()] if task.workspace.is_dir() else []
    sizes=[]
    for path in files:
        try: sizes.append(path.stat().st_size)
        except OSError: pass
    return {'task_type': task.task_type, 'instruction_chars': len(task.instruction),
            'file_count': len(files), 'workspace_bytes': sum(sizes),
            'test_files': sum(p.name.startswith('test') and p.suffix=='.py' for p in files)}


def screen_task(task):
    # A missing mention can be an output to create or a recoverable dependency.
    # Findings are risk indicators ONLY, never a proof of impossibility.
    mentions = sorted(set(re.findall(r'[\w./-]+\.(?:csv|json|txt|py|md|tsv)', task.instruction)))[:32]
    names = {p.name for p in islice(task.workspace.rglob('*'), 5000) if p.is_file()} if task.workspace.is_dir() else set()
    missing = [name for name in mentions if name.rsplit('/',1)[-1] not in names and name != 'answer.txt']
    return {'verdict': 'unknown', 'auto_reject': False,
            'findings': [{'kind': 'mentioned_file_absent', 'path': name, 'proof': False} for name in missing],
            'note': 'Missing mentions may be outputs or repairable; budget/step failure does not imply impossible.'}


def distance(a,b):
    penalty = 0 if a['task_type']==b['task_type'] else 100
    return penalty + sum(abs(math.log1p(a[k])-math.log1p(b[k])) for k in ('instruction_chars','file_count','workspace_bytes','test_files') if a.get(k) is not None and b.get(k) is not None)
