"""New task families; expected values and held-out tests stay outside workspace."""
import argparse,csv, json, random, sqlite3
from pathlib import Path

parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,default=Path('experiments/skillstate/harder-v1'));parser.add_argument('--seed',type=int,default=20261113);args=parser.parse_args()
ROOT=args.out
rng=random.Random(args.seed)
ROOT.mkdir(parents=True,exist_ok=False)
def task(name,kind,instruction,reward,expected,check):
    root=ROOT/name;(root/'workspace').mkdir(parents=True)
    (root/'task.json').write_text(json.dumps(dict(task_id=name,task_type=kind,instruction=instruction,reward=reward,expected=str(expected),check=check),indent=2))
    return root

def csvfile(path,columns,rows):
    with path.open('w') as out:
        w=csv.writer(out);w.writerow(columns);w.writerows(rows)

customers=[(i,rng.choice(['east','west','north'])) for i in range(120)]
orders=[(i,rng.randrange(120),rng.randint(1,12),rng.choice(['paid','cancelled']),rng.randint(100,40000)) for i in range(2400)]
refunds=[(i,rng.randint(0,amount)) for i,c,m,status,amount in orders if rng.random()<.28]
regions=dict(customers);ref=dict(refunds)
answer=sum(amount-ref.get(i,0) for i,c,m,status,amount in orders if regions[c]=='west' and 4<=m<=9 and status=='paid')
# Independent relational oracle catches generator/join/filter mistakes.
db=sqlite3.connect(':memory:')
db.executescript('create table customers(id integer,region text);create table orders(id integer,customer integer,month integer,status text,cents integer);create table refunds(order_id integer,cents integer);')
db.executemany('insert into customers values (?,?)',customers);db.executemany('insert into orders values (?,?,?,?,?)',orders);db.executemany('insert into refunds values (?,?)',refunds)
assert answer==db.execute("select sum(o.cents-coalesce(r.cents,0)) from orders o join customers c on c.id=o.customer left join refunds r on r.order_id=o.id where c.region='west' and o.month between 4 and 9 and o.status='paid'").fetchone()[0]
t=task('net_revenue','data_analysis','Compute net paid revenue in integer cents for west-region customers in months 4 through 9 inclusive. Join customers.csv to orders.csv on customer_id; subtract every matching refund from refunds.csv, missing refund means zero. Exclude cancelled orders entirely, including their refunds. All amounts are integers; submit only the total. Do not assume row alignment.',4,answer,'exact_int')
w=t/'workspace';csvfile(w/'customers.csv',['customer_id','region'],customers);csvfile(w/'orders.csv',['order_id','customer_id','month','status','amount_cents'],orders);rng.shuffle(refunds);csvfile(w/'refunds.csv',['order_id','refund_cents'],refunds)

ids=rng.sample(range(10000,99999),24);code=f'RELEASE-{rng.randint(100000,999999)}'
t=task('versioned_route','search',f'Find the release code reachable from node {ids[0]} using kb/. Each node has historical revision records. Select the greatest revision number with status active at EACH node; revoked records are never valid. Follow its next field until a terminal record. Submit only that terminal release_code. Other terminals and old revisions are decoys. You may automate traversal.',3,code,'exact_str')
w=t/'workspace'/'kb';w.mkdir()
for i,node in enumerate(ids):
    records=[{'revision':1,'status':'active','release_code':'OLD-DECOY'}, {'revision':9,'status':'revoked','release_code':'REVOKED-DECOY'}, {'revision':4,'status':'active',**({'next':ids[i+1]} if i+1<len(ids) else {'release_code':code})}]
    rng.shuffle(records);(w/f'node_{node}.json').write_text(json.dumps(records,indent=2))
for n in range(50): (w/f'unrelated_{n}.json').write_text(json.dumps([{'revision':99,'status':'active','release_code':f'DECOY-{n}'}]))

t=task('intervals_and_ledger','coding','Fix library.py according to SPEC.md. Preserve tests. Use only Python standard library. Run test_mylib.py and submit DONE only after tests pass. Hidden tests also check the documented edge cases.',5,'tests_pass','unittest')
w=t/'workspace'
(w/'SPEC.md').write_text('''Implement four independent functions without changing signatures.
merge_intervals(intervals): input pairs [start,end] with start<=end, unsorted. Return a sorted list of tuples, merging overlaps AND touching boundaries. Empty input -> []. Do not mutate the input.
allocate(total, weights): total is a nonnegative integer; weights a nonempty list of nonnegative integers with positive sum. Return integer shares summing to total using largest remainder apportionment: floor(total*w/sum(weights)), then distribute remaining units by descending remainder, ties by lower original index. Use exact integer arithmetic, including huge integers.
unique_latest(rows): list of dicts with id and revision (integer) and arbitrary data. For each id keep its greatest revision; ties keep LAST occurrence. Return chosen dicts sorted by id. Do not mutate input.
rolling_net(events): events are (account, delta) pairs, delta integer. Return a dict of each account's balance, accumulating all deltas, preserving accounts with zero or negative balance. Empty input -> {}.
''')
(w/'library.py').write_text('''def merge_intervals(intervals):
    return sorted(intervals)
def allocate(total, weights):
    return [round(total*w/sum(weights)) for w in weights]
def unique_latest(rows):
    return list({r['id']:r for r in rows}.values())
def rolling_net(events):
    return dict(events)
''')
(w/'test_mylib.py').write_text('''import unittest
from library import *
class T(unittest.TestCase):
 def test_merge(self): self.assertEqual(merge_intervals([(5,8),(1,3),(3,6)]),[(1,8)])
 def test_allocate(self): self.assertEqual(allocate(5,[1,1,1]),[2,2,1])
 def test_latest(self): self.assertEqual(unique_latest([{'id':'b','revision':2},{'id':'a','revision':3},{'id':'a','revision':1}]),[{'id':'a','revision':3},{'id':'b','revision':2}])
 def test_net(self): self.assertEqual(rolling_net([('a',3),('b',7),('a',-3)]),{'a':0,'b':7})
if __name__=='__main__':unittest.main()
''')
(t/'hidden_test.py').write_text('''import unittest, copy
from library import *
class Hidden(unittest.TestCase):
 def test_empty(self):
  self.assertEqual(merge_intervals([]),[]);self.assertEqual(unique_latest([]),[]);self.assertEqual(rolling_net([]),{})
 def test_contained_and_immutable(self):
  xs=[[6,9],[1,20],[30,31],[31,40]];original=copy.deepcopy(xs)
  self.assertEqual(merge_intervals(xs),[(1,20),(30,40)]);self.assertEqual(xs,original)
 def test_integer_precision(self):
  self.assertEqual(allocate(10**20+1,[1,1]),[50000000000000000001,50000000000000000000])
  self.assertEqual(allocate(2,[0,3,3]),[0,1,1]);self.assertEqual(allocate(0,[3,1]),[0,0])
 def test_revisions_and_ties(self):
  rows=[{'id':'z','revision':8,'v':1},{'id':'z','revision':8,'v':2},{'id':'a','revision':9},{'id':'a','revision':0}];old=copy.deepcopy(rows)
  self.assertEqual(unique_latest(rows),[rows[2],rows[1]]);self.assertEqual(rows,old)
 def test_negative_and_zero(self):
  self.assertEqual(rolling_net([('x',-5),('x',2),('y',0)]),{'x':-3,'y':0})
if __name__=='__main__':unittest.main()
''')
print(f'Generated 3 harder tasks in {ROOT}; independent SQL oracle verified')
