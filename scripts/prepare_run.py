#!/usr/bin/env python3
"""Create a fresh run directory without exposing sample answers to the solver."""
import argparse
import json
import shutil
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path('task-dir'))
    parser.add_argument('--dest', type=Path, required=True)
    args = parser.parse_args()
    source, destination = args.source.resolve(), args.dest.resolve()
    files = sorted(source.glob('*/task.json'))
    if not files:
        parser.error('Source contains no task.json files')
    if destination.exists():
        parser.error('Destination already exists; choose a fresh directory')
    if destination.is_relative_to(source) or source.is_relative_to(destination):
        parser.error('Source and destination must not contain one another')
    for file in files:
        workspace = file.parent/'workspace'
        if workspace.is_symlink() or (workspace.exists() and any(p.is_symlink() for p in workspace.rglob('*'))):
            parser.error(f'Symlink in {workspace}')
    destination.mkdir(parents=True)
    for file in files:
        raw = json.loads(file.read_text())
        target = destination/file.parent.name
        target.mkdir()
        public = {key: raw[key] for key in ('task_id', 'task_type', 'instruction', 'reward')}
        (target/'task.json').write_text(json.dumps(public, ensure_ascii=False, indent=2))
        workspace = file.parent/'workspace'
        if workspace.is_dir():
            shutil.copytree(workspace, target/'workspace',
                            ignore=shutil.ignore_patterns('answer.txt', '__pycache__', '.DS_Store'))
    print(f'Prepared {len(files)} tasks in {destination}; expected/check omitted')


if __name__ == '__main__':
    main()
