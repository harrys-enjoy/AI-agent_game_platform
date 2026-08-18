_UNSUPPORTED_STRICT_KEYWORDS = {
    "exclusiveMinimum",
    "exclusiveMaximum",
    "minimum",
    "maximum",
    "minLength",
    "maxLength",
    "pattern",
    "format",
    "multipleOf",
}


def assert_strict_schema_safe(model: type) -> None:
    _check_node(model.model_json_schema())


def _check_node(node) -> None:
    if isinstance(node, dict):
        found = _UNSUPPORTED_STRICT_KEYWORDS & node.keys()
        if found:
            raise AssertionError(
                f"Schema node contains unsupported strict-mode keyword(s) {sorted(found)}: {node}"
            )
        for value in node.values():
            _check_node(value)
    elif isinstance(node, list):
        for item in node:
            _check_node(item)
