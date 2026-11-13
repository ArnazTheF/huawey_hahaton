"""Freeze all reference cases; deduplicate exact copies, retain every source alias."""
import argparse
import hashlib
import json
import shutil
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
IGNORED={'__pycache__','.DS_Store'}


def case_files(case):
    result=[]
    for path in sorted(case.rglob('*')):
        if any(part in IGNORED for part in path.relative_to(case).parts):
            continue
        if path.is_symlink():
            raise ValueError(f'Symlink in reference case: {path}')
        if path.is_file() and path!=case/'task.json':
            result.append(path)
    return result


def signature(case, meta):
    # Include grader labels/tests too: different grading is not an exact duplicate.
    normalized={key:value for key,value in meta.items() if key!='task_id'}
    digest=hashlib.sha256(json.dumps(normalized,sort_keys=True,ensure_ascii=False).encode())
    for path in case_files(case):
        name=path.relative_to(case).as_posix().encode()
        data=path.read_bytes()
        digest.update(len(name).to_bytes(8,'big')+name+len(data).to_bytes(8,'big')+data)
    return digest.hexdigest()


def display(path):
    try:return str(path.resolve().relative_to(ROOT))
    except ValueError:return str(path.resolve())


def discover(sources):
    groups={}
    for source in sources:
        if not source.is_dir():raise ValueError(f'Reference source is missing: {source}')
        for file in sorted(source.rglob('task.json')):
            if 'workspace' in file.relative_to(source).parts[:-1]:
                continue
            meta=json.loads(file.read_text())
            if not isinstance(meta,dict) or not {'task_id','task_type','instruction','reward'} <= meta.keys():
                continue
            key=signature(file.parent,meta)
            group=groups.setdefault(key,{'source':file.parent,'meta':meta,'aliases':[]})
            alias=display(file.parent)
            if alias not in group['aliases']:group['aliases'].append(alias)
    if not groups:raise ValueError('No reference cases found')
    return groups


def validate_catalog(path):
    catalog=json.loads(path.read_text())
    sources=[Path(p) if Path(p).is_absolute() else ROOT/p for p in catalog['source_roots']]
    groups=discover(sources)
    registered={case['signature']:case for case in catalog['cases']}
    if set(groups)!=set(registered):
        raise ValueError('Case corpus changed: rebuild the full catalog before quality evaluation')
    for key,group in groups.items():
        if set(group['aliases'])!=set(registered[key]['sources']):
            raise ValueError('Source aliases changed: rebuild the full catalog')
    reference=(path.parent/catalog['reference']).resolve()
    actual={str(p.relative_to(reference)):hashlib.sha256(p.read_bytes()).hexdigest() for p in reference.rglob('*')
            if p.is_file() and not any(part in IGNORED for part in p.relative_to(reference).parts)}
    if actual!=catalog['reference_hashes'] or any(p.is_symlink() for p in reference.rglob('*')):
        raise ValueError('Frozen reference files changed: rebuild the catalog')
    return catalog


def build(sources, out):
    groups=discover(sources)
    out.mkdir(parents=True,exist_ok=False)
    reference=out/'reference';reference.mkdir()
    cases=[]
    for key,group in sorted(groups.items(),key=lambda pair:(pair[1]['meta']['task_id'],pair[0])):
        raw=group['meta']
        # Original names stay visible; hash distinguishes data variants of one ID.
        case_id=raw['task_id']+'__'+key[:12]
        if '/' in case_id or '\\' in case_id:raise ValueError('Invalid task ID')
        dest=reference/case_id;dest.mkdir()
        for source in case_files(group['source']):
            target=dest/source.relative_to(group['source']);target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(source,target)
        (dest/'task.json').write_text(json.dumps({**raw,'task_id':case_id},ensure_ascii=False,indent=2))
        cases.append({'task_id':case_id,'original_task_id':raw['task_id'],'signature':key,
                      'type':raw['task_type'],'reward':raw['reward'],
                      'impossible':bool(raw.get('impossible',False)),'sources':group['aliases']})
    catalog={'schema':1,'reference':'reference','source_roots':[display(p) for p in sources],
             'source_cases':sum(len(g['aliases']) for g in groups.values()),'unique_cases':len(cases),
             'deduplication':'Exact metadata except task_id + all resource/grader file bytes; all aliases retained.',
             'cases':cases,
             'reference_hashes':{str(p.relative_to(reference)):hashlib.sha256(p.read_bytes()).hexdigest() for p in reference.rglob('*') if p.is_file()}}
    (out/'catalog.json').write_text(json.dumps(catalog,ensure_ascii=False,indent=2))
    lines=['# Полный реестр задач','',f"Уникальных вариантов: {len(cases)}; исходных папок: {catalog['source_cases']}.",
           'Точные копии объединены; разные данные, инструкции или проверки остаются отдельными задачами.',
           '', '| ID варианта | Тип | Источники |', '|---|---|---|']
    for case in cases:
        lines.append(f"| {case['task_id']} | {case['type']} | {'; '.join(case['sources'])} |")
    (out/'catalog.md').write_text('\n'.join(lines)+'\n')
    return catalog


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources',nargs='+',type=Path,default=[ROOT/'task-dir',ROOT/'experiments'])
    parser.add_argument('--out',type=Path,default=ROOT/'benchmarks/all-v1')
    args=parser.parse_args()
    catalog=build([p.resolve() for p in args.sources],args.out.resolve())
    print(json.dumps({'unique_cases':catalog['unique_cases'],'source_cases':catalog['source_cases'],
                      'catalog':str(args.out/'catalog.json')}))


if __name__=='__main__':main()
