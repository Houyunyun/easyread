import base64
import hashlib
import io
import os
import stat
import struct
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from easyread.app import config, qa_skills


def skill(name="paper-helper", description="Read the original paper.", body="Use local references."):
    return f"---\nname: {name}\ndescription: {description}\n---\n{body}\n".encode("utf-8")


def encoded(data):
    return base64.b64encode(data).decode("ascii")


def archive(entries, compression=zipfile.ZIP_DEFLATED):
    buffer = io.BytesIO()
    with warnings.catch_warnings(), zipfile.ZipFile(buffer, "w", compression=compression) as output:
        warnings.simplefilter("ignore", UserWarning)
        for name, content, mode in entries:
            info = zipfile.ZipInfo(name)
            info.create_system = 3
            info.external_attr = mode << 16
            info.compress_type = compression
            output.writestr(info, content)
    return buffer.getvalue()


def regular(name, content):
    return name, content, stat.S_IFREG | 0o644


class QaSkillsTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        # Resolve the fixture base for platforms whose system temp path is a link.
        self.base = Path(self.temporary.name).resolve()
        self.home = self.base / "home"
        self.home.mkdir()
        self.data = self.base / "easyread"
        self.addCleanup(patch.stopall)
        patch.dict(os.environ, {"HOME": str(self.home), "USERPROFILE": str(self.home),
                                "EASYREAD_HOME": str(self.data), "CODEX_HOME": ""}).start()
        patch.object(config, "HOME", self.data).start()

    def native(self, engine, folder, content=None, root=None):
        root = root or self.home / (".claude" if engine == "claude" else ".codex") / "skills"
        path = root / folder / "SKILL.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content if content is not None else skill(folder))
        return path

    def import_plain(self, engine="claude", content=None):
        return qa_skills.import_skill(engine, "SKILL.md", encoded(content if content is not None else skill()))

    def import_zip(self, entries, engine="claude"):
        return qa_skills.import_skill(engine, "bundle.zip", encoded(archive(entries)))

    def assert_no_managed_files(self):
        root = self.data / "qa-skills"
        self.assertFalse(root.exists() and any(p.is_file() or p.is_symlink() for p in root.rglob("*")))
        if root.exists():
            self.assertFalse(any(p.name.startswith(".import-") for p in root.rglob("*")))

    def symlink(self, link, target, directory=False):
        link.parent.mkdir(parents=True, exist_ok=True)
        try:
            link.symlink_to(target, target_is_directory=directory)
        except (OSError, NotImplementedError):
            self.skipTest("Symlinks unavailable")

    def test_plain_import_metadata_only_stable_resolve_and_engine_isolation(self):
        item = self.import_plain()
        expected = self.data / "qa-skills" / "claude" / "paper-helper" / "SKILL.md"
        self.assertEqual(item, {"id": "managed:paper-helper", "name": "paper-helper",
                                "description": "Read the original paper.", "path": str(expected), "managed": True})
        self.assertEqual(expected.read_bytes(), skill())
        self.assertEqual(qa_skills.resolve("claude", item["id"]), expected)
        self.assertEqual(qa_skills.inventory("claude"), [item])
        self.assertEqual(qa_skills.inventory("codex"), [])
        self.assertEqual(list(self.home.iterdir()), [])
        second = self.import_plain("codex")
        self.assertEqual(second["id"], item["id"])
        self.assertNotEqual(second["path"], item["path"])
        expected.unlink()
        with self.assertRaises(ValueError):
            qa_skills.resolve("claude", item["id"])

    def test_zip_multifile_wrapped_and_flat_and_script_never_executed(self):
        for index, prefix in enumerate(("exported/", "")):
            with self.subTest(prefix=prefix):
                name = f"bundle-{index}"
                script = f"from pathlib import Path\nPath({str(self.base / 'executed')!r}).touch()\n".encode()
                entries = [regular(prefix + "SKILL.md", skill(name)),
                           regular(prefix + "references/guide.md", b"# Reference\n"),
                           regular(prefix + "agents/openai.yaml", b"interface:\n  display_name: Paper\n"),
                           regular(prefix + "assets/icon.png", b"\x89PNG\r\n\x1a\nfixture"),
                           regular(prefix + "references/paper.pdf", b"%PDF-1.7\nfixture"),
                           (prefix + "scripts/check.py", script, stat.S_IFREG | 0o755),
                           (prefix + "scripts/", b"", stat.S_IFDIR | 0o755)]
                if prefix:
                    entries.append((prefix, b"", stat.S_IFDIR | 0o755))
                item = self.import_zip(entries)
                folder = Path(item["path"]).parent
                self.assertEqual((folder / "scripts/check.py").read_bytes(), script)
                self.assertEqual((folder / "references/guide.md").read_bytes(), b"# Reference\n")
                self.assertEqual((folder / "assets/icon.png").read_bytes(), b"\x89PNG\r\n\x1a\nfixture")
                self.assertEqual((folder / "agents/openai.yaml").read_bytes(), b"interface:\n  display_name: Paper\n")
                if os.name != "nt":
                    self.assertEqual((folder / "scripts/check.py").stat().st_mode & 0o111, 0o111)
                self.assertFalse((self.base / "executed").exists())

    def test_conflict_preserves_prior_plain_and_zip_and_casefold(self):
        first = self.import_plain()
        before = Path(first["path"]).read_bytes()
        for filename, content in [("SKILL.md", skill(body="Changed")),
                                  ("changed.zip", archive([regular("SKILL.md", skill(body="Changed"))]))]:
            with self.assertRaisesRegex(ValueError, "already exists"):
                qa_skills.import_skill("claude", filename, encoded(content))
            self.assertEqual(Path(first["path"]).read_bytes(), before)
        root = self.data / "qa-skills" / "claude"
        (root / "OTHER").mkdir()
        with self.assertRaisesRegex(ValueError, "already exists"):
            self.import_plain(content=skill("other"))
        self.assertFalse(any(p.name.startswith(".import-") for p in root.iterdir()))

    def test_native_metadata_name_and_folder_conflicts_never_written(self):
        path = self.native("claude", "Different-Folder", skill("paper-helper"))
        before = (path.read_bytes(), path.stat().st_mtime_ns, path.stat().st_mode)
        for name in ("paper-helper", "different-folder"):
            with self.assertRaisesRegex(ValueError, "already exists"):
                self.import_plain(content=skill(name))
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns, path.stat().st_mode), before)
        self.assert_no_managed_files()

    def test_invalid_native_metadata_still_reserves_native_folder_name(self):
        self.native("claude", "paper-helper", b"no metadata")
        with self.assertRaisesRegex(ValueError, "already exists"):
            self.import_plain()
        self.assert_no_managed_files()

    def test_native_inventory_read_only_bounded_and_metadata_only(self):
        valid = self.native("claude", "local", skill("local", "本地论文笔记"))
        before = (valid.read_bytes(), valid.stat().st_mtime_ns, valid.stat().st_mode)
        self.native("claude", ".system", skill("internal"))
        self.native("claude", ".system/nested", skill("nested"))
        self.native("claude", "bad", b"No frontmatter")
        self.native("claude", "large", skill("large") + b"x" * qa_skills.MAX_SKILL_BYTES)
        self.native("claude", "invalid-utf8", b"\xff")
        self.native("claude", "parent/nested", skill("nested"))
        self.native("codex", "other-engine")
        items = qa_skills.inventory("claude")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["description"], "本地论文笔记")
        self.assertFalse(items[0]["managed"])
        self.assertEqual(items[0]["id"], "native:" + hashlib.sha256(str(valid.resolve()).encode()).hexdigest()[:16])
        self.assertEqual(qa_skills.resolve("claude", items[0]["id"]), valid)
        self.assertEqual((valid.read_bytes(), valid.stat().st_mtime_ns, valid.stat().st_mode), before)
        self.assertFalse(self.data.exists())
        with patch.object(qa_skills, "MAX_ROOT_ENTRIES", 1), patch.object(qa_skills, "_read_metadata", wraps=qa_skills._read_metadata) as read:
            self.assertLessEqual(len(qa_skills.inventory("claude")), 1)
            self.assertLessEqual(read.call_count, 1)
        with patch.object(qa_skills, "MAX_ROOT_ENTRIES", 1):
            with self.assertRaisesRegex(ValueError, "too large"):
                self.import_plain()

    def test_codex_native_roots_override_and_deduplication(self):
        agents = self.home / ".agents" / "skills"
        first = self.native("codex", "shared", root=agents)
        default = self.native("codex", "default")
        self.assertEqual({item["path"] for item in qa_skills.inventory("codex")}, {str(first), str(default)})
        custom = self.base / "custom-codex"
        second = self.native("codex", "custom", root=custom / "skills")
        with patch.dict(os.environ, {"CODEX_HOME": str(custom)}):
            self.assertEqual({item["path"] for item in qa_skills.inventory("codex")}, {str(first), str(second)})
        with patch.dict(os.environ, {"CODEX_HOME": str(self.home / ".agents")}):
            self.assertEqual(len(qa_skills.inventory("codex")), 1)
        self.assertEqual(qa_skills.inventory("claude"), [])

    def test_missing_roots_inventory_and_resolve_do_not_create_anything(self):
        for engine in ("claude", "codex"):
            self.assertEqual(qa_skills.inventory(engine), [])
            for identifier in ("managed:missing", "/etc/passwd", "../SKILL.md", "native:missing"):
                with self.assertRaises(ValueError):
                    qa_skills.resolve(engine, identifier)
        self.assertFalse(self.data.exists())
        self.assertEqual(list(self.home.iterdir()), [])

    def test_engine_validation_for_all_public_functions(self):
        for engine in ("openai", "Claude", "", "../codex", None, []):
            with self.subTest(engine=engine):
                for operation in (lambda: qa_skills.inventory(engine),
                                  lambda: qa_skills.resolve(engine, "missing"),
                                  lambda: self.import_plain(engine)):
                    with self.assertRaises(ValueError):
                        operation()
        self.assert_no_managed_files()

    def test_valid_quoted_and_block_metadata(self):
        for i, description in enumerate(('"A quoted description"', "'Another description'", ">-\n  Read the paper\n  then verify it.", "|\n  First line\n  Second line")):
            item = self.import_plain(content=skill(f"valid-{i}", description))
            self.assertNotIn("description:", item["description"])
            self.assertTrue(item["description"])
        long_name = "n" * 64
        self.assertEqual(self.import_plain(content=skill(long_name))["name"], long_name)

    def test_invalid_frontmatter_and_utf8_are_rejected_before_writes(self):
        invalid = [b"# No metadata", b"---\nname: a\ndescription: missing end\n",
                   b"---\nname: a\n---\n", b"---\ndescription: missing name\n---\n",
                   b"---\nname: a\nname: b\ndescription: duplicate\n---\n", b"\xff",
                   skill(description=""), skill(description="[]"), skill(description="{}"),
                   skill(description="null"), skill(description="true"), skill(description="!tag value"),
                   skill(description="'unfinished"), skill(description="|"), skill(description="\x00binary"),
                   skill(description="good\ndescription: repeated")]
        invalid.extend(skill(name) for name in ("../escape", "Uppercase", "with space", "", "a" * 65, "-start", ".system", "con", "lpt1"))
        for content in invalid:
            with self.subTest(content=content[:80]):
                with self.assertRaises(ValueError):
                    self.import_plain(content=content)
                with self.assertRaises(ValueError):
                    self.import_zip([regular("SKILL.md", content)])
                self.assert_no_managed_files()

    def test_filename_base64_and_upload_size_validation(self):
        for filename in ("notes.md", "skill.md", "../SKILL.md", "../a.zip", "a\\b.zip", "C:a.zip", None):
            with self.subTest(filename=filename), self.assertRaises(ValueError):
                qa_skills.import_skill("claude", filename, encoded(skill()))
        for content in ("!invalid!", "a", "é", None, b"bytes", encoded(skill()) + "\n"):
            with self.subTest(content=content), self.assertRaises(ValueError):
                qa_skills.import_skill("claude", "SKILL.md", content)
        with self.assertRaisesRegex(ValueError, "5 MiB"):
            qa_skills.import_skill("claude", "large.zip", encoded(b"x" * (qa_skills.MAX_UPLOAD_BYTES + 1)))
        self.assert_no_managed_files()

    def test_skill_markdown_limit_plain_and_zip(self):
        content = skill() + b"x" * qa_skills.MAX_SKILL_BYTES
        for operation in (lambda: self.import_plain(content=content),
                          lambda: self.import_zip([regular("SKILL.md", content)])):
            with self.assertRaises(ValueError):
                operation()
        self.assert_no_managed_files()

    def test_zip_unsafe_paths(self):
        for path in ("../outside.txt", "/outside.txt", "C:/outside.txt", "C:outside.txt", "scripts\\bad.py",
                     "scripts/../../outside.txt", "scripts//bad.py", "scripts/./bad.py", "scripts/a:stream.py",
                     "scripts/NUL.py", "scripts/space .py ", "scripts/name./x.py", "scripts/bad\x01.py"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.import_zip([regular("SKILL.md", skill()), regular(path, b"safe")])
        self.assert_no_managed_files()
        self.assertFalse((self.base / "outside.txt").exists())

    def test_zip_duplicate_casefold_and_file_directory_collisions(self):
        for extras in ([regular("SKILL.md", skill())],
                       [regular("references/a.md", b"a"), regular("references/a.md", b"b")],
                       [regular("references/A.md", b"a"), regular("references/a.md", b"b")],
                       [regular("references/a.md", b"a"), regular("References/b.md", b"b")],
                       [regular("references/a.md", b"a"), regular("references/a.md/child.md", b"b")],
                       [("references/", b"", stat.S_IFDIR), ("references/", b"", stat.S_IFDIR)]):
            with self.subTest(extras=extras), self.assertRaises(ValueError):
                self.import_zip([regular("SKILL.md", skill()), *extras])
        self.assert_no_managed_files()

    def test_zip_symlinks_special_files_and_elevated_modes(self):
        for mode in (stat.S_IFLNK | 0o777, stat.S_IFIFO | 0o644, stat.S_IFCHR | 0o600,
                     stat.S_IFBLK | 0o600, stat.S_IFSOCK | 0o600,
                     stat.S_IFREG | 0o4755, stat.S_IFREG | 0o2755, stat.S_IFREG | 0o1755):
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                self.import_zip([regular("SKILL.md", skill()), ("scripts/run.py", b"print('no')", mode)])
        self.assert_no_managed_files()

    def test_zip_unsupported_types_and_binary_disguised_as_text(self):
        for filename, content in (("scripts/program.exe", b"MZ"), ("assets/nested.zip", b"PK"),
                                  ("assets/plugin.so", b"\x7fELF"), ("scripts/run.py", b"\x7fELF\x00"),
                                  ("references/note.md", b"\xff\x00"), ("assets/icon.png", b"MZbinary"),
                                  ("assets/icon.webp", b"RIFFnot-a-webp"), ("assets/run.py", b"print('no')"),
                                  ("unexpected.txt", b"no")):
            with self.subTest(filename=filename), self.assertRaises(ValueError):
                self.import_zip([regular("SKILL.md", skill()), regular(filename, content)])
        self.assert_no_managed_files()

    def test_zip_requires_exactly_one_skill_and_no_unrelated_directories(self):
        for entries in ([], [regular("references/a.md", b"no skill")],
                        [regular("one/SKILL.md", skill()), regular("two/SKILL.md", skill("two"))],
                        [regular("one/SKILL.md", skill()), regular("two/references/a.md", b"other")],
                        [regular("one/nested/SKILL.md", skill())],
                        [regular("SKILL.md", skill()), ("unrelated/", b"", stat.S_IFDIR)]):
            with self.subTest(entries=entries), self.assertRaises(ValueError):
                self.import_zip(entries)
        self.assert_no_managed_files()

    def test_zip_count_expansion_and_compression_bomb_limits(self):
        limits = [archive([regular("SKILL.md", skill()),
                           *(regular(f"references/{i}.md", b"doc") for i in range(qa_skills.MAX_FILES))]),
                  archive([regular("SKILL.md", skill()),
                           regular("references/huge.md", b"x" * (qa_skills.MAX_EXPANDED_BYTES + 1))]),
                  archive([regular("SKILL.md", skill()), regular("references/bomb.md", b"x" * (1024 * 1024))]),
                  archive([regular("SKILL.md", skill()),
                           *((f"references/{i}/", b"", stat.S_IFDIR) for i in range(qa_skills.MAX_FILES * 2))])]
        for data in limits:
            with self.subTest(size=len(data)), self.assertRaises(ValueError):
                qa_skills.import_skill("claude", "bad.zip", encoded(data))
        self.assert_no_managed_files()

    def test_zip_corrupt_encrypted_and_unsupported_compression(self):
        encrypted = bytearray(archive([regular("SKILL.md", skill())]))
        struct.pack_into("<H", encrypted, 6, 1)
        central = encrypted.index(b"PK\x01\x02")
        struct.pack_into("<H", encrypted, central + 8, 1)
        bad_crc = bytearray(archive([regular("SKILL.md", skill())], zipfile.ZIP_STORED))
        offset = bad_crc.index(b"---")
        bad_crc[offset] = ord("!")
        unsupported = bytearray(archive([regular("SKILL.md", skill())]))
        struct.pack_into("<H", unsupported, 8, 99)
        struct.pack_into("<H", unsupported, unsupported.index(b"PK\x01\x02") + 10, 99)
        for data in (b"not a zip", bytes(encrypted), bytes(bad_crc), bytes(unsupported)):
            with self.subTest(data=data[:20]), self.assertRaises(ValueError):
                qa_skills.import_skill("claude", "bad.zip", encoded(data))
        self.assert_no_managed_files()

    def test_native_symlink_roots_children_and_markdown_are_not_followed(self):
        outside = self.base / "outside"
        target = self.native("claude", "real", root=outside)
        root = self.home / ".claude" / "skills"
        self.symlink(root, outside, directory=True)
        self.assertEqual(qa_skills.inventory("claude"), [])
        root.unlink()
        root.mkdir()
        self.symlink(root / "linked", target.parent, directory=True)
        self.symlink(root / "file-link" / "SKILL.md", target)
        self.assertEqual(qa_skills.inventory("claude"), [])
        self.assertEqual(target.read_bytes(), skill("real"))

    def test_managed_symlink_root_and_parent_escape_rejected(self):
        outside = self.base / "outside"
        outside.mkdir()
        for link in (self.data, self.data / "qa-skills", self.data / "qa-skills" / "claude"):
            with self.subTest(link=link):
                self.symlink(link, outside, directory=True)
                with self.assertRaises(ValueError):
                    self.import_plain()
                self.assertEqual(qa_skills.inventory("claude"), [])
                self.assertEqual(list(outside.iterdir()), [])
                link.unlink()

    def test_windows_junction_directory_mode_is_not_treated_as_safe(self):
        junction = SimpleNamespace(st_mode=stat.S_IFDIR | 0o755, st_file_attributes=0x400)
        with patch.object(Path, "lstat", return_value=junction):
            with self.assertRaises(ValueError):
                qa_skills._safe_chain(self.data)

    def test_managed_existing_symlink_is_not_overwritten_or_resolved(self):
        outside = self.base / "outside"
        outside.mkdir()
        root = self.data / "qa-skills" / "claude"
        self.symlink(root / "paper-helper", outside, directory=True)
        with self.assertRaises(ValueError):
            self.import_plain()
        self.assertTrue((root / "paper-helper").is_symlink())
        self.assertEqual(list(outside.iterdir()), [])
        self.assertEqual(qa_skills.inventory("claude"), [])

    def test_managed_root_cannot_be_under_either_native_discovery_root(self):
        for root in (self.home / ".claude" / "skills", self.home / ".agents" / "skills", self.home / ".codex" / "skills"):
            with self.subTest(root=root), patch.object(config, "HOME", root):
                with self.assertRaisesRegex(ValueError, "outside native"):
                    self.import_plain()
                self.assertFalse(root.exists())
        with patch.dict(os.environ, {"CODEX_HOME": str(self.data / "qa-skills" / "claude")}):
            with self.assertRaisesRegex(ValueError, "outside native"):
                self.import_plain()
        self.assert_no_managed_files()

    def test_publish_failure_cleans_temporary_directory_and_lock(self):
        with patch.object(Path, "rename", side_effect=OSError("simulated disk error")):
            with self.assertRaisesRegex(OSError, "simulated"):
                self.import_plain()
        self.assertEqual(list((self.data / "qa-skills" / "claude").iterdir()), [])
        self.assertEqual(self.import_plain()["id"], "managed:paper-helper")

    def test_existing_import_lock_fails_without_removing_other_importers_lock(self):
        lock = self.data / "qa-skills" / "claude" / ".import-lock"
        lock.mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, "in progress"):
            self.import_plain()
        self.assertTrue(lock.is_dir())
        self.assertEqual(list(lock.parent.iterdir()), [lock])

    def test_exact_markdown_and_file_count_limits_are_accepted(self):
        content = skill("exact-size")
        content += b"x" * (qa_skills.MAX_SKILL_BYTES - len(content))
        item = self.import_plain(content=content)
        self.assertEqual(Path(item["path"]).stat().st_size, qa_skills.MAX_SKILL_BYTES)
        entries = [regular("SKILL.md", skill("exact-count"))]
        entries.extend(regular(f"references/{i}.md", b"doc") for i in range(qa_skills.MAX_FILES - 1))
        item = self.import_zip(entries)
        self.assertEqual(sum(p.is_file() for p in Path(item["path"]).parent.rglob("*")), qa_skills.MAX_FILES)

    def test_import_preserves_unrelated_configuration_files(self):
        self.data.mkdir()
        configuration = self.data / "config.json"
        configuration.write_bytes(b'{"qa_policy": "unchanged"}')
        before = (configuration.read_bytes(), configuration.stat().st_mtime_ns)
        self.import_plain()
        self.assertEqual((configuration.read_bytes(), configuration.stat().st_mtime_ns), before)
        self.assertEqual({p.name for p in self.data.iterdir()}, {"config.json", "qa-skills"})

    def test_resolve_rejects_replaced_symlink_and_unlisted_managed_directory(self):
        item = self.import_plain()
        path = Path(item["path"])
        path.unlink()
        native = self.native("claude", "native")
        self.symlink(path, native)
        with self.assertRaises(ValueError):
            qa_skills.resolve("claude", item["id"])
        mismatch = self.data / "qa-skills" / "claude" / "mismatched" / "SKILL.md"
        mismatch.parent.mkdir()
        mismatch.write_bytes(skill("another-name"))
        with self.assertRaises(ValueError):
            qa_skills.resolve("claude", "managed:mismatched")

    def test_zip_nul_and_deep_paths_are_rejected(self):
        data = archive([regular("SKILL.md", skill()), regular("references/badX.md", b"bad")])
        data = data.replace(b"references/badX.md", b"references/bad\x00.md")
        with self.assertRaises(ValueError):
            qa_skills.import_skill("claude", "bad.zip", encoded(data))
        with self.assertRaises(ValueError):
            self.import_zip([regular("SKILL.md", skill()), regular("references/" + "a/" * 20 + "b.md", b"bad")])
        self.assert_no_managed_files()

    def test_conflict_appearing_during_import_is_not_overwritten(self):
        check = qa_skills._check_conflicts
        count = 0
        conflict = self.data / "qa-skills" / "claude" / "paper-helper"

        def introduce_conflict(engine, root, name):
            nonlocal count
            count += 1
            if count == 3:
                conflict.mkdir()
                (conflict / "keep.txt").write_bytes(b"untouched")
            check(engine, root, name)

        with patch.object(qa_skills, "_check_conflicts", side_effect=introduce_conflict):
            with self.assertRaisesRegex(ValueError, "already exists"):
                self.import_plain()
        self.assertEqual((conflict / "keep.txt").read_bytes(), b"untouched")
        self.assertEqual(list(conflict.parent.iterdir()), [conflict])

    def test_corrupt_deflate_stream_is_validation_error(self):
        data = bytearray(archive([regular("SKILL.md", skill())]))
        name_length, extra_length = struct.unpack_from("<HH", data, 26)
        # Reserved DEFLATE block type must fail during bounded decompression.
        data[30 + name_length + extra_length] = 7
        with self.assertRaises(ValueError):
            qa_skills.import_skill("claude", "bad.zip", encoded(data))
        self.assert_no_managed_files()

    def test_all_files_validated_before_any_publish(self):
        with self.assertRaises(ValueError):
            self.import_zip([regular("SKILL.md", skill()), regular("references/good.md", b"valid"),
                             regular("scripts/bad.exe", b"MZ")])
        self.assertFalse(self.data.exists())


if __name__ == "__main__":
    unittest.main()
