import unittest, copy
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
