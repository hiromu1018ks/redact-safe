"""Unit tests for PII detection engine."""

import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pii_detector import detect_pii, detect_pii_text, load_rules, load_rules_from_string


class TestLoadRules(unittest.TestCase):
    """Test rule loading from YAML files."""

    def test_load_default_rules(self):
        rules = load_rules()
        self.assertIsInstance(rules, list)
        self.assertGreater(len(rules), 0)

    def test_default_rules_have_required_fields(self):
        rules = load_rules()
        for rule in rules:
            self.assertIn("id", rule)
            self.assertIn("name", rule)
            self.assertIn("type", rule)
            self.assertIn("pattern", rule)
            self.assertIn("confidence", rule)
            self.assertIn("enabled", rule)

    def test_load_rules_from_string(self):
        yaml_content = """
rules:
  - id: test_rule
    name: テスト
    type: custom
    pattern: "\\d{4}"
    confidence: 0.5
    enabled: true
"""
        rules = load_rules_from_string(yaml_content)
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0]["id"], "test_rule")

    def test_load_rules_from_empty_string(self):
        rules = load_rules_from_string("")
        self.assertEqual(rules, [])

    def test_default_rules_count(self):
        rules = load_rules()
        self.assertEqual(len(rules), 6)


class TestAddressDetection(unittest.TestCase):
    """Test address (住所) detection."""

    def test_full_address_with_number(self):
        results = detect_pii_text("東京都渋谷区神南1-23-10")
        types = [r["type"] for r in results]
        self.assertIn("address", types)

    def test_osaka_address(self):
        results = detect_pii_text("大阪府大阪市北区梅田3-1-1")
        types = [r["type"] for r in results]
        self.assertIn("address", types)

    def test_hokkaido_address(self):
        results = detect_pii_text("北海道札幌市中央区北1条2-3")
        types = [r["type"] for r in results]
        self.assertIn("address", types)

    def test_address_with_kanji_numbers(self):
        results = detect_pii_text("東京都千代田区一丁目1番1号")
        types = [r["type"] for r in results]
        self.assertIn("address", types)

    def test_address_with_banchi_suffix(self):
        results = detect_pii_text("京都府京都市東山区番町123番地")
        types = [r["type"] for r in results]
        self.assertIn("address", types)

    def test_prefecture_only_no_match(self):
        results = detect_pii_text("東京都は日本の首都です")
        types = [r["type"] for r in results]
        self.assertNotIn("address", types)

    def test_multiple_addresses(self):
        results = detect_pii_text(
            "東京都新宿区1-2-3と大阪府大阪市4-5-6"
        )
        address_results = [r for r in results if r["type"] == "address"]
        self.assertGreaterEqual(len(address_results), 1)

    def test_address_with_ward(self):
        results = detect_pii_text("埼玉県さいたま市浦和区高砂3-15-1")
        types = [r["type"] for r in results]
        self.assertIn("address", types)


class TestPhoneDetection(unittest.TestCase):
    """Test phone number (電話番号) detection."""

    def test_phone_with_hyphens(self):
        results = detect_pii_text("電話番号: 03-1234-5678")
        types = [r["type"] for r in results]
        self.assertIn("phone", types)

    def test_mobile_phone(self):
        results = detect_pii_text("携帯: 090-1234-5678")
        types = [r["type"] for r in results]
        self.assertIn("phone", types)

    def test_phone_without_hyphens(self):
        results = detect_pii_text("連絡先: 0312345678")
        types = [r["type"] for r in results]
        self.assertIn("phone", types)

    def test_mobile_without_hyphens(self):
        results = detect_pii_text("09012345678")
        types = [r["type"] for r in results]
        self.assertIn("phone", types)

    def test_phone_not_confused_with_my_number(self):
        results = detect_pii_text("123456789012")
        phone_results = [r for r in results if r["type"] == "phone"]
        my_number_results = [r for r in results if r["type"] == "my_number"]
        self.assertEqual(len(phone_results), 0)
        self.assertEqual(len(my_number_results), 1)

    def test_freephone(self):
        results = detect_pii_text("フリーダイヤル: 0120-123-456")
        types = [r["type"] for r in results]
        self.assertIn("phone", types)


class TestMyNumberDetection(unittest.TestCase):
    """Test MyNumber (マイナンバー) detection."""

    def test_my_number_12_digits(self):
        results = detect_pii_text("マイナンバー: 123456789012")
        types = [r["type"] for r in results]
        self.assertIn("my_number", types)

    def test_my_number_not_11_digits(self):
        results = detect_pii_text("12345678901")
        types = [r["type"] for r in results]
        self.assertNotIn("my_number", types)

    def test_my_number_not_13_digits(self):
        results = detect_pii_text("1234567890123")
        types = [r["type"] for r in results]
        self.assertNotIn("my_number", types)
        self.assertIn("corporate_number", types)

    def test_my_number_surrounded_by_text(self):
        results = detect_pii_text("番号は123456789012です")
        my_number_results = [r for r in results if r["type"] == "my_number"]
        self.assertEqual(len(my_number_results), 1)
        self.assertEqual(my_number_results[0]["text"], "123456789012")

    def test_my_number_with_leading_zero(self):
        results = detect_pii_text("012345678901")
        types = [r["type"] for r in results]
        self.assertIn("my_number", types)


class TestEmailDetection(unittest.TestCase):
    """Test email address (メールアドレス) detection."""

    def test_basic_email(self):
        results = detect_pii_text("連絡先: test@example.com")
        types = [r["type"] for r in results]
        self.assertIn("email", types)

    def test_email_with_dots(self):
        results = detect_pii_text("user.name@domain.co.jp")
        types = [r["type"] for r in results]
        self.assertIn("email", types)

    def test_email_with_plus(self):
        results = detect_pii_text("user+tag@example.com")
        types = [r["type"] for r in results]
        self.assertIn("email", types)

    def test_email_with_subdomain(self):
        results = detect_pii_text("admin@mail.example.co.jp")
        types = [r["type"] for r in results]
        self.assertIn("email", types)

    def test_no_false_positive_at_sign(self):
        results = detect_pii_text("価格は@1000円です")
        types = [r["type"] for r in results]
        self.assertNotIn("email", types)


class TestBirthDateDetection(unittest.TestCase):
    """Test birth date (生年月日) detection."""

    def test_western_era_japanese_format(self):
        results = detect_pii_text("生年月日: 1990年4月15日")
        types = [r["type"] for r in results]
        self.assertIn("birth_date", types)

    def test_western_era_with_slash(self):
        results = detect_pii_text("1990/04/15")
        types = [r["type"] for r in results]
        self.assertIn("birth_date", types)

    def test_western_era_with_hyphen(self):
        results = detect_pii_text("1990-04-15")
        types = [r["type"] for r in results]
        self.assertIn("birth_date", types)

    def test_reiwa_era(self):
        results = detect_pii_text("令和6年1月1日")
        types = [r["type"] for r in results]
        self.assertIn("birth_date", types)

    def test_heisei_era(self):
        results = detect_pii_text("平成31年4月1日")
        types = [r["type"] for r in results]
        self.assertIn("birth_date", types)

    def test_showa_era(self):
        results = detect_pii_text("昭和50年10月1日")
        types = [r["type"] for r in results]
        self.assertIn("birth_date", types)

    def test_reiwa_gannen(self):
        results = detect_pii_text("令和元年5月1日")
        types = [r["type"] for r in results]
        self.assertIn("birth_date", types)

    def test_era_with_kanji_number(self):
        results = detect_pii_text("昭和五十年")
        types = [r["type"] for r in results]
        self.assertNotIn("birth_date", types)

    def test_single_digit_month_day(self):
        results = detect_pii_text("2000年1月5日")
        types = [r["type"] for r in results]
        self.assertIn("birth_date", types)

    def test_date_with_spaces(self):
        results = detect_pii_text("2000年 1月 5日")
        types = [r["type"] for r in results]
        self.assertIn("birth_date", types)


class TestCorporateNumberDetection(unittest.TestCase):
    """Test corporate number (法人番号) detection."""

    def test_corporate_number_13_digits(self):
        results = detect_pii_text("法人番号: 1234567890123")
        types = [r["type"] for r in results]
        self.assertIn("corporate_number", types)

    def test_corporate_number_not_12_digits(self):
        results = detect_pii_text("123456789012")
        types = [r["type"] for r in results]
        self.assertNotIn("corporate_number", types)
        self.assertIn("my_number", types)

    def test_corporate_number_not_14_digits(self):
        results = detect_pii_text("12345678901234")
        corporate_results = [r for r in results if r["type"] == "corporate_number"]
        self.assertEqual(len(corporate_results), 0)

    def test_corporate_number_in_text(self):
        results = detect_pii_text("法人番号は1234567890123です")
        corporate_results = [r for r in results if r["type"] == "corporate_number"]
        self.assertEqual(len(corporate_results), 1)
        self.assertEqual(corporate_results[0]["text"], "1234567890123")


class TestDetectPiiWithRegions(unittest.TestCase):
    """Test PII detection with structured text regions."""

    def test_detect_with_bbox(self):
        regions = [
            {
                "text": "東京都渋谷区1-2-3",
                "bbox_pt": [100, 200, 300, 50],
            }
        ]
        results = detect_pii(regions)
        self.assertGreater(len(results), 0)
        self.assertEqual(results[0]["bbox_pt"], [100, 200, 300, 50])

    def test_detect_with_region_id(self):
        regions = [
            {
                "id": "region-001",
                "text": "03-1234-5678",
                "bbox_pt": [50, 100, 150, 30],
            }
        ]
        results = detect_pii(regions)
        self.assertGreater(len(results), 0)
        self.assertEqual(results[0]["original_region_id"], "region-001")

    def test_detect_with_region_confidence(self):
        regions = [
            {
                "text": "test@example.com",
                "bbox_pt": [0, 0, 100, 20],
                "confidence": 0.9,
            }
        ]
        results = detect_pii(regions)
        self.assertGreater(len(results), 0)
        # detection confidence = region_confidence * rule_confidence
        self.assertLessEqual(results[0]["confidence"], 0.95)

    def test_empty_regions(self):
        results = detect_pii([])
        self.assertEqual(results, 0) if isinstance(results, int) else self.assertEqual(len(results), 0)

    def test_regions_without_text(self):
        regions = [{"bbox_pt": [0, 0, 100, 20]}]
        results = detect_pii(regions)
        self.assertEqual(len(results), 0)

    def test_multiple_detections_in_one_region(self):
        regions = [
            {
                "text": "TEL: 03-1234-5678 Email: test@example.com",
                "bbox_pt": [0, 0, 400, 20],
            }
        ]
        results = detect_pii(regions)
        types = [r["type"] for r in results]
        self.assertIn("phone", types)
        self.assertIn("email", types)


class TestEnabledTypesFilter(unittest.TestCase):
    """Test filtering by enabled PII types."""

    def test_filter_phone_only(self):
        text = "TEL: 03-1234-5678 Email: test@example.com"
        results = detect_pii_text(text, enabled_types=["phone"])
        types = [r["type"] for r in results]
        self.assertIn("phone", types)
        self.assertNotIn("email", types)

    def test_filter_email_only(self):
        text = "TEL: 03-1234-5678 Email: test@example.com"
        results = detect_pii_text(text, enabled_types=["email"])
        types = [r["type"] for r in results]
        self.assertNotIn("phone", types)
        self.assertIn("email", types)

    def test_filter_none_returns_all(self):
        text = "TEL: 03-1234-5678 Email: test@example.com"
        results = detect_pii_text(text, enabled_types=None)
        types = [r["type"] for r in results]
        self.assertIn("phone", types)
        self.assertIn("email", types)

    def test_filter_empty_list_returns_none(self):
        text = "TEL: 03-1234-5678"
        results = detect_pii_text(text, enabled_types=[])
        self.assertEqual(len(results), 0)


class TestDetectionResultStructure(unittest.TestCase):
    """Test that detection results have the expected structure."""

    def test_result_has_required_fields(self):
        results = detect_pii_text("03-1234-5678")
        self.assertGreater(len(results), 0)
        result = results[0]
        self.assertIn("id", result)
        self.assertIn("text", result)
        self.assertIn("bbox_pt", result)
        self.assertIn("type", result)
        self.assertIn("confidence", result)
        self.assertIn("source", result)
        self.assertIn("rule_id", result)
        self.assertIn("rule_name", result)
        self.assertIn("start", result)
        self.assertIn("end", result)

    def test_source_is_auto(self):
        results = detect_pii_text("03-1234-5678")
        self.assertEqual(results[0]["source"], "auto")

    def test_confidence_bounded(self):
        results = detect_pii_text("03-1234-5678")
        conf = results[0]["confidence"]
        self.assertGreaterEqual(conf, 0.0)
        self.assertLessEqual(conf, 1.0)

    def test_id_is_uuid(self):
        results = detect_pii_text("03-1234-5678")
        import re
        uuid_pattern = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
        self.assertRegex(results[0]["id"], uuid_pattern)


class TestMixedPiiDetection(unittest.TestCase):
    """Test detection of mixed PII types in realistic text."""

    def test_personal_info_block(self):
        text = (
            "山田太郎\n"
            "東京都新宿区西新宿1-1-1\n"
            "TEL: 03-1234-5678\n"
            "Email: yamada@example.com\n"
            "生年月日: 1985年3月20日\n"
            "マイナンバー: 123456789012"
        )
        results = detect_pii_text(text)
        types = [r["type"] for r in results]
        self.assertIn("address", types)
        self.assertIn("phone", types)
        self.assertIn("email", types)
        self.assertIn("birth_date", types)
        self.assertIn("my_number", types)

    def test_corporate_document(self):
        text = (
            "株式会社テスト\n"
            "法人番号: 1234567890123\n"
            "所在地: 大阪府大阪市北区梅田2-4-13\n"
            "TEL: 06-1234-5678"
        )
        results = detect_pii_text(text)
        types = [r["type"] for r in results]
        self.assertIn("corporate_number", types)
        self.assertIn("address", types)
        self.assertIn("phone", types)


if __name__ == "__main__":
    unittest.main()
