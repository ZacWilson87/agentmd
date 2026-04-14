"""Tests for the trust module."""

import pytest
from pathlib import Path

from agentmd.trust import (
    TRUST_FILENAME,
    compute_hash,
    trust_file,
    untrust_file,
    verify,
    verify_all_skills,
)


SKILL_CONTENT = """\
---
agentmd: "1.0"
type: skill
id: my-skill
version: "1.0"
description: "A skill"
trigger: "do the thing"
---
"""


class TestComputeHash:
    def test_consistent(self, tmp_path):
        f = tmp_path / "file.txt"
        f.write_text("hello")
        h1 = compute_hash(f)
        h2 = compute_hash(f)
        assert h1 == h2

    def test_different_content_different_hash(self, tmp_path):
        a = tmp_path / "a.txt"
        b = tmp_path / "b.txt"
        a.write_text("hello")
        b.write_text("world")
        assert compute_hash(a) != compute_hash(b)

    def test_sha256_length(self, tmp_path):
        f = tmp_path / "f.txt"
        f.write_text("data")
        assert len(compute_hash(f)) == 64  # SHA-256 hex = 64 chars


class TestVerify:
    def test_new_file_not_in_store(self, tmp_path):
        f = tmp_path / "skill.skill.md"
        f.write_text(SKILL_CONTENT)
        result = verify(f, root=tmp_path)
        assert result.status == "new"
        assert result.stored_hash is None

    def test_trusted_after_trust_file(self, tmp_path):
        f = tmp_path / "skill.skill.md"
        f.write_text(SKILL_CONTENT)
        trust_file(f, root=tmp_path)
        result = verify(f, root=tmp_path)
        assert result.status == "trusted"

    def test_changed_after_modification(self, tmp_path):
        f = tmp_path / "skill.skill.md"
        f.write_text(SKILL_CONTENT)
        trust_file(f, root=tmp_path)
        f.write_text(SKILL_CONTENT + "\n# Extra line added by PR\n")
        result = verify(f, root=tmp_path)
        assert result.status == "changed"

    def test_missing_file(self, tmp_path):
        f = tmp_path / "nonexistent.skill.md"
        result = verify(f, root=tmp_path)
        assert result.status == "missing"


class TestTrustFile:
    def test_creates_trust_store(self, tmp_path):
        f = tmp_path / "my.skill.md"
        f.write_text(SKILL_CONTENT)
        trust_file(f, root=tmp_path)
        assert (tmp_path / TRUST_FILENAME).exists()

    def test_records_hash(self, tmp_path):
        f = tmp_path / "my.skill.md"
        f.write_text(SKILL_CONTENT)
        result = trust_file(f, root=tmp_path)
        assert result.status == "trusted"
        assert result.current_hash == compute_hash(f)
        assert result.trusted_at is not None

    def test_re_trusting_updates_hash(self, tmp_path):
        f = tmp_path / "my.skill.md"
        f.write_text(SKILL_CONTENT)
        trust_file(f, root=tmp_path)
        f.write_text(SKILL_CONTENT + "\n## Updated\n")
        result = trust_file(f, root=tmp_path)
        assert result.status == "trusted"
        assert result.current_hash == compute_hash(f)

    def test_raises_for_missing_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            trust_file(tmp_path / "nonexistent.skill.md", root=tmp_path)


class TestUntrustFile:
    def test_removes_entry(self, tmp_path):
        f = tmp_path / "my.skill.md"
        f.write_text(SKILL_CONTENT)
        trust_file(f, root=tmp_path)
        removed = untrust_file(f, root=tmp_path)
        assert removed is True
        result = verify(f, root=tmp_path)
        assert result.status == "new"

    def test_returns_false_if_not_present(self, tmp_path):
        f = tmp_path / "my.skill.md"
        f.write_text(SKILL_CONTENT)
        removed = untrust_file(f, root=tmp_path)
        assert removed is False


class TestVerifyAllSkills:
    def test_finds_skill_files(self, tmp_path):
        (tmp_path / "skills").mkdir()
        (tmp_path / "skills" / "my-skill.skill.md").write_text(SKILL_CONTENT)
        # Also add an AGENTS.md so parse_file can validate context
        (tmp_path / "AGENTS.md").write_text(
            "---\nagentmd: '1.0'\ntype: agents\nname: X\n---\n"
        )
        results = verify_all_skills(tmp_path)
        assert len(results) == 1
        assert results[0].status == "new"

    def test_empty_repo(self, tmp_path):
        results = verify_all_skills(tmp_path)
        assert results == []
