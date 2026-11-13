"""JSON response schemas; no network, model calls, or repair heuristics."""
from .protocol import FIELDS


def action_schema(edit=False, terminal_only=False):
    tools={'bash':('command',),'read':('path',),'write':('path','content'),
           'final':('answer',),'skip':('reason',)}
    if edit:tools['edit']=('path','old','new')
    if terminal_only:tools={key:value for key,value in tools.items() if key in ('final','skip')}
    return {'anyOf':[{'type':'object','properties':{'action':{'type':'string','enum':[name]},
                      **{key:{'type':'string'} for key in args}},
                     'required':['action',*args],'additionalProperties':False}
                    for name,args in tools.items()]}


def response_schema(edit=False, terminal_only=False, patch_schema=None):
    if patch_schema is None:
        patch_schema={'type':'object','properties':{key:{'type':'object','maxProperties':8,
                      'additionalProperties':{'type':['string','null'],'maxLength':240}} for key in sorted(FIELDS)},
                      'additionalProperties':False}
    return {'type':'object','properties':{'action':action_schema(edit,terminal_only),'state_patch':patch_schema},
            'required':['action'],'additionalProperties':False}


def response_format(mode, **kwargs):
    if mode=='text':return None
    if mode=='json_object':return {'type':'json_object'}
    if mode=='json_schema':return {'type':'json_schema','json_schema':{'name':'agent_step','strict':True,'schema':response_schema(**kwargs)}}
    raise ValueError('Unknown output format')
