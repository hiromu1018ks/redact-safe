"""
Name detection module using MeCab (fugashi) morphological analysis.

Detects person names (氏名) in Japanese text using UniDic-based morphological
analysis. Uses fugashi as the MeCab wrapper with unidic-lite dictionary.
"""

import sys
import uuid
import re


_tagger = None


def _get_tagger():
    """Lazily initialize the fugashi MeCab tagger."""
    global _tagger
    if _tagger is None:
        try:
            import fugashi
            _tagger = fugashi.Tagger()
        except ImportError:
            sys.stderr.write(
                "Warning: fugashi not available. Name detection via MeCab is disabled.\n"
            )
            return None
        except Exception as e:
            sys.stderr.write(
                f"Warning: Failed to initialize MeCab tagger: {e}\n"
            )
            return None
    return _tagger


def _get_pos_fields(word):
    """Extract POS fields from a fugashi word object.

    UniDic POS structure:
      - pos1 (品詞大分類): 名詞, 動詞, etc.
      - pos2 (品詞中分類): 固有名詞, 人名, etc.
      - pos3 (品詞小分類): 一般, 姓, 名, etc.
      - pos4 (品詞細分類): (optional)
    Also checks for surface form and lemma.
    """
    feature = word.feature
    if isinstance(feature, str):
        parts = feature.split(",")
        return {
            "pos1": parts[0] if len(parts) > 0 else "",
            "pos2": parts[1] if len(parts) > 1 else "",
            "pos3": parts[2] if len(parts) > 2 else "",
            "pos4": parts[3] if len(parts) > 3 else "",
        }
    elif isinstance(feature, (list, tuple)):
        return {
            "pos1": feature[0] if len(feature) > 0 else "",
            "pos2": feature[1] if len(feature) > 1 else "",
            "pos3": feature[2] if len(feature) > 2 else "",
            "pos4": feature[3] if len(feature) > 3 else "",
        }
    return {"pos1": "", "pos2": "", "pos3": "", "pos4": ""}


def _is_name_token(pos):
    """Check if a token's POS indicates a person name component.

    Returns:
        Tuple of (is_name, subcategory) where subcategory is:
        - "surname" for 姓
        - "given" for 名
        - "person" for generic 人名
        - "" if not a name
    """
    pos1 = pos["pos1"]
    pos2 = pos["pos2"]
    pos3 = pos["pos3"]

    # 固有名詞-人名-姓
    if pos1 == "名詞" and pos2 == "固有名詞" and pos3 == "人名":
        return True, "person"
    if pos1 == "名詞" and pos2 == "固有名詞" and pos3 == "人名姓":
        return True, "surname"
    if pos1 == "名詞" and pos2 == "固有名詞" and pos3 == "人名名":
        return True, "given"

    return False, ""


def _calculate_name_confidence(name_tokens, context_text):
    """Calculate confidence score for a detected name.

    Higher confidence when:
    - Multiple name tokens are found in sequence (full name pattern)
    - The name appears before a title/role marker (様, 氏, さん, etc.)
    - The name has both surname and given name components

    Args:
        name_tokens: List of dicts with 'surface', 'subcategory' keys.
        context_text: Original text surrounding the name.

    Returns:
        Float confidence score between 0.0 and 1.0.
    """
    if not name_tokens:
        return 0.0

    confidence = 0.60  # base confidence for single name token

    # Boost for multiple tokens (likely full name)
    if len(name_tokens) >= 2:
        confidence += 0.10
        has_surname = any(t["subcategory"] == "surname" for t in name_tokens)
        has_given = any(t["subcategory"] == "given" for t in name_tokens)
        if has_surname and has_given:
            confidence += 0.10  # full name with surname + given

    # Boost for honorific/title after the name
    full_name = "".join(t["surface"] for t in name_tokens)
    honorifics = ["様", "氏", "さん", "殿", "先生", "氏"]
    for honorific in honorifics:
        if honorific in context_text:
            idx = context_text.find(full_name)
            honorific_idx = context_text.find(honorific)
            if idx >= 0 and honorific_idx > idx:
                confidence += 0.10
                break

    return round(min(confidence, 1.0), 4)


def detect_names(text_regions, enabled_types=None):
    """Detect person names in text regions using MeCab morphological analysis.

    Uses fugashi (MeCab wrapper) with UniDic to identify proper nouns
    classified as person names (人名), then groups consecutive name tokens
    into full name detections.

    Args:
        text_regions: List of dicts, each with 'text' and 'bbox_pt' keys.
                     'bbox_pt' is [x, y, width, height] in PDF point coordinates.
                     Optional keys: 'id', 'confidence'.
        enabled_types: Optional list of PII type strings to detect.
                      None = all types. Name detection is type "name".

    Returns:
        List of detected name region dicts with:
            'id', 'text', 'bbox_pt', 'type', 'confidence', 'source',
            'rule_id', 'rule_name', 'start', 'end', 'original_region_id'
    """
    if enabled_types is not None and "name" not in enabled_types:
        return []

    tagger = _get_tagger()
    if tagger is None:
        return []

    detections = []

    for region in text_regions:
        text = region.get("text", "")
        if not text or not text.strip():
            continue

        bbox = region.get("bbox_pt", region.get("bbox", []))
        region_conf = region.get("confidence", 1.0)

        words = tagger(text)

        # Build token list with positions
        tokens = []
        current_pos = 0
        for word in words:
            surface = word.surface
            if not surface:
                current_pos += 1  # skip empty tokens
                continue

            # Find the actual position in text (handle whitespace differences)
            actual_pos = text.find(surface, current_pos)
            if actual_pos < 0:
                actual_pos = current_pos
            current_pos = actual_pos + len(surface)

            pos_fields = _get_pos_fields(word)
            is_name, subcategory = _is_name_token(pos_fields)

            tokens.append({
                "surface": surface,
                "start": actual_pos,
                "end": actual_pos + len(surface),
                "is_name": is_name,
                "subcategory": subcategory,
                "pos": pos_fields,
            })

        # Group consecutive name tokens into name detections
        i = 0
        while i < len(tokens):
            if tokens[i]["is_name"]:
                group = [tokens[i]]
                j = i + 1

                # Extend group while next token is also a name
                while j < len(tokens) and tokens[j]["is_name"]:
                    # Check if tokens are adjacent (no more than 1 char gap)
                    if tokens[j]["start"] <= group[-1]["end"] + 1:
                        group.append(tokens[j])
                        j += 1
                    else:
                        break

                name_text = "".join(t["surface"] for t in group)
                name_start = group[0]["start"]
                name_end = group[-1]["end"]

                confidence = _calculate_name_confidence(group, text)
                final_conf = round(min(region_conf * confidence, 1.0), 4)

                detection = {
                    "id": str(uuid.uuid4()),
                    "text": name_text,
                    "bbox_pt": list(bbox) if bbox else [],
                    "type": "name",
                    "confidence": final_conf,
                    "source": "auto",
                    "rule_id": "name_mecab",
                    "rule_name": "氏名（MeCab形態素解析）",
                    "start": name_start,
                    "end": name_end,
                    "original_region_id": region.get("id"),
                }
                detections.append(detection)
                i = j
            else:
                i += 1

    return detections


def detect_names_text(text, enabled_types=None):
    """Detect person names in a single text string (convenience function for testing).

    Args:
        text: Input text string.
        enabled_types: Optional list of PII types to detect.

    Returns:
        List of detected name match dicts.
    """
    regions = [{"text": text, "bbox_pt": []}]
    return detect_names(regions, enabled_types=enabled_types)
