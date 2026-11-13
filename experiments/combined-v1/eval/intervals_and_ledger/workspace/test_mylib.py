import unittest
from library import *
class T(unittest.TestCase):
 def test_merge(self): self.assertEqual(merge_intervals([(5,8),(1,3),(3,6)]),[(1,8)])
 def test_allocate(self): self.assertEqual(allocate(5,[1,1,1]),[2,2,1])
 def test_latest(self): self.assertEqual(unique_latest([{'id':'b','revision':2},{'id':'a','revision':3},{'id':'a','revision':1}]),[{'id':'a','revision':3},{'id':'b','revision':2}])
 def test_net(self): self.assertEqual(rolling_net([('a',3),('b',7),('a',-3)]),{'a':0,'b':7})
if __name__=='__main__':unittest.main()
