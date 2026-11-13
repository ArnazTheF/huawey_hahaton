"""Eight diverse synthetic tasks, including two provably underspecified/inconsistent."""
import csv,json,random,datetime
from pathlib import Path
root=Path('experiments/state-broad-v1');root.mkdir(parents=True,exist_ok=False)
rng=random.Random(813927)
def task(name,kind,instruction,answer,check='exact_int',impossible=False):
 d=root/name;(d/'workspace').mkdir(parents=True)
 (d/'task.json').write_text(json.dumps({'task_id':name,'task_type':kind,'instruction':instruction,'reward':rng.randint(1,5),'expected':str(answer),'check':check,'impossible':impossible},indent=2))
 return d
# Integer arithmetic simulation with order and flooring.
ops=[(rng.choice(['add','multiply','divide']),rng.randint(1,7)) for _ in range(80)]
value=137
for operation,n in ops:value=value+n if operation=='add' else value*n if operation=='multiply' else value//n
d=task('integer_program','math','Starting from integer 137, apply instructions in ops.json in order. add adds value, multiply multiplies, divide uses floor integer division. Submit the final integer.',value)
(d/'workspace/ops.json').write_text(json.dumps(ops))
start=datetime.date(2026,2,1);end=datetime.date(2026,4,30)
holidays={datetime.date(2026,2,17),datetime.date(2026,3,9),datetime.date(2026,4,10)}
answer=sum((start+datetime.timedelta(days=i)).weekday()<5 and start+datetime.timedelta(days=i) not in holidays for i in range((end-start).days+1))
task('working_days','math','How many Monday-Friday days are there from 2026-02-01 through 2026-04-30 inclusive, excluding holidays 2026-02-17, 2026-03-09, 2026-04-10? Compute with Python. Submit only the integer.',answer)
rows=[];latest={}
for i in range(70):
 for revision in range(1,rng.randint(2,5)):
  rows.append([i,revision,rng.choice(['open','cancelled']),rng.randint(1,20),rng.randint(100,2000)])
rng.shuffle(rows)
for row in rows:
 if row[0] not in latest or row[1]>=latest[row[0]][1]:latest[row[0]]=row
answer=sum(r[3]*r[4] for r in latest.values() if r[2]=='open')
d=task('snapshot_revenue','data_analysis','Read snapshots.csv. For each order_id keep the greatest revision; if tied keep the LAST file occurrence. Include only orders whose selected status is open. Sum units*unit_cents using integer arithmetic. Submit only total cents.',answer)
with (d/'workspace/snapshots.csv').open('w') as f:
 w=csv.writer(f);w.writerow(['order_id','revision','status','units','unit_cents']);w.writerows(rows)
values=[rng.randint(-30,100) for _ in range(101)]
answer=sorted(v for v in values if v>=0)[(sum(v>=0 for v in values)-1)//2]
d=task('lower_median','data_analysis','Read readings.json; discard negative readings. Return the LOWER median of the remaining values (index (n-1)//2 after sorting). Keep duplicates. Submit only the integer.',answer)
(d/'workspace/readings.json').write_text(json.dumps(values))
# Local multi-hop lookup, distractors and explicit active relation.
d=task('manager_office','search','Using kb.json: find the active employee named Mira, follow her current manager_id, then that manager office_id, and return the office canonical_city. Ignore inactive employees and old_manager_id. Submit only the city.','Tallinn','exact_str')
(d/'workspace/kb.json').write_text(json.dumps({'employees':[{'id':'e1','name':'Mira','active':False,'manager_id':'m0'},{'id':'e2','name':'Mira','active':True,'manager_id':'m3','old_manager_id':'m0'}], 'managers':[{'id':'m0','office_id':'o0'},{'id':'m3','office_id':'o7'}], 'offices':[{'id':'o0','canonical_city':'Osaka'},{'id':'o7','canonical_city':'Tallinn'}]},indent=2))
d=task('stable_toposort','coding','Fix library.py per SPEC.md. Preserve test_mylib.py. Use standard Python. Run tests and submit DONE. Hidden tests cover the specification edge cases.','tests_pass','unittest')
(d/'workspace/SPEC.md').write_text('topological_order(nodes, edges): nodes is a list of unique strings. Directed edges (u,v) mean u before v. Return a topological order of ALL nodes. At each step choose lexicographically smallest currently available node. Duplicate edges must not change the result. Empty nodes -> []. Raise ValueError on any cycle. Do not mutate nodes or edges. All edge endpoints belong to nodes.\n')
(d/'workspace/library.py').write_text('def topological_order(nodes, edges):\n    return sorted(nodes)\n')
(d/'workspace/test_mylib.py').write_text('import unittest\nfrom library import topological_order\nclass T(unittest.TestCase):\n def test_order(self):self.assertEqual(topological_order(["a","b","c"],[("c","a")]),["b","c","a"])\n def test_empty(self):self.assertEqual(topological_order([],[]),[])\nif __name__=="__main__":unittest.main()\n')
(d/'hidden_test.py').write_text('import unittest,copy\nfrom library import topological_order\nclass Hidden(unittest.TestCase):\n def test_duplicate(self):self.assertEqual(topological_order(["b","a"],[("b","a"),("b","a")]),["b","a"])\n def test_cycle(self):\n  with self.assertRaises(ValueError):topological_order(["a","b"],[("a","b"),("b","a")])\n def test_dynamic_frontier(self):self.assertEqual(topological_order(["a","b","c","d"],[("b","a"),("a","d")]),["b","a","c","d"])\n def test_immutable(self):\n  n=["z","a"];e=[("z","a")];old=copy.deepcopy((n,e));self.assertEqual(topological_order(n,e),["z","a"]);self.assertEqual((n,e),old)\nif __name__=="__main__":unittest.main()\n')
d=task('missing_amounts','data_analysis','The manifest describes three private invoices. Report the exact sum of their invoice amounts in cents. No external services are available.',0,impossible=True)
(d/'workspace/manifest.json').write_text(json.dumps({'invoice_ids':['i12','i18','i22'],'amounts_redacted':True}))
task('inconsistent_integer','math','Find an integer x satisfying BOTH x > 10 and x < 5. Submit the integer, if one exists.',0,impossible=True)
print('Generated 8 tasks: 6 solvable, 2 impossible; expected/hidden files outside agent workspace')
