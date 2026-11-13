"""All-case staged evaluation report, including failed and impossible cases."""
import argparse,collections,hashlib,json
from pathlib import Path


def metrics(rows,folder):
    events=[json.loads(line) for f in (folder/'state/tasks/.baseline').glob('*.jsonl') for line in f.read_text().splitlines()]
    last={};rejected_cost=0;errors=0;writes=collections.Counter();reads=collections.Counter();last_action={}
    for event in events:
        task=event.get('task_id');kind=event.get('event')
        if kind=='response':
            last[task]=event
            try:last_action[task]=json.loads(event['content']).get('action',{})
            except (ValueError,AttributeError):last_action[task]={}
        elif kind=='response_error':
            errors+=1;rejected_cost+=last.get(task,{}).get('cost',0)
        elif kind=='tool':
            result=event.get('result',{})
            if 'written'in result or 'edited'in result:writes[task]+=1
            action=last_action.get(task,{})
            if action.get('action')=='read' and 'content'in result:
                key=(task,action.get('path'),hashlib.sha256(result['content'].encode()).hexdigest(),bool(result.get('truncated')))
                reads[key]+=1
    eligible=all(r['status']!='not_attempted' and r['status']!='error' and not str(r.get('reason','')).startswith(('proxy_','unsupported_proxy_response_schema')) for r in rows)
    return {'eligible_for_comparison':eligible,'passed':sum(r['passed'] for r in rows),'solvable':sum(not r['impossible'] for r in rows),
            'score':sum(r['score'] for r in rows),'solvable_max_score':sum(r['reward'] for r in rows if not r['impossible']),
            'cost':round(sum(r['cost'] for r in rows),1),'calls':sum(r['calls'] for r in rows),
            'rejected_responses':errors,'rejected_response_cost':round(rejected_cost,1),
            'length_responses':sum(e.get('event')=='response' and e.get('finish_reason')=='length' for e in events),
            'repeat_identical_read_fragments':sum(max(0,n-1) for n in reads.values()),
            'writes':dict(writes),'correct_skips':sum(r['correct_skip'] for r in rows),
            'impossible_controls':sum(r['impossible'] for r in rows),
            'not_attempted':sum(r['status']=='not_attempted' for r in rows),
            'reported_usage_cost':round(sum(e.get('cost',0) for e in events if e['event']=='response' and not e.get('estimated')),1),
            'estimated_usage_cost':round(sum(e.get('cost',0) for e in events if e['event']=='response' and e.get('estimated')),1),
            'uncertain_reservation_cost':round(sum(e.get('cost',0) for e in events if e['event']=='uncertain_request'),1),
            'http_rejections_without_usage':sum(e['event']=='http_error' for e in events)}


def build(out,catalog_path):
    manifest=json.loads((out/'manifest.json').read_text());catalog=json.loads(catalog_path.read_text())
    expected={c['task_id'] for c in catalog['cases']};completed={};summaries={}
    for arm in manifest['arms']:
        path=out/arm['name']/'results.json'
        if not path.is_file():continue
        rows=json.loads(path.read_text())
        if len(rows)!=len(expected) or {r['task_id'] for r in rows}!=expected:
            raise ValueError('Incomplete case accounting: '+arm['name'])
        completed[arm['name']]={r['task_id']:r for r in rows}
        summaries[arm['name']]=metrics(rows,path.parent)
    result={'suite':'all','catalog':str(catalog_path),'case_count':len(expected),
            'planned_arms':manifest['arms'],'completed_arms':list(completed),'summary':summaries,
            'accounted_cost':round(sum(s['cost'] for s in summaries.values()),1),
            'actual_cost':round(sum(s['reported_usage_cost'] for s in summaries.values()),1),
            'uncertain_reservations':round(sum(s['uncertain_reservation_cost']+s['estimated_usage_cost'] for s in summaries.values()),1),
            'tasks':[{'task_id':c['task_id'],'original_id':c['original_task_id'],'type':c['type'],'sources':c['sources'],
                      'impossible':c['impossible'],'results':{name:rows[c['task_id']] for name,rows in completed.items()}} for c in catalog['cases']]}
    (out/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    lines=['# State-v2: все задачи','',
           'Каждая завершённая серия содержит все 29 вариантов. Знаменатель решённых исключает три заведомо невыполнимых контроля; расход включает их.',
           'Один запуск каждой промежуточной версии — исследовательская оценка, не статистическое доказательство. Расход прерванных серий может включать консервативный резерв без подтверждённого usage; он выделен в JSON.',
           '', '| Версия | Выполнимых решено | Баллы | Расход | Вызовы | Отклонено ответов | Обрезано ответов |',
           '|---|---:|---:|---:|---:|---:|---:|']
    for name,s in summaries.items():
        label=name if s['eligible_for_comparison'] else name+' (неполный: инфраструктура)'
        quality=f"{s['passed']}/{s['solvable']}" if s['eligible_for_comparison'] else 'не оценено'
        points=f"{s['score']}/{s['solvable_max_score']}" if s['eligible_for_comparison'] else 'не оценено'
        lines.append(f"| {label} | {quality} | {points} | {s['cost']:.1f} | {s['calls']} | {s['rejected_responses']} | {s['length_responses']} |")
    names=list(completed)
    lines+=['','В ячейках: решено; неверный ответ; пропуск с причиной; не начато; либо отдельный статус невыполнимого контроля.','',
            '| Задача / вариант | Тип | '+' | '.join(names)+' |', '|---|---|'+'---|'*len(names)]
    for case in catalog['cases']:
        cells=[]
        for name in names:
            row=completed[name][case['task_id']]
            if case['impossible']:label='контроль: '+('skip' if row['correct_skip'] else row['status'])
            elif row['passed']:label='решено'
            elif row['status']=='submitted':label='неверный ответ'
            else:label=row['status']+': '+str(row.get('reason') or row.get('check_detail'))[:120]
            cells.append(label.replace('|','/').replace('\n',' '))
        lines.append('| '+case['task_id']+' | '+case['type']+' | '+' | '.join(cells)+' |')
    lines+=['','Полные настройки, источники, стоимость и внешняя проверка каждой попытки находятся в results.json.',
            'repeat_identical_read_fragments считает повтор одинакового фрагмента direct-read; это не доказательство бесполезности чтения и не учёт чтений внутри Bash.']
    if len(completed)!=len(manifest['arms']):lines+=['','Остальные запланированные серии ещё не завершены; их успех не предполагается.']
    (out/'report.md').write_text('\n'.join(lines)+'\n')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,default=Path('runs/state-v2'));p.add_argument('--catalog',type=Path,default=Path('benchmarks/all-v1/catalog.json'));args=p.parse_args()
    report=build(args.out,args.catalog);print(json.dumps({'completed':report['completed_arms'],'summary':report['summary'],'actual_cost':report['actual_cost']},ensure_ascii=False))
