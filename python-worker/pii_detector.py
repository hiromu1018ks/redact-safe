"""
PII (Personally Identifiable Information) detection engine for RedactSafe.

Detects sensitive information in Japanese text using regex patterns loaded
from YAML rule definitions. Supports custom rules, type filtering, schema
validation, and regex safety checks.
"""

import re
import os
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError


# Valid PII type identifiers
VALID_PII_TYPES = {
    "name", "address", "phone", "my_number", "email",
    "birth_date", "corporate_number", "custom",
}

# Schema for a single detection rule
REQUIRED_RULE_FIELDS = {"id", "name", "type", "pattern"}
OPTIONAL_RULE_FIELDS = {"confidence", "enabled", "description"}

# Maximum regex match time (seconds) to prevent catastrophic backtracking
REGEX_TIMEOUT_SECONDS = 2.0

# Module-level cache for compiled rules (loaded once, reused across calls)
_rules_cache = {"compiled": None, "rules_path": None}


def validate_my_number(digits_str):
    """Validate a 12-digit My Number (個人番号) using the check digit algorithm.

    Args:
        digits_str: String of exactly 12 digits.

    Returns:
        True if the check digit is valid, False otherwise.
    """
    if len(digits_str) != 12 or not digits_str.isdigit():
        return False

    digits = [int(d) for d in digits_str]
    # Weights for positions 1-11: 6, 5, 4, 3, 2, 1, 6, 5, 4, 3, 2
    weights = [6, 5, 4, 3, 2, 1, 6, 5, 4, 3, 2]
    total = sum(digits[i] * weights[i] for i in range(11))
    remainder = total % 11

    if remainder <= 1:
        expected_check = 0
    else:
        expected_check = 11 - remainder

    return digits[11] == expected_check


def validate_corporate_number(digits_str):
    """Validate a 13-digit Corporate Number (法人番号) using the check digit algorithm.

    Args:
        digits_str: String of exactly 13 digits.

    Returns:
        True if the check digit is valid, False otherwise.
    """
    if len(digits_str) != 13 or not digits_str.isdigit():
        return False

    digits = [int(d) for d in digits_str]
    # Weights for positions 1-12: 1, 2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4
    weights = [1, 2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4]
    total = sum(digits[i] * weights[i] for i in range(12))
    remainder = total % 9

    if remainder == 0:
        expected_check = 0
    else:
        expected_check = 9 - remainder

    return digits[12] == expected_check


def validate_birth_date(matched_text):
    """Validate that a matched date string contains a plausible date.

    Rejects dates with month > 12 or day > 31, and other clearly invalid values.
    Supports Japanese era and Western calendar formats.

    Args:
        matched_text: The matched date string.

    Returns:
        True if the date is plausible, False otherwise.
    """
    import re as _re

    # Extract month and day from the matched text
    # Japanese era format: 令和5年4月22日
    m = _re.search(r'(\d{1,2})月\s*(\d{1,2})日', matched_text)
    if m:
        month = int(m.group(1))
        day = int(m.group(2))
        if month < 1 or month > 12:
            return False
        if day < 1 or day > 31:
            return False
        return True

    # Western format: 2026-04-22 or 2026/04/22 or 2026.04.22
    m = _re.search(r'(\d{4})[-\/.]\s*(\d{1,2})[-\/.]\s*(\d{1,2})', matched_text)
    if m:
        month = int(m.group(2))
        day = int(m.group(3))
        if month < 1 or month > 12:
            return False
        if day < 1 or day > 31:
            return False
        return True

    # If we can't parse it, let it through (be permissive)
    return True


def _compute_bbox_iou(a, b):
    """Compute Intersection over Union (IoU) of two bboxes.

    Each bbox is [x, y, width, height] in PDF point coordinates.

    Returns:
        Float IoU value between 0.0 and 1.0.
    """
    if not a or not b or len(a) < 4 or len(b) < 4:
        return 0.0

    ax1, ay1, aw, ah = a[0], a[1], a[2], a[3]
    bx1, by1, bw, bh = b[0], b[1], b[2], b[3]
    ax2, ay2 = ax1 + aw, ay1 + ah
    bx2, by2 = bx1 + bw, by1 + bh

    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)

    intersection = max(0, ix2 - ix1) * max(0, iy2 - iy1)
    area_a = aw * ah
    area_b = bw * bh
    union = area_a + area_b - intersection

    if union <= 0:
        return 0.0
    return intersection / union


def _get_default_rules_path():
    """Get path to the default detection rules YAML file."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "detection_rules.yaml")


def _get_custom_rules_dir():
    """Get path to the custom rules directory."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "custom_rules")


def check_regex_safety(pattern_str):
    """Check a regex pattern for potential catastrophic backtracking.

    Detects patterns that could cause exponential time complexity on
    certain inputs (ReDoS - Regular Expression Denial of Service).

    Args:
        pattern_str: The regex pattern string to check.

    Returns:
        Tuple of (is_safe: bool, warning: str).
        is_safe is True if no issues found, False if potentially dangerous.
        warning describes the issue found.
    """
    # Check for nested quantifiers: (a+)+, (a*)*, (a+)*, (a+)?, etc.
    nested_quantifier = re.compile(
        r'\([^)]*[+*][^)]*\)[+*?]'
    )
    if nested_quantifier.search(pattern_str):
        return False, "Pattern contains nested quantifiers (potential catastrophic backtracking)"

    # Check for overlapping alternations with quantifiers: (a|a)+, (ab|a)+, etc.
    # Simplified check: alternation inside a group followed by a quantifier
    overlapping_alt = re.compile(
        r'\([^)]*\|[^)]*\)[+*]'
    )
    if overlapping_alt.search(pattern_str):
        # More specific check: verify if alternatives share a common prefix
        # This is a heuristic - not all such patterns are dangerous
        return False, "Pattern contains alternation with quantifier (potential catastrophic backtracking)"

    # Check for excessive repetition: a{n,m} where m-n is very large
    large_range = re.compile(r'\{(\d+),(\d+)\}')
    for match in large_range.finditer(pattern_str):
        min_val = int(match.group(1))
        max_val = int(match.group(2))
        if max_val - min_val > 100:
            return False, f"Pattern has large repetition range {{{min_val},{max_val}}} (potential performance issue)"

    # Check for unbounded repetition on complex groups
    unbounded_group = re.compile(
        r'\([^)]{10,}\)[+*]'
    )
    if unbounded_group.search(pattern_str):
        return False, "Pattern has unbounded quantifier on complex group (potential catastrophic backtracking)"

    return True, ""


def validate_rule(rule, rule_index=None):
    """Validate a single detection rule against the schema.

    Args:
        rule: Dict to validate as a detection rule.
        rule_index: Optional index for error messages.

    Returns:
        Tuple of (is_valid: bool, errors: list of str).
    """
    errors = []
    prefix = f"Rule[{rule_index}]" if rule_index is not None else "Rule"

    if not isinstance(rule, dict):
        errors.append(f"{prefix}: must be a dict, got {type(rule).__name__}")
        return False, errors

    # Check required fields
    missing = REQUIRED_RULE_FIELDS - set(rule.keys())
    if missing:
        errors.append(f"{prefix}: missing required fields: {', '.join(sorted(missing))}")

    # Check for unknown fields
    all_valid = REQUIRED_RULE_FIELDS | OPTIONAL_RULE_FIELDS
    unknown = set(rule.keys()) - all_valid
    if unknown:
        errors.append(f"{prefix}: unknown fields: {', '.join(sorted(unknown))}")

    # Validate 'id'
    if "id" in rule:
        if not isinstance(rule["id"], str) or not rule["id"].strip():
            errors.append(f"{prefix}: 'id' must be a non-empty string")

    # Validate 'name'
    if "name" in rule:
        if not isinstance(rule["name"], str) or not rule["name"].strip():
            errors.append(f"{prefix}: 'name' must be a non-empty string")

    # Validate 'type'
    if "type" in rule:
        if rule["type"] not in VALID_PII_TYPES:
            errors.append(
                f"{prefix}: 'type' must be one of {sorted(VALID_PII_TYPES)}, got '{rule['type']}'"
            )

    # Validate 'pattern'
    if "pattern" in rule:
        if not isinstance(rule["pattern"], str) or not rule["pattern"].strip():
            errors.append(f"{prefix}: 'pattern' must be a non-empty string")
        else:
            # Check regex validity
            try:
                re.compile(rule["pattern"].strip())
            except re.error as e:
                errors.append(f"{prefix}: invalid regex pattern: {e}")

            # Check regex safety
            is_safe, warning = check_regex_safety(rule["pattern"])
            if not is_safe:
                errors.append(f"{prefix}: {warning}")

    # Validate 'confidence'
    if "confidence" in rule:
        conf = rule["confidence"]
        if not isinstance(conf, (int, float)):
            errors.append(f"{prefix}: 'confidence' must be a number, got {type(conf).__name__}")
        elif not (0.0 <= conf <= 1.0):
            errors.append(f"{prefix}: 'confidence' must be between 0.0 and 1.0, got {conf}")

    # Validate 'enabled'
    if "enabled" in rule:
        if not isinstance(rule["enabled"], bool):
            errors.append(f"{prefix}: 'enabled' must be a boolean, got {type(rule['enabled']).__name__}")

    return len(errors) == 0, errors


def validate_rules(rules):
    """Validate a list of detection rules.

    Args:
        rules: List of rule dicts to validate.

    Returns:
        Tuple of (is_valid: bool, errors: list of str).
    """
    all_errors = []
    for i, rule in enumerate(rules):
        is_valid, errors = validate_rule(rule, rule_index=i)
        if not is_valid:
            all_errors.extend(errors)

    # Check for duplicate IDs
    if isinstance(rules, list):
        seen_ids = set()
        for i, rule in enumerate(rules):
            if isinstance(rule, dict):
                rule_id = rule.get("id", "")
                if rule_id in seen_ids:
                    all_errors.append(f"Rule[{i}]: duplicate rule id '{rule_id}'")
                seen_ids.add(rule_id)

    return len(all_errors) == 0, all_errors


def load_rules(rules_path=None):
    """Load detection rules from a YAML or JSON file.

    Args:
        rules_path: Path to rules file (YAML or JSON). Uses bundled default if None.

    Returns:
        List of rule dicts with 'id', 'name', 'type', 'pattern', 'confidence', 'enabled'.
    """
    if rules_path is None:
        rules_path = _get_default_rules_path()

    if not os.path.exists(rules_path):
        sys.stderr.write(f"Warning: Rules file not found: {rules_path}\n")
        return []

    _, ext = os.path.splitext(rules_path)
    ext = ext.lower()

    with open(rules_path, "r", encoding="utf-8") as f:
        content = f.read()

    if ext == ".json":
        import json
        data = json.loads(content)
    else:
        import yaml
        data = yaml.safe_load(content)

    return data.get("rules", []) if isinstance(data, dict) else []


def load_rules_from_string(content, format_hint=None):
    """Load detection rules from a YAML or JSON string.

    Args:
        content: String containing rules definition.
        format_hint: "yaml" or "json" to force format. Auto-detects if None.

    Returns:
        List of rule dicts.
    """
    if format_hint == "json":
        import json
        data = json.loads(content)
    elif format_hint == "yaml":
        import yaml
        data = yaml.safe_load(content)
    else:
        # Auto-detect: try JSON first (faster), then YAML
        try:
            import json
            data = json.loads(content)
        except (json.JSONDecodeError, ValueError):
            import yaml
            data = yaml.safe_load(content)

    if not isinstance(data, dict):
        return []

    return data.get("rules", [])


def load_custom_rules(rules_dir=None):
    """Load all custom rule files from the custom rules directory.

    Looks for *.yaml, *.yml, and *.json files in the custom rules directory.

    Args:
        rules_dir: Path to custom rules directory. Uses default if None.

    Returns:
        Tuple of (rules: list, errors: list of str).
    """
    if rules_dir is None:
        rules_dir = _get_custom_rules_dir()

    if not os.path.isdir(rules_dir):
        return [], []

    all_rules = []
    all_errors = []

    for filename in sorted(os.listdir(rules_dir)):
        ext = os.path.splitext(filename)[1].lower()
        if ext not in (".yaml", ".yml", ".json"):
            continue

        filepath = os.path.join(rules_dir, filename)
        try:
            rules = load_rules(filepath)
            is_valid, errors = validate_rules(rules)
            if not is_valid:
                all_errors.extend(
                    [f"{filename}: {e}" for e in errors]
                )
                continue

            # Check for ID conflicts with already loaded rules
            existing_ids = {r.get("id") for r in all_rules}
            for rule in rules:
                if rule.get("id") in existing_ids:
                    all_errors.append(
                        f"{filename}: rule id '{rule['id']}' conflicts with a previously loaded rule"
                    )
                else:
                    all_rules.append(rule)
                    existing_ids.add(rule.get("id"))

        except Exception as e:
            all_errors.append(f"{filename}: failed to load: {e}")

    return all_rules, all_errors


def merge_rules(bundled_rules, custom_rules):
    """Merge bundled rules with custom rules.

    Custom rules override bundled rules with the same ID.
    Custom rules with new IDs are appended.

    Args:
        bundled_rules: List of bundled rule dicts.
        custom_rules: List of custom rule dicts.

    Returns:
        Merged list of rule dicts.
    """
    bundled_map = {r["id"]: r for r in bundled_rules}
    merged = list(bundled_rules)
    seen_ids = set(bundled_map.keys())

    for rule in custom_rules:
        rule_id = rule.get("id", "")
        if rule_id in seen_ids:
            # Override bundled rule
            merged = [r for r in merged if r.get("id") != rule_id]
            merged.append(rule)
        else:
            merged.append(rule)
            seen_ids.add(rule_id)

    return merged


def _compile_rules(rules):
    """Compile regex patterns from rule definitions.

    Args:
        rules: List of rule dicts.

    Returns:
        List of compiled rule dicts with 'compiled_pattern' key.
    """
    compiled = []
    for rule in rules:
        if not rule.get("enabled", True):
            continue

        pattern_str = rule["pattern"]
        if isinstance(pattern_str, str):
            pattern_str = pattern_str.strip()

        try:
            compiled_re = re.compile(pattern_str)
        except re.error as e:
            sys.stderr.write(
                f"Warning: Invalid regex in rule '{rule.get('id', '?')}': {e}\n"
            )
            continue

        compiled.append(
            {
                "id": rule["id"],
                "name": rule["name"],
                "type": rule["type"],
                "compiled_pattern": compiled_re,
                "confidence": rule.get("confidence", 0.8),
                "description": rule.get("description", ""),
            }
        )

    return compiled


def detect_pii(text_regions, rules=None, rules_path=None, enabled_types=None,
               enable_name_detection=True, custom_rules_dir=None):
    """Detect PII in extracted text regions.

    Combines regex-based detection with MeCab morphological analysis for
    person name detection.

    Args:
        text_regions: List of dicts, each with 'text' and 'bbox_pt' keys.
                     'bbox_pt' is [x, y, width, height] in PDF point coordinates.
                     Optional keys: 'id', 'confidence'.
        rules: Optional list of rule dicts (from YAML). Loads defaults if None.
        rules_path: Optional path to custom rules YAML file.
        enabled_types: Optional list of PII type strings to detect. None = all.
        enable_name_detection: Whether to enable MeCab-based name detection.
        custom_rules_dir: Optional path to custom rules directory.

    Returns:
        List of detected PII region dicts with:
            'id', 'text', 'bbox_pt', 'type', 'confidence', 'source',
            'rule_id', 'rule_name', 'start', 'end', 'original_region_id'
    """
    # Load and merge rules (bundled + custom), with module-level caching
    if rules is None:
        cache_key = (rules_path, custom_rules_dir)
        if _rules_cache["rules_path"] == cache_key and _rules_cache["compiled"] is not None:
            compiled = _rules_cache["compiled"]
        else:
            bundled_rules = load_rules(rules_path)
            if custom_rules_dir:
                custom_rules, _ = load_custom_rules(custom_rules_dir)
                rules = merge_rules(bundled_rules, custom_rules)
            else:
                rules = bundled_rules
            compiled = _compile_rules(rules)
            _rules_cache["rules_path"] = cache_key
            _rules_cache["compiled"] = compiled
    else:
        compiled = _compile_rules(rules)

    detections = []
    executor = ThreadPoolExecutor(max_workers=1)

    for region in text_regions:
            text = region.get("text", "")
            if not text:
                continue

            bbox = region.get("bbox_pt", region.get("bbox", []))
            region_conf = region.get("confidence", 1.0)

            for rule in compiled:
                if enabled_types is not None and rule["type"] not in enabled_types:
                    continue

                try:
                    # Run regex matching in a separate thread with timeout
                    future = executor.submit(
                        list, rule["compiled_pattern"].finditer(text)
                    )
                    matches = future.result(timeout=REGEX_TIMEOUT_SECONDS)
                except FuturesTimeoutError:
                    sys.stderr.write(
                        f"Warning: Rule '{rule['id']}' timed out "
                        f"after {REGEX_TIMEOUT_SECONDS}s, skipping\n"
                    )
                    continue
                except Exception as e:
                    sys.stderr.write(
                        f"Warning: Error applying rule '{rule['id']}': {e}\n"
                    )
                    continue

                for match in matches:
                    matched_text = match.group()

                    # Validate check digits for structured number types
                    if rule["type"] == "my_number" and not validate_my_number(matched_text):
                        continue
                    if rule["type"] == "corporate_number" and not validate_corporate_number(matched_text):
                        continue
                    # Validate birth dates (reject 99月99日 etc.)
                    if rule["type"] == "birth_date" and not validate_birth_date(matched_text):
                        continue

                    detection = {
                        "id": str(uuid.uuid4()),
                        "text": matched_text,
                        "bbox_pt": list(bbox) if bbox else [],
                        "type": rule["type"],
                        "confidence": round(
                            min(region_conf * rule["confidence"], 1.0), 4
                        ),
                        "source": "auto",
                        "rule_id": rule["id"],
                        "rule_name": rule["name"],
                        "start": match.start(),
                        "end": match.end(),
                        "original_region_id": region.get("id"),
                    }
                    detections.append(detection)

    # MeCab-based name detection
    if enable_name_detection:
        try:
            from name_detector import detect_names
            name_detections = detect_names(text_regions, enabled_types=enabled_types)

            # Deduplicate: remove regex detections that overlap with MeCab name detections
            # When bboxes overlap significantly (IoU > 0.3), keep the higher-confidence one
            if name_detections:
                filtered = []
                for det in detections:
                    is_duplicate = False
                    if det.get("type") == "name" and det.get("bbox_pt"):
                        det_bbox = det["bbox_pt"]
                        for name_det in name_detections:
                            name_bbox = name_det.get("bbox_pt", [])
                            if name_bbox and len(name_bbox) == 4:
                                iou = _compute_bbox_iou(det_bbox, name_bbox)
                                if iou > 0.3:
                                    # Keep the one with higher confidence
                                    if name_det.get("confidence", 0) >= det.get("confidence", 0):
                                        is_duplicate = True
                                        break
                    if not is_duplicate:
                        filtered.append(det)
                detections = filtered
                detections.extend(name_detections)
            else:
                detections.extend(name_detections)
        except Exception as e:
            sys.stderr.write(f"Warning: Name detection failed: {e}\n")

    executor.shutdown(wait=False)
    return detections


def detect_pii_text(text, rules=None, rules_path=None, enabled_types=None,
                    enable_name_detection=True):
    """Detect PII in a single text string (convenience function for testing).

    Args:
        text: Input text string.
        rules: Optional list of rule dicts.
        rules_path: Optional path to custom rules YAML.
        enabled_types: Optional list of PII types to detect.
        enable_name_detection: Whether to enable MeCab-based name detection.

    Returns:
        List of detected PII match dicts.
    """
    regions = [{"text": text, "bbox_pt": []}]
    return detect_pii(
        regions, rules=rules, rules_path=rules_path, enabled_types=enabled_types,
        enable_name_detection=enable_name_detection,
    )


def detect_pii_base64(
    pdf_data_b64,
    page_num,
    text_regions=None,
    rules_path=None,
    enabled_types=None,
    password="",
    enable_name_detection=True,
    custom_rules_dir=None,
    progress_callback=None,
    pdf_path="",
):
    """Detect PII from text extraction results for a PDF page.

    JSON-RPC entry point that combines text extraction and PII detection.

    Args:
        pdf_data_b64: Base64-encoded PDF data (ignored if pdf_path is provided).
        page_num: Page number (0-indexed).
        text_regions: Optional pre-extracted text regions.
                     If None, extracts text from PDF automatically.
        rules_path: Optional path to custom rules YAML.
        enabled_types: Optional list of PII types to detect.
        password: PDF password if encrypted.
        enable_name_detection: Whether to enable MeCab-based name detection.
        custom_rules_dir: Optional path to custom rules directory.
        progress_callback: Optional callable(phase, current, total, message) for progress.
        pdf_path: Optional file path to open PDF directly (avoids base64 overhead).

    Returns:
        Dict with 'detections', 'region_count', 'detection_count'.
    """
    if progress_callback:
        progress_callback("pii_detection_start", 0, 2, "PII検出開始...")

    if text_regions is None:
        from ocr_pipeline import run_text_extraction

        if progress_callback:
            progress_callback("text_extraction", 0, 2, "テキスト抽出中...")

        extraction_result = run_text_extraction(
            pdf_data_b64, page_num, 300, password, progress_callback=progress_callback,
            pdf_path=pdf_path,
        )
        text_regions = extraction_result.get("text_regions", [])

    if progress_callback:
        progress_callback("pii_detecting", 1, 2, "個人情報を検出中...")

    detections = detect_pii(
        text_regions, rules_path=rules_path, enabled_types=enabled_types,
        enable_name_detection=enable_name_detection,
        custom_rules_dir=custom_rules_dir,
    )

    if progress_callback:
        progress_callback("pii_detection_complete", 2, 2, "PII検出完了")

    return {
        "detections": detections,
        "region_count": len(text_regions),
        "detection_count": len(detections),
    }


# --- Unit tests for check digit validation ---

if __name__ == "__main__":
    import unittest

    class TestMyNumberValidation(unittest.TestCase):
        def test_valid_my_number(self):
            # Check digit: total=176, rem=0, expected=0 → 123456789010
            self.assertTrue(validate_my_number("123456789010"))

        def test_invalid_my_number_bad_check_digit(self):
            # Same prefix but wrong check digit (8 instead of 0)
            self.assertFalse(validate_my_number("123456789018"))

        def test_invalid_my_number_too_short(self):
            self.assertFalse(validate_my_number("12345678901"))

        def test_invalid_my_number_too_long(self):
            self.assertFalse(validate_my_number("1234567890123"))

        def test_invalid_my_number_non_digit(self):
            self.assertFalse(validate_my_number("12345678901a"))

    class TestCorporateNumberValidation(unittest.TestCase):
        def test_valid_corporate_number(self):
            # Check digit: total=36, rem=0, expected=0 → 6010001003220
            self.assertTrue(validate_corporate_number("6010001003220"))

        def test_invalid_corporate_number_bad_check_digit(self):
            self.assertFalse(validate_corporate_number("6010001003226"))

        def test_invalid_corporate_number_too_short(self):
            self.assertFalse(validate_corporate_number("601000100322"))

        def test_invalid_corporate_number_too_long(self):
            self.assertFalse(validate_corporate_number("60100010032267"))

        def test_invalid_corporate_number_non_digit(self):
            self.assertFalse(validate_corporate_number("601000100322a"))

    unittest.main()
