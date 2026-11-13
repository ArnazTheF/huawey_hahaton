"""Small-data empirical baseline: family-balanced neighbors, success/cost separately.
Not TokenCast, not a calibrated universal probability model. Unknown pairs abstain.
"""
import json
import math
from collections import defaultdict
from pathlib import Path
from .core import MODELS
from .task_features import distance

SETTINGS = ('response_protocol','input_estimator','budget_policy','max_steps','max_output_tokens','task_budget','finish_output_tokens','finish_seconds','observation_memory','observation_memory_chars','output_format','schema_accounting','edit_tool','edit_domains','progress_state','progress_domains','evidence_policy')


def normalize_settings(config):
    result = dict(config)
    result['observation_memory'] = result.get('observation_memory') or 'off'
    result['output_format']=result.get('output_format') or 'text'
    result['schema_accounting']=(result.get('schema_accounting') or 'conservative') if result['output_format']!='text' else None
    result['edit_tool']=bool(result.get('edit_tool'))
    edit_domains=result.get('edit_domains')
    result['edit_domains']=sorted(edit_domains) if result['edit_tool'] and edit_domains is not None else None
    result['progress_state']=bool(result.get('progress_state'))
    domains=result.get('progress_domains')
    result['progress_domains']=sorted(domains) if result['progress_state'] and domains is not None else None
    result['evidence_policy']=result.get('evidence_policy') or 'off'
    if result['observation_memory'] == 'off':
        result['observation_memory_chars'] = None
    return result


def settings(config):
    result={k:getattr(config,k,None) for k in SETTINGS}
    if result['budget_policy']=='off':
        result['finish_output_tokens']=None;result['finish_seconds']=None
    return normalize_settings(result)


def quantile(values,q):
    values=sorted(values)
    return values[min(len(values)-1,math.ceil(q*(len(values)-1)))] if values else None


class Portfolio:
    def __init__(self, artifact, min_groups=3):
        if artifact.get('schema') != 1 or artifact.get('kind') != 'empirical-family-baseline':
            raise ValueError('Unsupported portfolio artifact')
        self.rows=artifact['rows'];self.min_groups=max(3,min_groups)
        for row in self.rows:
            if row['model'] not in MODELS or row['mode'] not in ('history','state','hybrid'):
                raise ValueError('Artifact contains an unsupported model or mode')
            if not math.isfinite(row['cost']) or row['cost'] < 0:
                raise ValueError('Invalid artifact cost')

    @classmethod
    def load(cls,path):
        return cls(json.loads(Path(path).read_text()))

    def candidates(self, features, config, models, modes, exclude_family=None):
        predictions=[]
        for model in models:
            for mode in modes:
                rows=[r for r in self.rows if r['model']==model and r['mode']==mode
                      and normalize_settings(r['settings'])==normalize_settings(config) and r['features']['task_type']==features['task_type']
                      and r['family']!=exclude_family and distance(features,r['features'])<=4.0]
                groups=defaultdict(list)
                for row in rows: groups[row['family']].append(row)
                # Repeated seeds/runs of one family must not masquerade as independent evidence.
                chosen=sorted(groups.values(),key=lambda rs:min(distance(features,r['features']) for r in rs))[:8]
                n=len(chosen)
                group_success=[sum(r['success'] for r in rs)/len(rs) for rs in chosen]
                p=(sum(group_success)+1)/(n+2) if n else None
                costs=[sum(r['cost'] for r in rs)/len(rs) for rs in chosen]  # spend until termination, including failures
                successful_costs=[sum(r['cost'] for r in rs if r['success'])/sum(r['success'] for r in rs) for rs in chosen if any(r['success'] for r in rs)]
                predictions.append({'model':model,'mode':mode,'groups':n,
                    'supported':n>=self.min_groups and bool(successful_costs),
                    'success_probability_estimate':p,'expected_attempt_cost':sum(costs)/n if n else None,
                    'successful_cost_median':quantile(successful_costs,.5),
                    'successful_cost_p90':quantile(successful_costs,.9),
                    'calibrated':False})
        return predictions

    def recommend(self, features, config, models, modes, remaining, reward=1, exclude_family=None):
        candidates=self.candidates(features,config,models,modes,exclude_family)
        eligible=[p for p in candidates if p['supported'] and p['successful_cost_p90']<=remaining]
        for p in eligible:
            p['utility']=reward*p['success_probability_estimate']/max(1,p['expected_attempt_cost'])
        best=max(eligible,key=lambda p:p['utility']) if eligible else None
        return {'recommendation':best,'candidates':candidates,'fallback':best is None,
                'reason':'empirical_utility' if best else 'insufficient_matching_evidence_or_budget'}

    def remaining_forecast(self, features, config, model, mode, calls, spent):
        rows=[r for r in self.rows if r['model']==model and r['mode']==mode
              and normalize_settings(r['settings'])==normalize_settings(config) and r['success'] and r.get('prefixes')
              and r['features']['task_type']==features['task_type'] and distance(features,r['features'])<=4.0]
        groups=defaultdict(list)
        for r in rows: groups[r['family']].append(r)
        if len(groups)<self.min_groups:
            return {'supported':False,'reason':'insufficient_successful_families','auto_stop':False}
        selected=sorted(groups.values(),key=lambda rs:min(distance(features,r['features']) for r in rs))[:8]
        values=[]
        for rs in selected:
            # Prefix selection uses only observable calls/spend, never future success flags at runtime.
            r=min(rs,key=lambda r:distance(features,r['features']))
            prefix=min(r['prefixes'],key=lambda p:abs(p['calls']-calls)+abs(math.log1p(p['spent'])-math.log1p(spent)))
            values.append(max(0,r['cost']-prefix['spent']))
        return {'supported':True,'groups':len(values),'remaining_p50':quantile(values,.5),
                'remaining_p90':quantile(values,.9),'calibrated':False,'auto_stop':False}
