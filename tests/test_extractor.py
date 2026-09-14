"""تست استخراج، Deduplication و طبقه‌بندی لینک (بخش ششم)."""
from __future__ import annotations


from app.db.models import LinkKind
from app.eitaa.extractor import classify, deduplicate, find_links


class TestFindLinks:
    def test_extracts_from_persian_text(self) -> None:
        text = (
            "سلام 👋 به گروه ما بپیوندید https://eitaa.com/mygroup\n"
            "کانال دوم: eitaa.com/second_channel\n"
            "این هم لینک دعوت https://eitaa.com/joinchat/AAAA1111"
        )
        links = find_links(text)
        assert "https://eitaa.com/mygroup" in links
        assert "https://eitaa.com/second_channel" in links
        assert "https://eitaa.com/joinchat/AAAA1111" in links

    def test_ignores_other_messengers(self) -> None:
        text = "https://t.me/foo https://instagram.com/bar https://example.com/baz"
        assert find_links(text) == []

    def test_empty_input(self) -> None:
        assert find_links("") == []
        assert find_links(None) == []  # type: ignore[arg-type]


class TestClassify:
    def test_invite_links_are_certain(self) -> None:
        assert classify("https://eitaa.com/joinchat/ABC123") is LinkKind.INVITE
        assert classify("https://eitaa.com/+XYZ789") is LinkKind.INVITE

    def test_plain_username_is_unknown_not_guessed(self) -> None:
        """طبق بخش ۶: بدون منبع قطعی، حدس ممنوع است."""
        assert classify("https://eitaa.com/somechannel") is LinkKind.UNKNOWN

    def test_reserved_paths_are_unknown(self) -> None:
        assert classify("https://eitaa.com/about") is LinkKind.UNKNOWN
        assert classify("https://eitaa.com/faq") is LinkKind.UNKNOWN


class TestDeduplicate:
    def test_removes_duplicates_preserving_order(self) -> None:
        urls = [
            "https://eitaa.com/a",
            "https://eitaa.com/b",
            "https://eitaa.com/a",
            "https://eitaa.com/c",
        ]
        unique, duplicates = deduplicate(urls)
        assert unique == [
            "https://eitaa.com/a",
            "https://eitaa.com/b",
            "https://eitaa.com/c",
        ]
        assert duplicates == 1

    def test_case_and_slash_insensitive(self) -> None:
        unique, duplicates = deduplicate(
            ["https://eitaa.com/Group", "https://eitaa.com/group/", "https://eitaa.com/GROUP"]
        )
        assert len(unique) == 1
        assert duplicates == 2

    def test_no_duplicates(self) -> None:
        urls = ["https://eitaa.com/x", "https://eitaa.com/y"]
        unique, duplicates = deduplicate(urls)
        assert len(unique) == 2 and duplicates == 0

    def test_empty(self) -> None:
        assert deduplicate([]) == ([], 0)


class TestExtractionStats:
    def test_joinable_counts_only_certain_kinds(self) -> None:
        from app.eitaa.extractor import ExtractionStats

        stats = ExtractionStats()
        stats.by_kind = {
            LinkKind.GROUP: 5,
            LinkKind.INVITE: 3,
            LinkKind.UNKNOWN: 100,   # نباید شمرده شود
            LinkKind.USER: 7,        # کاربر برای join گروه استفاده نمی‌شود
        }
        assert stats.joinable == 8
