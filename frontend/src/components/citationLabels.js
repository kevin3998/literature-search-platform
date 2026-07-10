export function citationOrdinalLabel(n) {
  return n ? `证据 ${n}` : "证据";
}

export function evidenceIdLabel(id) {
  return id ? `证据ID：${id}` : "证据ID：未提供";
}

export function citationAriaLabel(n) {
  return n ? `文献证据 ${n}` : "文献证据";
}
