"""genios_auth 的离线测试：python3 <skill>/scripts/test_genios_auth.py"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genios_auth as gl  # noqa: E402


class EncryptTest(unittest.TestCase):
    def test_matches_login_page_crypto_js(self):
        # 期望值由登录页同款 crypto-js 4 在 Node 中生成
        self.assertEqual(gl.encrypt_password("Sample#Pass123"), "6ece634a06a0f30ef606e557f0237718")

    def test_strips_whitespace_like_login_page(self):
        self.assertEqual(gl.encrypt_password("  Sample#Pass123 "), gl.encrypt_password("Sample#Pass123"))


class CredentialsFileTest(unittest.TestCase):
    def write(self, text, mode=0o600):
        fd, path = tempfile.mkstemp()
        os.write(fd, text.encode())
        os.close(fd)
        os.chmod(path, mode)
        self.addCleanup(os.remove, path)
        return path

    def test_reads_account_and_password(self):
        path = self.write("ACCOUNT=1120260000\nPASSWORD=a=b#c\n")
        self.assertEqual(gl.read_credentials(path), ("1120260000", "a=b#c"))

    def test_rejects_group_readable_file(self):
        with self.assertRaisesRegex(gl.LoginError, "chmod 600"):
            gl.read_credentials(self.write("ACCOUNT=1\nPASSWORD=2\n", 0o644))

    def test_rejects_missing_password(self):
        with self.assertRaisesRegex(gl.LoginError, "PASSWORD"):
            gl.read_credentials(self.write("ACCOUNT=1\n"))

    def test_rejects_unignored_file_inside_project(self):
        with self.assertRaisesRegex(gl.LoginError, "没有被 git 忽略"):
            gl.read_credentials(os.path.join(gl.ROOT, "tools", "credentials-not-ignored.txt"))

    def test_default_credentials_file_is_git_ignored(self):
        self.assertTrue(gl.git_ignored(gl.DEFAULT_CREDENTIALS))


if __name__ == "__main__":
    unittest.main()
