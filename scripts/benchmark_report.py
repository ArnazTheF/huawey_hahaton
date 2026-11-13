"""Per-case benchmark accounting; failures and unattempted cases stay visible."""
import json
from pathlib import Path


def outcome(row):
    if row.get('passed'):
        return 'SOLVED'
    if row.get('correct_skip'):
        return 'IMPOSSIBLE_SKIP'
    status = row.get('status', 'not_attempted')
    return {'submitted':'WRONG_ANSWER', 'skipped':'SKIPPED', 'stopped':'STOPPED',
            'error':'ERROR', 'not_attempted':'NOT_ATTEMPTED'}.get(status, status.upper())


def summarize(rows):
    names = sorted({row['task_id'] for row in rows})
    return {'attempts':len(rows), 'unique_tasks':len(names),
            'solved':sum(bool(row.get('passed')) for row in rows),
            'score':sum(row.get('score',0) for row in rows),
            'max_score':sum(row.get('reward',0) for row in rows),
            'cost':round(sum(row.get('cost',0) for row in rows),1),
            'not_attempted':sum(row.get('status')=='not_attempted' for row in rows),
            'solved_tasks':sorted({row['task_id'] for row in rows if row.get('passed')}),
            'unsolved_tasks':sorted({row['task_id'] for row in rows if not row.get('passed')})}


def write_report(out, cohorts, manifest):
    out = Path(out)
    all_rows = []
    for cohort in cohorts:
        for row in cohort['rows']:
            all_rows.append({**row, 'cohort':cohort['name'], 'repetition':cohort['repetition'],
                             'memory':cohort['memory'], 'variant':cohort.get('variant',cohort['memory']), 'outcome':outcome(row),
                             'sources':manifest.get('case_sources',{}).get(row['task_id'],[])})
    summary = {cohort['name']:summarize(cohort['rows']) for cohort in cohorts}
    report = {'suite':manifest['suite'], 'planned_cohorts':manifest['cohort_order'],
              'completed_cohorts':[c['name'] for c in cohorts], 'summary':summary,
              'total_cost':round(sum(v['cost'] for v in summary.values()),1), 'tasks':all_rows}
    report['by_memory']={memory:summarize([row for row in all_rows if row['memory']==memory])
                         for memory in sorted({row['memory'] for row in all_rows})}
    report['by_variant']={variant:summarize([row for row in all_rows if row['variant']==variant])
                         for variant in sorted({row['variant'] for row in all_rows})}
    (out/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    text = ['# Поимённый отчёт сравнительного прогона', '',
            f"Набор: {manifest['suite']}. Модель: {manifest['model']}. Reasoning: 0.",
            f"Бюджет серии: {manifest['budget_per_arm']}; задачи: {manifest['task_budget']}; шагов: {manifest['max_steps']}.",
            '', '| Серия | Решено / задач | Баллы | Расход | Не начато |',
            '|---|---:|---:|---:|---:|']
    for name, row in summary.items():
        text.append(f"| {name} | {row['solved']}/{row['attempts']} | {row['score']}/{row['max_score']} | {row['cost']:.1f} | {row['not_attempted']} |")
    text += ['', 'Баллы и число задач учитываются раздельно. Невыполнимый skip не считается решённой задачей.',
             'Каждая строка ниже — конкретная задача в конкретном повторе; не начатые задачи остаются в таблице.',
             '', '| Задача | Серия | Итог | Фактический лимит задачи | Причина / проверка | Расход |', '|---|---|---|---:|---|---:|']
    for row in all_rows:
        reason = row.get('reason') or row.get('check_detail') or ''
        if not isinstance(reason,str):
            reason = 'external tests passed' if row.get('passed') else json.dumps(reason,ensure_ascii=False)
        reason = reason.replace('|','/').replace('\n',' ')[:240]
        cap=row.get('settings',{}).get('task_budget')
        cap_text=f'{cap:.1f}' if isinstance(cap,(int,float)) else '—'
        text.append(f"| {row['task_id']} | {row['cohort']} | {row['outcome']} | {cap_text} | {reason} | {row.get('cost',0):.1f} |")
    if len(cohorts) != len(manifest['cohort_order']):
        text += ['', 'Прогон ещё не завершён либо остановлен; отсутствующие серии не считаются выполненными.']
    text += ['', 'JSON содержит настройки, внешний результат проверки, статусы и расход каждой попытки.',
             'Повторы используют семплирование провайдера по умолчанию; два повтора не устанавливают статистическую значимость.']
    (out/'report.md').write_text('\n'.join(text)+'\n')
    return report
