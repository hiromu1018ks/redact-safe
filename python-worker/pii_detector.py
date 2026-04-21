"""
PII (Personally Identifiable Information) detection engine for RedactSafe.

Detects sensitive information in Japanese text using regex patterns loaded
from YAML rule definitions. Supports custom rules and type filtering.
"""

import re
import os
import sys
import uuid


def _get_default_rules_path():
    """Get path to the default detection rules YAML file."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "detection_rules.yaml")


def load_rules(rules_path=None):
    """Load detection rules from a YAML file.

    Args:
        rules_path: Path to YAML rules file. Uses bundled default if None.

    Returns:
        List of rule dicts with 'id', 'name', 'type', 'pattern', 'confidence', 'enabled'.
    """
    import yaml

    if rules_path is None:
        rules_path = _get_default_rules_path()

    with open(rules_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    return data.get("rules", []) if isinstance(data, dict) else []


def load_rules_from_string(yaml_content):
    """Load detection rules from a YAML string.

    Args:
        yaml_content: YAML string containing rules definition.

    Returns:
        List of rule dicts.
    """
    import yaml

    data = yaml.safe_load(yaml_content)
    if not isinstance(data, dict):
        return []

    return data.get("rules", [])


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


def detect_pii(text_regions, rules=None, rules_path=None, enabled_types=None):
    """Detect PII in extracted text regions.

    Args:
        text_regions: List of dicts, each with 'text' and 'bbox_pt' keys.
                     'bbox_pt' is [x, y, width, height] in PDF point coordinates.
                     Optional keys: 'id', 'confidence'.
        rules: Optional list of rule dicts (from YAML). Loads defaults if None.
        rules_path: Optional path to custom rules YAML file.
        enabled_types: Optional list of PII type strings to detect. None = all.

    Returns:
        List of detected PII region dicts with:
            'id', 'text', 'bbox_pt', 'type', 'confidence', 'source',
            'rule_id', 'rule_name', 'start', 'end', 'original_region_id'
    """
    if rules is None:
        rules = load_rules(rules_path)

    compiled = _compile_rules(rules)
    detections = []

    for region in text_regions:
        text = region.get("text", "")
        if not text:
            continue

        bbox = region.get("bbox_pt", region.get("bbox", []))
        region_conf = region.get("confidence", 1.0)

        for rule in compiled:
            if enabled_types is not None and rule["type"] not in enabled_types:
                continue

            for match in rule["compiled_pattern"].finditer(text):
                matched_text = match.group()

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

    return detections


def detect_pii_text(text, rules=None, rules_path=None, enabled_types=None):
    """Detect PII in a single text string (convenience function for testing).

    Args:
        text: Input text string.
        rules: Optional list of rule dicts.
        rules_path: Optional path to custom rules YAML.
        enabled_types: Optional list of PII types to detect.

    Returns:
        List of detected PII match dicts.
    """
    regions = [{"text": text, "bbox_pt": []}]
    return detect_pii(
        regions, rules=rules, rules_path=rules_path, enabled_types=enabled_types
    )


def detect_pii_base64(
    pdf_data_b64,
    page_num,
    text_regions=None,
    rules_path=None,
    enabled_types=None,
    password="",
):
    """Detect PII from text extraction results for a PDF page.

    JSON-RPC entry point that combines text extraction and PII detection.

    Args:
        pdf_data_b64: Base64-encoded PDF data.
        page_num: Page number (0-indexed).
        text_regions: Optional pre-extracted text regions.
                     If None, extracts text from PDF automatically.
        rules_path: Optional path to custom rules YAML.
        enabled_types: Optional list of PII types to detect.
        password: PDF password if encrypted.

    Returns:
        Dict with 'detections', 'region_count', 'detection_count'.
    """
    if text_regions is None:
        from ocr_pipeline import run_text_extraction

        extraction_result = run_text_extraction(
            pdf_data_b64, page_num, 300, password
        )
        text_regions = extraction_result.get("regions", [])

    detections = detect_pii(
        text_regions, rules_path=rules_path, enabled_types=enabled_types
    )

    return {
        "detections": detections,
        "region_count": len(text_regions),
        "detection_count": len(detections),
    }
