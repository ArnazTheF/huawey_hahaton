import unittest,copy
from library import topological_order
class Hidden(unittest.TestCase):
 def test_duplicate(self):self.assertEqual(topological_order(["b","a"],[("b","a"),("b","a")]),["b","a"])
 def test_cycle(self):
  with self.assertRaises(ValueError):topological_order(["a","b"],[("a","b"),("b","a")])
 def test_dynamic_frontier(self):self.assertEqual(topological_order(["a","b","c","d"],[("b","a"),("a","d")]),["b","a","c","d"])
 def test_immutable(self):
  n=["z","a"];e=[("z","a")];old=copy.deepcopy((n,e));self.assertEqual(topological_order(n,e),["z","a"]);self.assertEqual((n,e),old)
if __name__=="__main__":unittest.main()
