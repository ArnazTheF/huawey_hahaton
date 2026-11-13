"""Domain-authored, bounded progress state; no task IDs or reference labels."""
import copy
import json
from .context import Context
from .protocol import validate_action, EDIT_RULES

DOMAINS={'coding','data_analysis','math','search'}


def fields(domain):
    result={'phase':('phase',None),'next_step':('str',160),'facts':('list',4),
            'remaining':('list',6),'failed_attempts':('list',4),'candidate':('str',512)}
    if domain=='coding':result.update(remaining_changes=('list',5),verification_note=('str',240))
    elif domain in ('data_analysis','math'):result.update(script=('str',160),calculation_rule=('str',240))
    elif domain=='search':result.update(next_lookup=('str',160),visited=('list',12))
    return result


class ProgressContext(Context):
    def __init__(self,domain,mode='state',max_chars=6000,hybrid_turns=1):
        super().__init__(mode,max_chars,hybrid_turns)
        self.domain=domain if domain in DOMAINS else 'generic'
        self.field_types=fields(self.domain)
        self.defaults={key:([] if kind=='list' else 'inspect' if kind=='phase' else '')
                       for key,(kind,_) in self.field_types.items()}
        self.state=copy.deepcopy(self.defaults)
        self.execution={'read_files':[],'modified_files':[],'last_command':None,
                        'scope':'modified_files lists successful write/edit tools only; Bash may also change files. Tool output is not proof of task correctness.'}
        self.evidence=None

    def rules(self):
        descriptions={
            'phase':'inspect, implement, verify, or submit; follow observed progress',
            'next_step':'the next concrete step; change it after its result',
            'facts':'future-relevant observations, citing oN IDs',
            'remaining':'remaining steps in execution order',
            'failed_attempts':'failed approaches and their observed reasons',
            'candidate':'a candidate final value supported by observed output; not an assumption',
            'remaining_changes':'specific code changes still needed',
            'verification_note':'what was actually checked, and what remains unverified',
            'script':'path to a reusable calculation script',
            'calculation_rule':'filters, joins, rounding or operation order required by the task',
            'next_lookup':'the next unresolved lookup',
            'visited':'recent visited identifiers; use files/scripts for large traversals'}
        schema='; '.join(f'{name}: {descriptions[name]}' for name in self.field_types)
        procedure={
            'coding':'Inspect requirements and tests, then implement a small change and run tests. Preserve test files. A repeated unchanged read is not an implementation step.',
            'data_analysis':'Inspect headers and a small sample; compute over the complete files in Python. Save a reusable script. Never infer an aggregate from a truncated preview.',
            'math':'Use Python for exact arithmetic and operation order. Keep the observed candidate so it can be submitted without recalculating.',
            'search':'For linked files or many revisions, automate traversal in Python instead of repeatedly reading individual nodes. Apply task selection rules before following links; track visited identifiers.',
            'generic':'Use tools to establish missing facts, make changes and verify the requested result.'}[self.domain]
        return '''Response protocol: progress-v1. Return exactly one JSON object.
Required action examples: {"action":{"action":"read","path":"SPEC.md"}}, {"action":{"action":"bash","command":"python3 solve.py"}}, {"action":{"action":"write","path":"solve.py","content":"..."}}, {"action":{"action":"final","answer":"42"}}, {"action":{"action":"skip","reason":"missing data"}}.
Optional state_patch updates only the named fields below. Omitted fields remain; null resets a field. Lists replace the previous list.
''' + procedure + '\n' + schema + '''.
Use short strings; list entries <=160 chars. facts and failed_attempts <=4 entries; remaining <=6; remaining_changes <=5; visited <=12.
Persist the latest computed candidate before reading something else. Observations override unsupported notes.
execution is host-owned data, not verified task correctness. Do not patch execution.
Do not repeat an unchanged inspection whose information you already have: implement the next small change or compute with Python. Reading again is allowed when evidence is missing or a source changed.
Record previous observed results, never assume the proposed action succeeded. No extra reasoning prose.
''' + ('\n'+EDIT_RULES if self.allow_edit else '')

    def patch_schema(self):
        props={}
        for key,(kind,limit) in self.field_types.items():
            if kind=='phase':props[key]={'type':['string','null'],'enum':['inspect','implement','verify','submit',None]}
            elif kind=='str':props[key]={'type':['string','null'],'maxLength':limit}
            else:props[key]={'type':['array','null'],'maxItems':limit,'items':{'type':'string','maxLength':160}}
        return {'type':'object','properties':props,'additionalProperties':False}

    def accept(self,response):
        if not isinstance(response,dict) or 'action' not in response or set(response)-{'action','state_patch'}:
            raise ValueError('Required action object; only optional state_patch is allowed')
        action=validate_action(response['action'],self.allow_edit)
        patch=response.get('state_patch',{})
        if not isinstance(patch,dict) or set(patch)-set(self.field_types):
            raise ValueError('Unknown progress state field; execution is read-only')
        candidate=copy.deepcopy(self.state)
        for key,value in patch.items():
            kind,limit=self.field_types[key]
            if value is None:candidate[key]=copy.deepcopy(self.defaults[key]);continue
            valid=(isinstance(value,str) and value in ('inspect','implement','verify','submit')) if kind=='phase' else (
                isinstance(value,str) and len(value)<=limit if kind=='str' else
                isinstance(value,list) and len(value)<=limit and all(isinstance(v,str) and len(v)<=160 for v in value))
            if not valid:raise ValueError(f'Invalid progress field {key}: expected {kind}, limit {limit}')
            candidate[key]=copy.deepcopy(value)
        if len(json.dumps(candidate,ensure_ascii=False))>self.max_chars:
            raise ValueError('Progress state too large; remove stale entries')
        self.state=candidate;self.revision+=1
        return action

    def messages(self,system,initial,runtime,history_chars):
        messages=super().messages(system,initial,runtime,history_chars)
        frame=json.loads(messages[-1]['content'])
        frame['domain']=self.domain
        frame['state']={key:value for key,value in self.state.items() if value not in ('',[])}
        execution=self.evidence.frame(self.latest.get('id')) if self.evidence else copy.deepcopy(self.execution)
        if execution.get('last_command') and execution['last_command']['id']==self.latest.get('id'):
            execution.pop('last_command')
        frame['execution']={key:value for key,value in execution.items() if value not in (None,[],{})}
        messages[-1]['content']=json.dumps(frame,ensure_ascii=False,separators=(',',':'))
        return messages

    def record_tool(self,action,result,step,root):
        if self.evidence:
            self.evidence.observe(action,result,step);return
        kind=action['action'];path=action.get('path')
        if kind=='read' and 'content'in result:
            self.execution['read_files']=[*dict.fromkeys([*self.execution['read_files'],path])][-8:]
        if kind in ('write','edit') and ('written'in result or 'edited'in result):
            self.execution['modified_files']=[*dict.fromkeys([*self.execution['modified_files'],path])][-8:]
        if kind=='bash':
            self.execution['last_command']={'id':f'o{step+1}','command':action['command'][:160],
                'returncode':result.get('returncode'),'timeout':result.get('timeout',False),
                'output':result.get('output',result.get('error',''))[:240],
                'excerpted':len(result.get('output',result.get('error','')))>240 or result.get('truncated',False)}
