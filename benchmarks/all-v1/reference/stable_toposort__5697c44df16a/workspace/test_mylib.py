import unittest
from library import topological_order
class T(unittest.TestCase):
 def test_order(self):self.assertEqual(topological_order(["a","b","c"],[("c","a")]),["b","c","a"])
 def test_empty(self):self.assertEqual(topological_order([],[]),[])
if __name__=="__main__":unittest.main()
