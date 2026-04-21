"""Tests for custom rules loading, schema validation, and regex safety checking."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pii_detector import (
    check_regex_safety,
    validate_rule,
    validate_rules,
    load_rules_from_string,
    load_custom_rules,
    merge_rules,
    VALID_PII_TYPES,
)


class TestRegexSafety:
    def test_safe_pattern(self):
        is_safe, warning = check_regex_safety(r"\d{4}-\d{2}-\d{2}")
        assert is_safe is True
        assert warning == ""

    def test_nested_quantifier(self):
        is_safe, warning = check_regex_safety(r"(a+)+")
        assert is_safe is False
        assert "nested quantifiers" in warning.lower()

    def test_nested_star(self):
        is_safe, warning = check_regex_safety(r"(a*)*")
        assert is_safe is False

    def test_overlapping_alternation(self):
        is_safe, warning = check_regex_safety(r"(a|a)+")
        assert is_safe is False
        assert "alternation" in warning.lower()

    def test_large_repetition_range(self):
        is_safe, warning = check_regex_safety(r"a{0,200}")
        assert is_safe is False
        assert "large repetition" in warning.lower()

    def test_small_repetition_range(self):
        is_safe, warning = check_regex_safety(r"a{0,50}")
        assert is_safe is True

    def test_complex_group_quantifier(self):
        is_safe, warning = check_regex_safety(r"(\w+\d+\s+)+x")
        assert is_safe is False

    def test_email_pattern_safe(self):
        is_safe, warning = check_regex_safety(
            r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"
        )
        assert is_safe is True

    def test_phone_pattern_safe(self):
        is_safe, warning = check_regex_safety(
            r"(?:0\d{2,4}[-ー―—–]\d{1,4}[-ー―—–]\d{3,4}|0\d{9,10})(?!\d)"
        )
        assert is_safe is True


class TestValidateRule:
    def test_valid_rule(self):
        rule = {
            "id": "test_rule",
            "name": "テスト",
            "type": "address",
            "pattern": r"\d+",
        }
        is_valid, errors = validate_rule(rule)
        assert is_valid is True
        assert errors == []

    def test_missing_required_fields(self):
        rule = {"id": "test"}
        is_valid, errors = validate_rule(rule)
        assert is_valid is False
        assert len(errors) > 0

    def test_invalid_type(self):
        rule = {
            "id": "test",
            "name": "テスト",
            "type": "invalid_type",
            "pattern": r"\d+",
        }
        is_valid, errors = validate_rule(rule)
        assert is_valid is False
        assert any("type" in e for e in errors)

    def test_invalid_pattern(self):
        rule = {
            "id": "test",
            "name": "テスト",
            "type": "custom",
            "pattern": r"(?P<unclosed",
        }
        is_valid, errors = validate_rule(rule)
        assert is_valid is False
        assert any("regex" in e.lower() or "pattern" in e.lower() for e in errors)

    def test_unsafe_pattern(self):
        rule = {
            "id": "test",
            "name": "テスト",
            "type": "custom",
            "pattern": r"(a+)+",
        }
        is_valid, errors = validate_rule(rule)
        assert is_valid is False
        assert any("catastrophic" in e.lower() or "nested" in e.lower() for e in errors)

    def test_confidence_out_of_range(self):
        rule = {
            "id": "test",
            "name": "テスト",
            "type": "custom",
            "pattern": r"\d+",
            "confidence": 1.5,
        }
        is_valid, errors = validate_rule(rule)
        assert is_valid is False
        assert any("confidence" in e.lower() for e in errors)

    def test_confidence_negative(self):
        rule = {
            "id": "test",
            "name": "テスト",
            "type": "custom",
            "pattern": r"\d+",
            "confidence": -0.1,
        }
        is_valid, errors = validate_rule(rule)
        assert is_valid is False

    def test_valid_confidence(self):
        rule = {
            "id": "test",
            "name": "テスト",
            "type": "custom",
            "pattern": r"\d+",
            "confidence": 0.95,
        }
        is_valid, errors = validate_rule(rule)
        assert is_valid is True

    def test_enabled_boolean(self):
        rule = {
            "id": "test",
            "name": "テスト",
            "type": "custom",
            "pattern": r"\d+",
            "enabled": "yes",
        }
        is_valid, errors = validate_rule(rule)
        assert is_valid is False
        assert any("boolean" in e.lower() for e in errors)

    def test_unknown_fields(self):
        rule = {
            "id": "test",
            "name": "テスト",
            "type": "custom",
            "pattern": r"\d+",
            "unknown_field": "value",
        }
        is_valid, errors = validate_rule(rule)
        assert is_valid is False
        assert any("unknown" in e.lower() for e in errors)

    def test_non_dict_input(self):
        is_valid, errors = validate_rule("not a dict")
        assert is_valid is False
        assert any("dict" in e.lower() for e in errors)

    def test_empty_id(self):
        rule = {
            "id": "",
            "name": "テスト",
            "type": "custom",
            "pattern": r"\d+",
        }
        is_valid, errors = validate_rule(rule)
        assert is_valid is False

    def test_all_valid_types(self):
        for pii_type in VALID_PII_TYPES:
            rule = {
                "id": f"test_{pii_type}",
                "name": pii_type,
                "type": pii_type,
                "pattern": r"\d+",
            }
            is_valid, errors = validate_rule(rule)
            assert is_valid is True, f"Type {pii_type} should be valid: {errors}"


class TestValidateRules:
    def test_valid_rules_list(self):
        rules = [
            {"id": "r1", "name": "テスト1", "type": "address", "pattern": r"\d+"},
            {"id": "r2", "name": "テスト2", "type": "phone", "pattern": r"\d+"},
        ]
        is_valid, errors = validate_rules(rules)
        assert is_valid is True
        assert errors == []

    def test_duplicate_ids(self):
        rules = [
            {"id": "dup", "name": "テスト1", "type": "address", "pattern": r"\d+"},
            {"id": "dup", "name": "テスト2", "type": "phone", "pattern": r"\d+"},
        ]
        is_valid, errors = validate_rules(rules)
        assert is_valid is False
        assert any("duplicate" in e.lower() for e in errors)

    def test_mixed_valid_invalid(self):
        rules = [
            {"id": "r1", "name": "テスト1", "type": "address", "pattern": r"\d+"},
            {"id": "r2", "name": "テスト2", "type": "invalid", "pattern": r"\d+"},
        ]
        is_valid, errors = validate_rules(rules)
        assert is_valid is False

    def test_empty_list(self):
        is_valid, errors = validate_rules([])
        assert is_valid is True


class TestLoadRulesFromString:
    def test_yaml_format(self):
        yaml_content = """
version: "1.0"
rules:
  - id: test_yaml
    name: YAML Test
    type: custom
    pattern: "\\d{4}"
    confidence: 0.9
"""
        rules = load_rules_from_string(yaml_content, format_hint="yaml")
        assert len(rules) == 1
        assert rules[0]["id"] == "test_yaml"

    def test_json_format(self):
        json_content = '{"rules": [{"id": "test_json", "name": "JSON Test", "type": "custom", "pattern": "\\\\d{4}"}]}'
        rules = load_rules_from_string(json_content, format_hint="json")
        assert len(rules) == 1
        assert rules[0]["id"] == "test_json"

    def test_auto_detect_json(self):
        json_content = '{"rules": [{"id": "auto_json", "name": "Auto JSON", "type": "custom", "pattern": "\\\\d+"}]}'
        rules = load_rules_from_string(json_content)
        assert len(rules) == 1
        assert rules[0]["id"] == "auto_json"

    def test_auto_detect_yaml(self):
        yaml_content = """
rules:
  - id: auto_yaml
    name: Auto YAML
    type: custom
    pattern: "\\d+"
"""
        rules = load_rules_from_string(yaml_content)
        assert len(rules) == 1
        assert rules[0]["id"] == "auto_yaml"

    def test_empty_string(self):
        rules = load_rules_from_string("")
        assert rules == []

    def test_invalid_content(self):
        rules = load_rules_from_string("not valid anything", format_hint="json")
        # JSON parse error returns empty
        assert rules == []


class TestMergeRules:
    def test_no_override(self):
        bundled = [
            {"id": "r1", "name": "Rule 1", "type": "address", "pattern": r"\d+"},
        ]
        custom = [
            {"id": "r2", "name": "Rule 2", "type": "phone", "pattern": r"\d+"},
        ]
        merged = merge_rules(bundled, custom)
        assert len(merged) == 2
        merged_ids = {r["id"] for r in merged}
        assert merged_ids == {"r1", "r2"}

    def test_override(self):
        bundled = [
            {"id": "r1", "name": "Old Rule 1", "type": "address", "pattern": r"\d+"},
        ]
        custom = [
            {"id": "r1", "name": "New Rule 1", "type": "address", "pattern": r"[0-9]+"},
        ]
        merged = merge_rules(bundled, custom)
        assert len(merged) == 1
        assert merged[0]["name"] == "New Rule 1"

    def test_empty_custom(self):
        bundled = [
            {"id": "r1", "name": "Rule 1", "type": "address", "pattern": r"\d+"},
        ]
        merged = merge_rules(bundled, [])
        assert len(merged) == 1
        assert merged[0]["name"] == "Rule 1"

    def test_empty_bundled(self):
        custom = [
            {"id": "r2", "name": "Rule 2", "type": "phone", "pattern": r"\d+"},
        ]
        merged = merge_rules([], custom)
        assert len(merged) == 1


class TestLoadCustomRules:
    def test_nonexistent_dir(self):
        rules, errors = load_custom_rules("/nonexistent/path")
        assert rules == []
        assert errors == []

    def test_empty_dir(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            rules, errors = load_custom_rules(tmpdir)
            assert rules == []
            assert errors == []

    def test_yaml_file(self):
        import tempfile
        yaml_content = """
version: "1.0"
rules:
  - id: custom_yaml_rule
    name: YAML Custom
    type: custom
    pattern: "\\d{5}"
    confidence: 0.75
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, "custom.yaml")
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(yaml_content)
            rules, errors = load_custom_rules(tmpdir)
            assert len(rules) == 1
            assert rules[0]["id"] == "custom_yaml_rule"
            assert errors == []

    def test_json_file(self):
        import tempfile
        json_content = '{"rules": [{"id": "custom_json_rule", "name": "JSON Custom", "type": "custom", "pattern": "\\\\d{6}"}]}'
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, "custom.json")
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(json_content)
            rules, errors = load_custom_rules(tmpdir)
            assert len(rules) == 1
            assert rules[0]["id"] == "custom_json_rule"
            assert errors == []

    def test_invalid_rule_skipped(self):
        import tempfile
        yaml_content = """
rules:
  - id: bad_rule
    name: Bad
    type: nonexistent_type
    pattern: "(a+)+"
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, "bad.yaml")
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(yaml_content)
            rules, errors = load_custom_rules(tmpdir)
            assert len(rules) == 0
            assert len(errors) > 0

    def test_non_rule_files_ignored(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create non-rule files
            for name in ["readme.txt", "notes.md", "script.py"]:
                with open(os.path.join(tmpdir, name), "w") as f:
                    f.write("content")
            rules, errors = load_custom_rules(tmpdir)
            assert rules == []
            assert errors == []

    def test_multiple_files(self):
        import tempfile
        yaml_content = """
rules:
  - id: rule_from_yaml
    name: YAML Rule
    type: custom
    pattern: "\\d{3}"
"""
        json_content = '{"rules": [{"id": "rule_from_json", "name": "JSON Rule", "type": "custom", "pattern": "\\\\d{4}"}]}'

        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "a.yaml"), "w", encoding="utf-8") as f:
                f.write(yaml_content)
            with open(os.path.join(tmpdir, "b.json"), "w", encoding="utf-8") as f:
                f.write(json_content)
            rules, errors = load_custom_rules(tmpdir)
            assert len(rules) == 2
            assert errors == []


if __name__ == "__main__":
    import unittest
    unittest.main()
