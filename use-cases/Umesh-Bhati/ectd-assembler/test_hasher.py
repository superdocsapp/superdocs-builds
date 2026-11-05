import unittest
import os
import tempfile
import hashlib
from hasher import calculate_file_hash, get_file_hashes

class TestHasher(unittest.TestCase):
    def setUp(self):
        self.fd, self.path = tempfile.mkstemp()
        with os.fdopen(self.fd, 'w') as f:
            f.write('test content')
            
    def tearDown(self):
        os.remove(self.path)
        
    def test_calculate_file_hash(self):
        # Hash of "test content"
        hash_val = calculate_file_hash(self.path)
        self.assertEqual(len(hash_val), 64) # SHA256 is 64 hex chars
        self.assertIsInstance(hash_val, str)
        
    def test_get_file_hashes(self):
        hashes = get_file_hashes({self.path})
        self.assertTrue(self.path in hashes)
        self.assertEqual(len(hashes[self.path]), 64)

    def test_hash_matches_reference_for_large_file(self):
        """A file larger than the streaming chunk size hashes identically to a
        one-shot SHA-256, proving chunked reads do not change the result."""
        large_path = os.path.join(tempfile.mkdtemp(), "large.bin")
        try:
            with open(large_path, "wb") as f:
                f.write(os.urandom(512 * 1024 + 123))
            reference = hashlib.sha256(open(large_path, "rb").read()).hexdigest()
            self.assertEqual(calculate_file_hash(large_path), reference)
        finally:
            os.remove(large_path)

if __name__ == '__main__':
    unittest.main()
