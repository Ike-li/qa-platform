"""Tests for app/utils/git.py — build_clone_url utility."""

from app.utils.git import build_clone_url


class TestBuildCloneUrl:
    def test_https_with_credential(self):
        url = build_clone_url("https://github.com/user/repo.git", "mytoken")
        assert url == "https://mytoken@github.com/user/repo.git"

    def test_https_without_credential(self):
        url = build_clone_url("https://github.com/user/repo.git", None)
        assert url == "https://github.com/user/repo.git"

    def test_https_with_empty_credential(self):
        url = build_clone_url("https://github.com/user/repo.git", "")
        assert url == "https://github.com/user/repo.git"

    def test_non_https_returns_original(self):
        url = build_clone_url("git://github.com/user/repo.git", "tok")
        assert url == "git://github.com/user/repo.git"

    def test_ssh_returns_original(self):
        url = build_clone_url("git@github.com:user/repo.git", "tok")
        assert url == "git@github.com:user/repo.git"

    def test_https_with_port_and_credential(self):
        url = build_clone_url("https://ghe.company.com:8443/team/repo.git", "pat123")
        assert url == "https://pat123@ghe.company.com:8443/team/repo.git"

    def test_https_with_port_no_credential(self):
        url = build_clone_url("https://ghe.company.com:8443/team/repo.git", None)
        assert url == "https://ghe.company.com:8443/team/repo.git"

    def test_credential_with_special_chars(self):
        url = build_clone_url("https://github.com/u/r.git", "token:with@colon")
        # The credential is placed before @hostname — special chars are part of
        # the userinfo segment
        assert url.startswith("https://token:with@colon@github.com")

    def test_no_path(self):
        url = build_clone_url("https://github.com/", "tok")
        assert url == "https://tok@github.com/"

    def test_long_credential(self):
        long_token = "ghp_" + "a" * 40
        url = build_clone_url("https://github.com/user/repo.git", long_token)
        assert url == f"https://{long_token}@github.com/user/repo.git"
