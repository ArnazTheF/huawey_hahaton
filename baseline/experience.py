"""Small lexical experience memory: verified lessons and unlabeled observations."""
import collections,json,math,re
from pathlib import Path
from .task_features import family_id


def terms(text):
    return collections.Counter(re.findall(r'[a-zA-Z_]{3,}',text.lower()))


class Experience:
    def __init__(self, data=None):
        data=data or {'schema':1,'cards':[],'behaviors':[]}
        if data.get('schema')!=1:raise ValueError('Unsupported experience schema')
        self.cards=data.get('cards',[]);self.behaviors=data.get('behaviors',[])
        for card in self.cards:
            if card.get('verification')!='external_grader':raise ValueError('Lesson must be externally verified')
            if len(card.get('lesson',''))>480:raise ValueError('Experience lesson too long')

    @classmethod
    def load(cls,path):return cls(json.loads(Path(path).read_text()))

    def retrieve(self, task, kind='cards', limit=1):
        records=getattr(self,kind);query=terms(task.instruction)
        documents=[terms(r['description']) for r in records]
        df=collections.Counter(word for doc in documents for word in doc)
        def vector(doc):return {word:count*(math.log((1+len(documents))/(1+df[word]))+1) for word,count in doc.items()}
        q=vector(query);qn=math.sqrt(sum(v*v for v in q.values())) or 1
        ranked=[]
        for record,doc in zip(records,documents):
            if record.get('family')==family_id(task):continue
            v=vector(doc);norm=math.sqrt(sum(x*x for x in v.values())) or 1
            similarity=sum(q.get(k,0)*value for k,value in v.items())/qn/norm
            if similarity>=.08:
                ranked.append((similarity,record))
        return [dict(record,similarity=round(score,3)) for score,record in sorted(ranked,key=lambda x:-x[0])[:limit]]

    def lesson(self,task):
        records=self.retrieve(task)
        if not records:return None
        r=records[0]
        return {'id':r['id'],'lesson':r['lesson'],'verification':r['verification'],'similarity':r['similarity']}

    def observations(self,task):
        # No gold labels, rewards or pass flags are exposed to the router.
        rows=self.retrieve(task,'behaviors',2)
        return [{'description':r['description'][:220],'observations':[{key:value for key,value in observation.items() if key in {'model','mode','answer','status','cost','seconds'}} for observation in r['observations']]} for r in rows]
