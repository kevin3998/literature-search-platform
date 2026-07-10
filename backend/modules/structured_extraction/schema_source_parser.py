from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from markdown_it import MarkdownIt

from .schema_contract import MAX_REQUIREMENTS, MAX_SOURCE_CHARS, SchemaRequirement, SourceSpan
from .schema_normalizer import normalize_field_tree, slugify_key

_LIST_ITEM_RE = re.compile(r"^(?P<indent>\s*)(?:[-+*]|\d+[.)])\s+(?P<body>.+?)\s*$")
_CODE_FIELD_RE = re.compile(r"^`(?P<name>[^`]+)`\s*:?(?P<rest>.*)$")
_BOLD_FIELD_RE = re.compile(r"^\*\*(?P<name>[^*]+)\*\*\s*:?(?P<rest>.*)$")
_PLAIN_FIELD_RE = re.compile(r"^(?P<name>[A-Za-z][A-Za-z0-9_ /-]{0,63})\s*:\s*(?P<rest>.*)$")
_ENUM_RE = re.compile(r"\[(?P<values>(?:\s*['\"][^'\"]+['\"]\s*,?)+)\]")


@dataclass
class ParsedSource:
    source_format: str
    source_text: str
    requirements: list[dict[str, Any]]
    field_tree: list[dict[str, Any]]


def parse_schema_source(text: str, source_format: str = "auto") -> ParsedSource:
    value = str(text or "")
    if not value.strip():
        raise ValueError("schema_source_required")
    if len(value) > MAX_SOURCE_CHARS:
        raise ValueError("schema_source_too_large")
    selected = detect_source_format(value) if source_format in {"", "auto"} else source_format
    if selected == "json":
        parsed = _parse_json_source(value)
    elif selected == "markdown":
        parsed = _parse_markdown_source(value)
    elif selected == "natural_language":
        parsed = _parse_natural_language(value)
    else:
        raise ValueError("unsupported_schema_source_format")
    if len(parsed.requirements) > MAX_REQUIREMENTS:
        raise ValueError("schema_requirement_limit_exceeded")
    return parsed


def detect_source_format(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith(("{", "[")):
        try:
            json.loads(stripped)
            return "json"
        except json.JSONDecodeError:
            pass
    tokens = MarkdownIt("commonmark").parse(text)
    if any(token.type in {"heading_open", "bullet_list_open", "ordered_list_open"} for token in tokens):
        return "markdown"
    if re.search(r"(?m)^\s*(?:[-+*]|\d+[.)])\s+", text):
        return "markdown"
    return "natural_language"


def _parse_json_source(text: str) -> ParsedSource:
    data = json.loads(text)
    if _looks_like_json_schema(data):
        tree = _tree_from_json_schema(data)
    elif isinstance(data, dict) and ("field_tree" in data or "fieldTree" in data):
        tree, _changes = normalize_field_tree(data)
    elif isinstance(data, list):
        tree, _changes = normalize_field_tree(data)
    elif isinstance(data, dict):
        tree = _tree_from_example(data)
    else:
        raise ValueError("unsupported_json_schema_source")
    requirements = _requirements_from_tree(tree, source_text=text)
    return ParsedSource(source_format="json", source_text=text, requirements=requirements, field_tree=tree)


def _looks_like_json_schema(data: Any) -> bool:
    return isinstance(data, dict) and isinstance(data.get("properties"), dict) and data.get("type", "object") == "object"


def _tree_from_json_schema(schema: dict[str, Any]) -> list[dict[str, Any]]:
    required = set(schema.get("required") or [])
    nodes = []
    for index, (key, spec) in enumerate((schema.get("properties") or {}).items(), start=1):
        spec = spec if isinstance(spec, dict) else {}
        raw_type = spec.get("type") or "string"
        allowed_values = spec.get("enum") or []
        children: list[dict[str, Any]] = []
        node_type = raw_type
        if raw_type == "object":
            children = _tree_from_json_schema(spec)
            node_type = "dict" if not children and spec.get("additionalProperties") else "object"
        elif raw_type == "array":
            item_spec = spec.get("items") or {}
            if isinstance(item_spec, dict) and (item_spec.get("type") == "object" or item_spec.get("properties")):
                children = _tree_from_json_schema(item_spec)
                node_type = "list_object"
            elif isinstance(item_spec, dict) and isinstance(item_spec.get("enum"), list):
                node_type = "multi_enum"
                allowed_values = item_spec["enum"]
            else:
                node_type = "list_string"
        elif isinstance(spec.get("enum"), list):
            node_type = "enum"
        elif raw_type == "string" and spec.get("format") in {"date", "date-time"}:
            node_type = "date"
        nodes.append({
            "key": slugify_key(key),
            "label": spec.get("title") or key,
            "type": node_type,
            "description": spec.get("description") or "",
            "required": key in required,
            "allowed_values": allowed_values,
            "order": index,
            "children": children,
            "origin": "source_declared",
        })
    tree, _changes = normalize_field_tree(nodes)
    return tree


def _tree_from_example(data: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = []
    for index, (key, value) in enumerate(data.items(), start=1):
        node_type = "string"
        children: list[dict[str, Any]] = []
        if isinstance(value, dict):
            node_type = "object"
            children = _tree_from_example(value)
        elif isinstance(value, list):
            if value and isinstance(value[0], dict):
                node_type = "list_object"
                children = _tree_from_example(value[0])
            else:
                node_type = "list_string"
        elif isinstance(value, bool):
            node_type = "boolean"
        elif isinstance(value, (int, float)):
            node_type = "number"
        nodes.append({"key": slugify_key(key), "label": key, "type": node_type, "children": children, "order": index, "origin": "source_declared"})
    return nodes


def _parse_markdown_source(text: str) -> ParsedSource:
    tokens = MarkdownIt("commonmark").parse(text)
    item_ends = {
        token.map[0]: max(token.map[1], 1)
        for token in tokens
        if token.type == "list_item_open" and token.map
    }
    lines = text.splitlines(keepends=True)
    offsets = _line_offsets(lines)
    requirements: list[dict[str, Any]] = []
    stack: list[tuple[int, str, str]] = []
    continuation_parent: tuple[int, int, str, str, str] | None = None
    req_index = 0
    for line_number, raw_line in enumerate(lines, start=1):
        match = _LIST_ITEM_RE.match(raw_line.rstrip("\r\n"))
        if not match:
            continuation = raw_line.strip()
            continuation_indent = len(raw_line) - len(raw_line.lstrip(" \t"))
            if not continuation or re.match(r"^#{1,6}\s", continuation) or continuation.startswith("```"):
                if re.match(r"^#{1,6}\s", continuation):
                    continuation_parent = None
                continue
            within_list_item = bool(
                continuation_parent
                and line_number - 1 < continuation_parent[1]
                and continuation_indent > continuation_parent[0]
            )
            if within_list_item:
                _parent_indent, _parent_end, parent_id, parent_path, parent_kind = continuation_parent
                for inline_name in _inline_declared_names(continuation):
                    req_index += 1
                    inline_key = slugify_key(inline_name, fallback=f"field_{req_index}")
                    requirements.append(SchemaRequirement(
                        requirement_id=f"req_{req_index:04d}",
                        kind="field" if parent_kind == "field" else "constraint",
                        raw_name=inline_name,
                        source_path=f"{parent_path}.{inline_key}" if parent_path else inline_key,
                        source_text=continuation,
                        source_span=SourceSpan(start=offsets[line_number - 1], end=offsets[line_number - 1] + len(raw_line), start_line=line_number, end_line=line_number),
                        parent_requirement_id=parent_id,
                    ).model_dump())
                req_index += 1
                requirements.append(SchemaRequirement(
                    requirement_id=f"req_{req_index:04d}",
                    kind="constraint" if parent_kind == "field" else "global_instruction",
                    source_path=parent_path,
                    source_text=continuation,
                    source_span=SourceSpan(start=offsets[line_number - 1], end=offsets[line_number - 1] + len(raw_line), start_line=line_number, end_line=line_number),
                    parent_requirement_id=parent_id,
                ).model_dump())
            else:
                req_index += 1
                kind = _prose_requirement_kind(continuation)
                identity_candidates = _identity_candidates(continuation) if kind == "record_identity" else []
                requirements.append(SchemaRequirement(
                    requirement_id=f"req_{req_index:04d}",
                    kind=kind,
                    raw_name=_best_identity_candidate(identity_candidates),
                    source_text=continuation,
                    source_span=SourceSpan(start=offsets[line_number - 1], end=offsets[line_number - 1] + len(raw_line), start_line=line_number, end_line=line_number),
                    constraints=_identity_candidate_constraints(identity_candidates),
                ).model_dump())
            continue
        body = match.group("body").strip()
        field = _field_declaration(body)
        req_index += 1
        requirement_id = f"req_{req_index:04d}"
        indent = len(match.group("indent").replace("\t", "    "))
        item_end = item_ends.get(line_number - 1, line_number)
        while stack and stack[-1][0] >= indent:
            stack.pop()
        parent_id = stack[-1][1] if stack else None
        parent_path = stack[-1][2] if stack else ""
        if field:
            name, description = field
            key = slugify_key(name, fallback=f"field_{req_index}")
            source_path = f"{parent_path}.{key}" if parent_path else key
            kind = _declared_requirement_kind(name, description)
            constraints = _constraints_from_text(body)
            requirements.append(SchemaRequirement(
                requirement_id=requirement_id,
                kind=kind,
                raw_name=name,
                source_path=source_path,
                source_text=body,
                source_span=SourceSpan(start=offsets[line_number - 1], end=offsets[line_number - 1] + len(raw_line), start_line=line_number, end_line=line_number),
                shape_hint=_shape_hint(body),
                parent_requirement_id=parent_id,
                constraints=constraints,
            ).model_dump())
            if kind == "field":
                stack.append((indent, requirement_id, source_path))
            inline_names = [value for value in _inline_declared_names(body) if value != name]
            is_container_declaration = bool(re.match(r"^(?:`[^`]+`|\*\*[^*]+\*\*)\s*:", body))
            for inline_name in inline_names:
                req_index += 1
                inline_id = f"req_{req_index:04d}"
                inline_key = slugify_key(inline_name, fallback=f"field_{req_index}")
                inline_parent_id = requirement_id if kind == "field" and is_container_declaration else parent_id
                inline_parent_path = source_path if kind == "field" and is_container_declaration else parent_path
                inline_path = f"{inline_parent_path}.{inline_key}" if inline_parent_path else inline_key
                requirements.append(SchemaRequirement(
                    requirement_id=inline_id,
                    kind="field" if kind == "field" else "constraint",
                    raw_name=inline_name.strip(),
                    source_path=inline_path,
                    source_text=body,
                    source_span=SourceSpan(start=offsets[line_number - 1], end=offsets[line_number - 1] + len(raw_line), start_line=line_number, end_line=line_number),
                    parent_requirement_id=inline_parent_id,
                ).model_dump())
            continuation_parent = (indent, item_end, requirement_id, source_path, kind)
        else:
            kind = _prose_requirement_kind(body)
            identity_candidates = _identity_candidates(body) if kind == "record_identity" else []
            requirements.append(SchemaRequirement(
                requirement_id=requirement_id,
                kind=kind,
                raw_name=_best_identity_candidate(identity_candidates),
                source_text=body,
                source_path=parent_path,
                source_span=SourceSpan(start=offsets[line_number - 1], end=offsets[line_number - 1] + len(raw_line), start_line=line_number, end_line=line_number),
                parent_requirement_id=parent_id,
                constraints=_identity_candidate_constraints(identity_candidates),
            ).model_dump())
            continuation_parent = (indent, item_end, requirement_id, parent_path, "global_instruction")
    if not requirements:
        return _parse_natural_language(text)
    tree = _tree_from_requirements(requirements)
    return ParsedSource(source_format="markdown", source_text=text, requirements=requirements, field_tree=tree)


def _parse_natural_language(text: str) -> ParsedSource:
    requirements = []
    offsets = _line_offsets(text.splitlines(keepends=True))
    index = 0
    cursor = 0
    for line_number, paragraph in enumerate(text.splitlines(), start=1):
        paragraph = paragraph.strip()
        if not paragraph:
            cursor += 1
            continue
        for sentence in re.split(r"(?<=[。！？.!?])\s+", paragraph):
            sentence = sentence.strip()
            if not sentence:
                continue
            index += 1
            start = text.find(sentence, cursor)
            end = start + len(sentence)
            cursor = max(cursor, end)
            kind = _prose_requirement_kind(sentence)
            identity_candidates = _identity_candidates(sentence) if kind == "record_identity" else []
            requirements.append(SchemaRequirement(
                requirement_id=f"req_{index:04d}",
                kind=kind,
                raw_name=_best_identity_candidate(identity_candidates),
                source_text=sentence,
                source_span=SourceSpan(start=max(0, start), end=end, start_line=line_number, end_line=line_number),
                constraints=_identity_candidate_constraints(identity_candidates),
            ).model_dump())
    return ParsedSource(source_format="natural_language", source_text=text, requirements=requirements, field_tree=[])


def _field_declaration(body: str) -> tuple[str, str] | None:
    for regex in (_CODE_FIELD_RE, _BOLD_FIELD_RE, _PLAIN_FIELD_RE):
        match = regex.match(body)
        if match:
            return match.group("name").strip(), match.groupdict().get("rest", "").strip(" :-")
    return None


def _inline_declared_names(text: str) -> list[str]:
    names = []
    for match in re.finditer(r"`([^`]+)`|\*\*([^*]+)\*\*", text):
        value = (match.group(1) or match.group(2) or "").strip()
        if value and value not in names and not _looks_like_instruction(value, ""):
            names.append(value)
    return names


def _looks_like_instruction(name: str, description: str) -> bool:
    return _declared_requirement_kind(name, description) != "field"


def _declared_requirement_kind(name: str, description: str) -> str:
    cleaned = re.sub(r"[^A-Za-z]", "", name)
    if bool(cleaned) and cleaned.isupper() and len(cleaned) > 3:
        return _prose_requirement_kind(f"{name} {description}")
    instruction_start = r"^(?:avoid|include|exclude|consolidate|identify|select|only|never|do\s+not|must|before|after|return|create|group|separate)\b"
    if re.match(instruction_start, name.strip().lower()) or re.match(instruction_start, description.strip().lower()):
        return _prose_requirement_kind(f"{name} {description}")
    return "field"


def _prose_requirement_kind(text: str) -> str:
    phrase = str(text or "").strip().lower()
    if re.search(r"(?:\bfor\s+each\b|\beach\b|\bper\b).{0,100}\b(?:record|object|entry)\b|\brecord\s+identity\b|\bunique\s+identifier\b|\bone\s+record\b", phrase):
        return "record_identity"
    if re.match(r"^(?:avoid|include|exclude|select|only|never|do\s+not)\b", phrase) or re.search(r"\bonly\s+(?:include|create|extract)\b", phrase):
        return "selection_rule"
    if re.match(r"^(?:consolidate|group|merge|separate)\b", phrase):
        return "grouping_rule"
    return "global_instruction"


def _identity_candidates(text: str) -> list[str]:
    candidates: list[str] = []
    for match in re.finditer(r"`([^`]{1,64})`|\"([^\"\n]{1,64})\"|'([^'\n]{1,64})'", str(text or "")):
        value = next((group for group in match.groups() if group is not None), "").strip()
        if not value or value in candidates or not re.search(r"[A-Za-z0-9\u4e00-\u9fff]", value):
            continue
        candidates.append(value)
    return candidates


def _best_identity_candidate(candidates: list[str]) -> str:
    if not candidates:
        return ""
    generic_wrappers = {"data", "detail", "details", "field", "fields", "record", "records", "result", "results", "metadata", "object"}

    def score(item: tuple[int, str]) -> tuple[int, int]:
        index, value = item
        key = slugify_key(value, fallback="")
        points = 0
        if key in generic_wrappers:
            points -= 20
        if re.search(r"(?:^|_)(?:id|identifier|name|key|code|uuid)$", key):
            points += 12
        if re.search(r"(?:id|identifier|name|key|code|uuid)$", key):
            points += 8
        return points, -index

    return max(enumerate(candidates), key=score)[1]


def _identity_candidate_constraints(candidates: list[str]) -> list[dict[str, Any]]:
    return [{"type": "identity_candidates", "values": candidates, "text": ""}] if candidates else []


def _shape_hint(text: str) -> str:
    lowered = text.lower()
    if "list of object" in lowered or "array of object" in lowered:
        return "list_object"
    if "list of string" in lowered or "array of string" in lowered:
        return "list_string"
    if "dictionary" in lowered or " key/value" in lowered or " key-value" in lowered or " dict" in lowered:
        return "dict"
    if "choose from" in lowered or _ENUM_RE.search(text):
        return "enum"
    return ""


def _constraints_from_text(text: str) -> list[dict[str, Any]]:
    constraints: list[dict[str, Any]] = []
    enum_match = _ENUM_RE.search(text)
    if enum_match:
        values = re.findall(r"['\"]([^'\"]+)['\"]", enum_match.group("values"))
        if values:
            constraints.append({"type": "allowed_values", "values": values, "text": enum_match.group(0)})
    return constraints


def _tree_from_requirements(requirements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    nodes_by_req: dict[str, dict[str, Any]] = {}
    roots: list[dict[str, Any]] = []
    for requirement in requirements:
        if requirement.get("kind") != "field":
            continue
        source_ids = [requirement["requirement_id"]]
        allowed_values = next((item.get("values") or [] for item in requirement.get("constraints") or [] if item.get("type") == "allowed_values"), [])
        node = {
            "key": slugify_key(requirement.get("raw_name"), fallback=(requirement.get("source_path") or requirement["requirement_id"]).rsplit(".", 1)[-1]),
            "label": requirement.get("raw_name") or requirement["requirement_id"],
            "type": requirement.get("shape_hint") or "string",
            "description": requirement.get("source_text") or "",
            "allowed_values": allowed_values,
            "children": [],
            "source_requirement_ids": source_ids,
            "origin": "source_declared",
        }
        nodes_by_req[requirement["requirement_id"]] = node
        parent = nodes_by_req.get(requirement.get("parent_requirement_id"))
        if parent is not None:
            parent["children"].append(node)
            parent["type"] = "object"
        else:
            roots.append(node)
    tree, _changes = normalize_field_tree(roots)
    return tree


def _requirements_from_tree(tree: list[dict[str, Any]], *, source_text: str) -> list[dict[str, Any]]:
    requirements: list[dict[str, Any]] = []
    counter = 0
    def visit(nodes: list[dict[str, Any]], parent_id: str | None = None, parent_path: str = "") -> None:
        nonlocal counter
        for node in nodes:
            counter += 1
            req_id = f"req_{counter:04d}"
            path = f"{parent_path}.{node['key']}" if parent_path else node["key"]
            requirements.append(SchemaRequirement(
                requirement_id=req_id,
                kind="field",
                raw_name=node.get("label") or node["key"],
                source_path=path,
                source_text=node.get("description") or node.get("label") or node["key"],
                shape_hint=node.get("type") or "string",
                parent_requirement_id=parent_id,
            ).model_dump())
            node["source_requirement_ids"] = [req_id]
            visit(node.get("children") or [], req_id, path)
    visit(tree)
    return requirements


def _line_offsets(lines: list[str]) -> list[int]:
    offsets: list[int] = []
    current = 0
    for line in lines:
        offsets.append(current)
        current += len(line)
    return offsets
