import copy,json,os,tempfile,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from baseline.client import Client
from baseline.context import Context
from baseline.core import Budget,Trace,Task
from baseline.execution_evidence import ExecutionEvidence
from baseline.progress import ProgressContext
from baseline.solver import solve
from baseline.tools import execute
from baseline.wire import response_format,response_schema


class StateV2Tests(unittest.TestCase):
    def test_edit_is_exact_atomic_and_preserves_permissions_and_line_endings(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);file=root/'script.py';file.write_bytes(b'a=1\r\nb=2\r\n');file.chmod(0o755)
            result=execute({'action':'edit','path':'script.py','old':'a=1','new':'a=3'},root,1,100)
            self.assertEqual(result['replacements'],1)
            self.assertEqual(file.read_bytes(),b'a=3\r\nb=2\r\n')
            self.assertEqual(file.stat().st_mode&0o777,0o755)
            file.write_text('aaa')
            for old in ('aa','missing',''):
                with self.assertRaises(ValueError):execute({'action':'edit','path':'script.py','old':old,'new':'x'},root,1,100)
                self.assertEqual(file.read_text(),'aaa')

    def test_edit_rejects_escape_and_test_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);file=root/'test_mylib.py';file.write_text('assert False')
            with self.assertRaises(ValueError):execute({'action':'edit','path':'test_mylib.py','old':'False','new':'True'},root,1,100)
            self.assertEqual(file.read_text(),'assert False')
            with self.assertRaises(ValueError):execute({'action':'edit','path':'../outside','old':'a','new':'b'},root,1,100)

    def test_edit_registration_does_not_change_control_schema(self):
        c=Context('state');response={'action':{'action':'edit','path':'a','old':'x','new':'y'}}
        with self.assertRaises(ValueError):c.accept(response)
        c.allow_edit=True
        self.assertEqual(c.accept(response),response['action'])
        self.assertIn('edit',json.dumps(response_schema(edit=True)))
        terminal=response_schema(edit=True,terminal_only=True)['properties']['action']['anyOf']
        self.assertEqual({v['properties']['action']['enum'][0] for v in terminal},{'final','skip'})

    def test_progress_domains_and_atomic_rejection(self):
        c=ProgressContext('coding');before=copy.deepcopy(c.state)
        for patch in [{'phase':'invented'},{'facts':{'wrong':'type'}},{'execution':{}},{'remaining_changes':['x'*161]}]:
            with self.assertRaises(ValueError):c.accept({'action':{'action':'read','path':'x'},'state_patch':patch})
            self.assertEqual(c.state,before)
        c.accept({'action':{'action':'read','path':'x'},'state_patch':{'phase':'implement','remaining_changes':['Fix integer division'],'next_step':'edit allocate'}})
        self.assertEqual(c.state['phase'],'implement')
        c.accept({'action':{'action':'read','path':'x'},'state_patch':{'remaining_changes':None}})
        self.assertEqual(c.state['remaining_changes'],[])
        self.assertEqual(ProgressContext('unknown-type').domain,'generic')
        self.assertNotIn('remaining_changes',ProgressContext('math').field_types)

    def test_progress_notes_do_not_claim_action_was_executed(self):
        c=ProgressContext('coding');c.allow_edit=True
        c.accept({'action':{'action':'edit','path':'a','old':'x','new':'y'},'state_patch':{'phase':'implement'}})
        self.assertEqual(c.execution['modified_files'],[])

    def test_domain_policy_uses_only_public_task_type_with_generic_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for domain,expected in [('math',False),('search',True),('unseen',False)]:
                case=root/domain;case.mkdir();budget=Budget(5000,time.monotonic()+10)
                class Scripted:
                    timeout=5
                    def complete(self,messages,*args):
                        self.messages=messages;budget.spent+=10
                        return '{"action":{"action":"final","answer":"42"}}'
                client=Scripted()
                config=SimpleNamespace(context_mode='state',response_protocol='unified',progress_state=True,progress_domains=['search'],
                    edit_tool=True,edit_domains=['search'],
                    task_seconds=5,task_budget=5000,max_steps=1,history_chars=24000,max_output_tokens=900,tool_seconds=1,tool_output_chars=12000)
                solve(Task(case,'arbitrary-id',domain,'Return a value',1),client,budget,Trace(root/(domain+'.jsonl')),config)
                frame=json.loads(client.messages[-1]['content'])
                self.assertEqual('domain'in frame,expected)
                self.assertEqual('Additional action:'in client.messages[0]['content'],expected)

    def test_precise_read_freshness_ignores_unrelated_writes_but_tracks_bash_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'data').write_text('42')
            memory=ExecutionEvidence(root)
            memory.observe({'action':'read','path':'data'},{'content':'42','truncated':False},0)
            (root/'script.py').write_text('print(42)')
            memory.observe({'action':'write','path':'script.py','content':'print(42)'},{'written':'script.py'},1)
            self.assertEqual(memory.frame()['read_files'][0]['freshness'],'unchanged')
            (root/'data').write_text('99')
            memory.observe({'action':'bash','command':'change data'},{'returncode':0,'output':'99'},2)
            self.assertEqual(memory.frame()['read_files'][0]['freshness'],'stale')
            self.assertEqual(memory.frame()['command_results'][0]['freshness'],'unknown_dependencies')

    def test_precise_evidence_survives_reads_is_bounded_and_does_not_hide_failures(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'data').write_text('42');m=ExecutionEvidence(root)
            m.observe({'action':'bash','command':'calculate'},{'output':'438293','returncode':0,'timeout':False},0)
            for step in range(1,12):m.observe({'action':'read','path':'data'},{'content':'42','truncated':False},step)
            frame=m.frame('o12')
            self.assertEqual(frame['command_results'][0]['output'],'438293')
            self.assertEqual(frame['read_files'][0]['read_count'],11)
            m.observe({'action':'bash','command':'x'*9000},{'output':'\x00😀'*9000,'returncode':-9,'timeout':True,'truncated':True},12)
            frame=m.frame()
            self.assertLessEqual(len(json.dumps(frame,ensure_ascii=False,separators=(',',':'))),1800)
            self.assertEqual(frame['command_results'][-1]['returncode'],-9)
            self.assertTrue(frame['command_results'][-1]['timeout'])

    def test_response_format_payload_accounting_and_no_implicit_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            budget=Budget(5000,time.monotonic()+10)
            client=Client('https://example.invalid/v1','private','qwen3.8-27b-noreason',budget,Trace(Path(directory)/'trace'),response_format=response_format('json_schema'))
            class Response:
                def __enter__(self):return self
                def __exit__(self,*args):pass
                def read(self,limit):return json.dumps({'choices':[{'message':{'content':'{"action":{"action":"final","answer":"42"}}'},'finish_reason':'stop'}],'usage':{'prompt_tokens':100,'completion_tokens':20}}).encode()
            messages=[{'role':'user','content':'Compute'}]
            self.assertGreater(len(client.accounting_messages(messages)),len(messages))
            with patch('urllib.request.urlopen',return_value=Response()) as request:
                client.complete(messages,'task',900,5000)
            payload=json.loads(request.call_args.args[0].data)
            self.assertEqual(payload['messages'],messages)
            self.assertEqual(payload['response_format']['type'],'json_schema')
            self.assertEqual(budget.spent,30)
            self.assertEqual(client.last_finish_reason,'stop')
            client.schema_accounting='messages'
            self.assertEqual(client.accounting_messages(messages),messages)

    def test_recommended_launcher_honors_explicit_user_flags(self):
        import run_solution,run_agent
        from unittest.mock import AsyncMock
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'configs').mkdir()
            (root/'configs/recommended.json').write_text(json.dumps({'flags':['--output-format','json_schema','--edit-tool']}))
            argv=['run_solution','--tasks-dir',str(root/'tasks'),'--output-format','text','--dry-run']
            with patch.object(run_solution,'__file__',str(root/'run_solution.py')),patch('sys.argv',argv),patch.object(run_agent,'main',new_callable=AsyncMock,return_value=0) as main:
                self.assertEqual(run_solution.main(),0)
            config=main.call_args.args[0]
            self.assertEqual(config.output_format,'text')
            self.assertTrue(config.edit_tool)
            self.assertTrue(config.dry_run)

    def test_full_progress_solver_records_real_edit_and_candidate_after_read(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);case=root/'case';(case/'workspace').mkdir(parents=True)
            (case/'workspace/code.py').write_text('x=1\n')
            (case/'workspace/data').write_text('irrelevant')
            budget=Budget(10000,time.monotonic()+20)
            class ScriptedClient:
                timeout=10
                def __init__(self):self.messages=[]
                def complete(self,messages,*args):
                    self.messages.append(messages);budget.spent+=10
                    actions=[{'action':'edit','path':'code.py','old':'x=1','new':'x=42'},
                             {'action':'bash','command':"python3 -c 'print(6*7)'"},
                             {'action':'read','path':'data'},{'action':'final','answer':'42'}]
                    return json.dumps({'action':actions[len(self.messages)-1]})
            client=ScriptedClient()
            config=SimpleNamespace(context_mode='state',response_protocol='unified',output_format='text',edit_tool=True,progress_state=True,evidence_policy='precise',
                task_seconds=15,task_budget=10000,max_steps=6,history_chars=24000,max_output_tokens=900,tool_seconds=2,tool_output_chars=12000)
            result=solve(Task(case,'any','math','Compute 6*7',1),client,budget,Trace(root/'trace'),config)
            self.assertEqual(result['status'],'submitted')
            frame=json.loads(client.messages[-1][-1]['content'])
            self.assertEqual(frame['execution']['command_results'][0]['output'],'42\n')
            self.assertIn('code.py',frame['execution']['modified_files'])

    def test_structured_solver_exposes_actual_cap_and_limits_terminal_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);case=root/'case';case.mkdir()
            budget=Budget(5000,time.monotonic()+20)
            trace=Trace(root/'trace')
            client=Client('https://example.invalid/v1','private','qwen3.8-27b-noreason',budget,trace)
            class Response:
                def __enter__(self):return self
                def __exit__(self,*args):pass
                def read(self,limit):return json.dumps({'choices':[{'message':{'content':'{"action":{"action":"final","answer":"42"}}'},'finish_reason':'stop'}],'usage':{'prompt_tokens':100,'completion_tokens':20}}).encode()
            config=SimpleNamespace(context_mode='state',response_protocol='unified',output_format='json_schema',
                task_seconds=15,task_budget=5000,max_steps=1,history_chars=24000,max_output_tokens=900,
                tool_seconds=2,tool_output_chars=12000,budget_policy='reserve',finish_output_tokens=256,finish_seconds=1)
            with patch('urllib.request.urlopen',return_value=Response()) as request:
                result=solve(Task(case,'any','math','Compute 6*7',1),client,budget,trace,config)
            self.assertEqual(result['status'],'submitted')
            payload=json.loads(request.call_args.args[0].data)
            frame=json.loads(payload['messages'][-1]['content'])
            self.assertEqual(frame['runtime']['max_response_tokens'],payload['max_tokens'])
            variants=payload['response_format']['json_schema']['schema']['properties']['action']['anyOf']
            self.assertEqual({v['properties']['action']['enum'][0] for v in variants},{'final','skip'})
            self.assertEqual(budget.spent,30)


if __name__=='__main__':unittest.main()
