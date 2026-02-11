#!/bin/bash
# Validate that a 1Password item exists and has the expected fields
# Usage: validate-secret-ref.sh <item-name/field-name> [vault]
#        validate-secret-ref.sh <item-name> [vault]

RAW_KEY="$1"
VAULT="${2:-anton}"

if [ -z "$RAW_KEY" ]; then
    echo "Usage: validate-secret-ref.sh <item-name/field-name> [vault]"
    echo "       validate-secret-ref.sh <item-name> [vault]"
    exit 1
fi

# Support combined "item/field" format used by 1Password SDK provider
if [[ "$RAW_KEY" == *"/"* ]]; then
    ITEM_NAME="${RAW_KEY%%/*}"
    FIELD_NAME="${RAW_KEY#*/}"
else
    ITEM_NAME="$RAW_KEY"
    FIELD_NAME=""
fi

# Check if op CLI is available
if ! command -v op &> /dev/null; then
    echo "WARNING: 1Password CLI (op) not installed or not in PATH"
    echo "Cannot validate item existence. Proceeding without validation."
    exit 0
fi

# Check if signed in
if ! op account list &> /dev/null; then
    echo "WARNING: Not signed into 1Password CLI"
    echo "Run 'op signin' to enable validation"
    exit 0
fi

# Try to get the item
ITEM_JSON=$(op item get "$ITEM_NAME" --vault "$VAULT" --format json 2>/dev/null)

if [ $? -ne 0 ]; then
    echo "ERROR: Item '$ITEM_NAME' not found in vault '$VAULT'"
    echo "Available items in vault:"
    op item list --vault "$VAULT" --format json 2>/dev/null | jq -r '.[].title' | head -10
    exit 1
fi

echo "OK: Item '$ITEM_NAME' exists in vault '$VAULT'"

# If field name provided, check it exists
if [ -n "$FIELD_NAME" ]; then
    FIELD_EXISTS=$(echo "$ITEM_JSON" | jq -r --arg f "$FIELD_NAME" '.fields[] | select(.label == $f or .id == $f) | .label' 2>/dev/null)

    if [ -z "$FIELD_EXISTS" ]; then
        echo "ERROR: Field '$FIELD_NAME' not found in item '$ITEM_NAME'"
        echo "Available fields:"
        echo "$ITEM_JSON" | jq -r '.fields[].label' 2>/dev/null | grep -v "^$"
        exit 1
    fi

    echo "OK: Field '$FIELD_NAME' exists"
fi

echo "Validation passed"
exit 0
