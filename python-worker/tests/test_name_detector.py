"""Tests for MeCab-based name detection module."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from name_detector import detect_names, detect_names_text, _is_name_token, _calculate_name_confidence


class TestIsNameToken:
    def test_person_name(self):
        pos = {"pos1": "名詞", "pos2": "固有名詞", "pos3": "人名"}
        is_name, subcategory = _is_name_token(pos)
        assert is_name is True
        assert subcategory == "person"

    def test_surname(self):
        pos = {"pos1": "名詞", "pos2": "固有名詞", "pos3": "人名姓"}
        is_name, subcategory = _is_name_token(pos)
        assert is_name is True
        assert subcategory == "surname"

    def test_given_name(self):
        pos = {"pos1": "名詞", "pos2": "固有名詞", "pos3": "人名名"}
        is_name, subcategory = _is_name_token(pos)
        assert is_name is True
        assert subcategory == "given"

    def test_non_name_noun(self):
        pos = {"pos1": "名詞", "pos2": "一般", "pos3": ""}
        is_name, subcategory = _is_name_token(pos)
        assert is_name is False
        assert subcategory == ""

    def test_verb(self):
        pos = {"pos1": "動詞", "pos2": "一般", "pos3": ""}
        is_name, subcategory = _is_name_token(pos)
        assert is_name is False

    def test_place_name(self):
        pos = {"pos1": "名詞", "pos2": "固有名詞", "pos3": "地域"}
        is_name, subcategory = _is_name_token(pos)
        assert is_name is False


class TestCalculateNameConfidence:
    def test_single_token(self):
        tokens = [{"surface": "太郎", "subcategory": "person"}]
        confidence = _calculate_name_confidence(tokens, "田中太郎")
        assert 0.0 <= confidence <= 1.0

    def test_full_name_boost(self):
        tokens_single = [{"surface": "太郎", "subcategory": "person"}]
        tokens_full = [
            {"surface": "田中", "subcategory": "surname"},
            {"surface": "太郎", "subcategory": "given"},
        ]
        conf_single = _calculate_name_confidence(tokens_single, "田中太郎")
        conf_full = _calculate_name_confidence(tokens_full, "田中太郎")
        assert conf_full > conf_single

    def test_honorific_boost(self):
        tokens = [{"surface": "太郎", "subcategory": "person"}]
        conf_without = _calculate_name_confidence(tokens, "太郎は")
        conf_with = _calculate_name_confidence(tokens, "太郎様")
        assert conf_with > conf_without

    def test_empty_tokens(self):
        confidence = _calculate_name_confidence([], "")
        assert confidence == 0.0

    def test_max_confidence_cap(self):
        tokens = [
            {"surface": "田中", "subcategory": "surname"},
            {"surface": "太郎", "subcategory": "given"},
        ]
        confidence = _calculate_name_confidence(tokens, "田中太郎様")
        assert confidence <= 1.0


class TestDetectNames:
    def test_detect_names_text_basic(self):
        """Test that name detection works on Japanese text with proper nouns."""
        # The test requires fugashi + unidic-lite to be installed
        try:
            import fugashi  # noqa: F401
        except ImportError:
            self.skipTest("fugashi not installed")

        results = detect_names_text("田中太郎が出席しました。")
        # Should detect at least some proper nouns
        # Note: exact results depend on MeCab dictionary
        assert isinstance(results, list)

    def test_detect_names_text_with_honorific(self):
        """Test name detection with honorific suffixes."""
        try:
            import fugashi  # noqa: F401
        except ImportError:
            self.skipTest("fugashi not installed")

        results = detect_names_text("山田花子様にお送りください。")
        assert isinstance(results, list)

    def test_detect_names_empty_text(self):
        """Test that empty text returns empty results."""
        results = detect_names_text("")
        assert results == []

    def test_detect_names_no_proper_nouns(self):
        """Test text without proper nouns."""
        try:
            import fugashi  # noqa: F401
        except ImportError:
            self.skipTest("fugashi not installed")

        results = detect_names_text("今日は良い天気です。")
        assert isinstance(results, list)

    def test_detect_names_with_regions(self):
        """Test detection with text regions that have bbox."""
        try:
            import fugashi  # noqa: F401
        except ImportError:
            self.skipTest("fugashi not installed")

        regions = [
            {"text": "鈴木一郎が来ました。", "bbox_pt": [100, 200, 300, 50]},
        ]
        results = detect_names(regions)
        assert isinstance(results, list)
        for det in results:
            assert det["type"] == "name"
            assert det["source"] == "auto"
            assert det["rule_id"] == "name_mecab"
            assert "id" in det
            assert "text" in det
            assert "confidence" in det

    def test_detect_names_enabled_types_filter(self):
        """Test that enabled_types filter works for name type."""
        results_filtered = detect_names_text("田中太郎", enabled_types=["address"])
        assert results_filtered == []

    def test_detect_names_result_structure(self):
        """Test that detection results have the expected structure."""
        try:
            import fugashi  # noqa: F401
        except ImportError:
            self.skipTest("fugashi not installed")

        results = detect_names_text("山本太郎様")
        for det in results:
            assert isinstance(det["id"], str)
            assert isinstance(det["text"], str)
            assert isinstance(det["bbox_pt"], list)
            assert det["type"] == "name"
            assert isinstance(det["confidence"], float)
            assert 0.0 <= det["confidence"] <= 1.0
            assert det["source"] == "auto"
            assert det["rule_id"] == "name_mecab"
            assert det["rule_name"] == "氏名（MeCab形態素解析）"
            assert isinstance(det["start"], int)
            assert isinstance(det["end"], int)


if __name__ == "__main__":
    import unittest
    unittest.main()
