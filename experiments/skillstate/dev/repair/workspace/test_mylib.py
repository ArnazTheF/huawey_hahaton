import unittest
from normalize import normalize
class T(unittest.TestCase):
 def test_basic(self): self.assertEqual(normalize([" B ","", " a ","  "]),["b","a"])
 def test_empty(self): self.assertEqual(normalize([]),[])
if __name__ == "__main__": unittest.main()
