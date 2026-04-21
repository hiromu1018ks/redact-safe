# Custom Rules Directory

Place custom detection rule files in this directory. Supported formats:

- **YAML** (`.yaml`, `.yml`) - Same format as the bundled `detection_rules.yaml`
- **JSON** (`.json`) - JSON format with the same schema

## Rule Schema

Each rule must have:
- `id` - Unique identifier (string)
- `name` - Display name (string)
- `type` - PII type: `name`, `address`, `phone`, `my_number`, `email`, `birth_date`, `corporate_number`, `custom`
- `pattern` - Regular expression pattern (string)

Optional fields:
- `confidence` - Detection confidence 0.0-1.0 (default: 0.8)
- `enabled` - Whether the rule is active (default: true)
- `description` - Description of the rule

## Override Behavior

If a custom rule has the same `id` as a bundled rule, the custom rule overrides it.
Custom rules with new IDs are added alongside the bundled rules.

## Safety

All custom rules are validated before loading:
- Invalid regex patterns are rejected
- Patterns with potential catastrophic backtracking are rejected
- Confidence values must be between 0.0 and 1.0
