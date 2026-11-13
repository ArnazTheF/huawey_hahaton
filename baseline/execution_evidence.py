"""Small host-owned evidence: exact read dependencies, opaque command outcomes."""
import copy,hashlib,json
from pathlib import Path
from .tools import safe_path
from .observation_memory import excerpt


def file_digest(root,path):
    try:
        file=safe_path(root,path)
        if not file.is_file() or file.stat().st_size>8*1024*1024:return None
        return hashlib.sha256(file.read_bytes()).hexdigest()
    except (OSError,ValueError):return None


class ExecutionEvidence:
    def __init__(self,root,max_chars=1800):
        self.root=Path(root);self.max_chars=max_chars
        self.reads={};self.modified=[];self.outputs=[]

    def observe(self,action,result,step):
        kind=action['action'];path=action.get('path');oid=f'o{step+1}'
        if kind=='read' and 'content'in result:
            digest=file_digest(self.root,path);previous=self.reads.get(path)
            count=previous['count']+1 if previous and digest is not None and previous['digest']==digest else 1
            self.reads.pop(path,None)
            self.reads[path]={'id':oid,'digest':digest,'count':count,'excerpted':bool(result.get('truncated'))}
            while len(self.reads)>8:self.reads.pop(next(iter(self.reads)))
        if kind in ('write','edit') and ('written'in result or 'edited'in result):
            self.modified=[*dict.fromkeys([*self.modified,path])][-6:]
        if kind=='bash':
            output=result.get('output',result.get('error',''))
            record={'id':oid,'command':excerpt(action['command'],140),
                    'returncode':result.get('returncode'),'timeout':result.get('timeout',False),
                    'output':excerpt(output,280),'excerpted':len(output)>280 or bool(result.get('truncated')),
                    'freshness':'unknown_dependencies'}
            self.outputs.append(record);self.outputs=self.outputs[-2:]

    def frame(self,latest_id=None):
        files=[]
        for path,record in self.reads.items():
            current=file_digest(self.root,path)
            freshness='unknown' if current is None or record['digest'] is None else ('unchanged' if current==record['digest'] else 'stale')
            files.append({'path':path,'id':record['id'],'read_count':record['count'],'freshness':freshness,
                          'excerpted':record['excerpted']})
        frame={'read_files':files,'modified_files':list(self.modified),
               'command_results':[copy.deepcopy(r) for r in self.outputs if r['id']!=latest_id],
               'notice':'Host observations, not verified answers. Read freshness covers only that file. modified_files lists write/edit tools only; Bash may change files. Bash dependencies are unknown. Repeated unchanged reads do not add information; use a narrower read or act when ready.'}
        while len(json.dumps(frame,ensure_ascii=False,separators=(',',':')))>self.max_chars:
            if len(frame['read_files'])>2:frame['read_files'].pop(0)
            elif len(frame['command_results'])>1:frame['command_results'].pop(0)
            elif frame['command_results']:
                r=frame['command_results'][0]
                if len(r['output'])>40:r['output']=excerpt(r['output'],len(r['output'])//2);r['excerpted']=True
                else:frame['command_results'].pop(0)
            elif frame['read_files']:frame['read_files'].pop(0)
            elif frame['modified_files']:frame['modified_files'].pop(0)
            else:break
        return frame
