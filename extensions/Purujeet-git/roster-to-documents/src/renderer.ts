function escapeHtml(value: RowValue): string {
  var text = String(value == null ? "" : value);
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function compareCondition(left: RowValue, operator: string, rightRaw: string): boolean {
  var right = rightRaw.trim().replace(/^['\"]|['\"]$/g, "");
  var leftString = String(left == null ? "" : left);
  var leftNumber = Number(leftString);
  var rightNumber = Number(right);
  var bothNumbers = leftString !== "" && right !== "" && !isNaN(leftNumber) && !isNaN(rightNumber);

  switch (operator) {
    case "==": return bothNumbers ? leftNumber === rightNumber : leftString === right;
    case "!=": return bothNumbers ? leftNumber !== rightNumber : leftString !== right;
    case ">": return bothNumbers ? leftNumber > rightNumber : leftString > right;
    case ">=": return bothNumbers ? leftNumber >= rightNumber : leftString >= right;
    case "<": return bothNumbers ? leftNumber < rightNumber : leftString < right;
    case "<=": return bothNumbers ? leftNumber <= rightNumber : leftString <= right;
    default: return false;
  }
}

function evaluateCondition(expression: string, data: Record<string, RowValue>): boolean {
  var trimmed = expression.trim();
  var match = trimmed.match(/^([A-Za-z0-9_ -]+)\s*(==|!=|>=|<=|>|<)\s*(.+)$/);
  if (match) return compareCondition(data[match[1].trim()], match[2], match[3]);
  var value = data[trimmed];
  return !(value === null || value === undefined || String(value).trim() === "" || value === false || value === 0);
}

function renderTemplate(template: string, data: Record<string, RowValue>): string {
  var rendered = template;
  // Support both the documented `{{...}}` syntax and the single-brace syntax
  // used by the original checked-in templates.
  var conditionalPattern = /\{\{#if\s+([^}]+)\}\}([\s\S]*?)\{\{\/if\}\}|\{#if\s+([^}]+)\}([\s\S]*?)\{\/if\}/g;
  rendered = rendered.replace(conditionalPattern, function (_match: string, expression: string, body: string, singleExpression: string, singleBody: string) {
    var condition = expression || singleExpression;
    var content = body || singleBody;
    return evaluateCondition(condition, data) ? content : "";
  });
  rendered = rendered.replace(/\{\{\s*([A-Za-z0-9_ -]+)\s*\}\}|\{\s*([A-Za-z0-9_ -]+)\s*\}/g, function (_match: string, doubleKey: string, singleKey: string) {
    var key = doubleKey || singleKey;
    return escapeHtml(data[key.trim()]);
  });
  return rendered;
}
