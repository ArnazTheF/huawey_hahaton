#!/usr/bin/env python3
"""Local sample grader. Only this script reads reference answers."""
import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from baseline.tools import run_command


def grade(reference, actual, timeout):
    raw = json.loads((reference/'task.json').read_text())
    answer_file = actual/'answer.txt'
    if not answer_file.is_file():
        return False, 'missing_answer'
    answer = answer_file.read_text().strip()
    check = raw.get('check')
    if check == 'exact_int':
        try:
            return int(answer) == int(raw['expected']), 'exact_int'
        except ValueError:
            return False, 'not_an_integer'
    if check == 'exact_str':
        return answer == str(raw['expected']).strip(), 'exact_str'
    if check == 'unittest':
        if answer != 'DONE':
            return False, 'expected_DONE'
        work = actual/'workspace'
        if not work.is_dir():
            return False, 'missing_workspace'
        original_tests = list((reference/'workspace').rglob('test*.py'))
        if not original_tests:
            return False, 'missing_reference_tests'
        for test in original_tests:
            candidate = work/test.relative_to(reference/'workspace')
            if not candidate.is_file() or candidate.read_bytes() != test.read_bytes():
                return False, 'modified_tests'
        with tempfile.TemporaryDirectory(prefix='baseline-grade-') as directory:
            root = Path(directory)
            shutil.copytree(work, root, dirs_exist_ok=True)
            # Use original tests even when validating an already checked run.
            for test in original_tests:
                shutil.copy2(test, root/test.relative_to(reference/'workspace'))
            result = run_command('python3 test_mylib.py', root, timeout)
        return result['returncode'] == 0 and not result['timeout'], result
    return False, f'unsupported_check:{check}'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, default=Path('task-dir'))
    parser.add_argument('--tasks-dir', type=Path, required=True)
    parser.add_argument('--timeout', type=float, default=20)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    references = sorted(args.reference.glob('*/task.json'))
    if not references:
        parser.error('No reference tasks found')
    rows = []
    for file in references:
        raw = json.loads(file.read_text())
        try:
            passed, detail = grade(file.parent, args.tasks_dir/file.parent.name, args.timeout)
        except (OSError, ValueError) as exc:
            passed, detail = False, str(exc)
        rows.append({'task_id': raw['task_id'], 'passed': passed,
                     'reward': raw['reward'], 'detail': detail})
    report = {'score': sum(r['reward'] for r in rows if r['passed']),
              'max_score': sum(r['reward'] for r in rows),
              'passed': sum(r['passed'] for r in rows), 'total': len(rows), 'tasks': rows}
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + '\n')
    return 0 if report['passed'] == report['total'] else 1


if __name__ == '__main__':
    sys.exit(main())
