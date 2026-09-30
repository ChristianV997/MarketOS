/**
 * A deliberately small HTML tree + accessible-query helper for node:test.
 * It parses the well-formed markup React's server renderer emits and offers
 * Testing-Library-style role/name queries, so tests assert what a user or
 * assistive technology perceives rather than CSS classes or source text.
 */
const VOID = new Set(["area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"]);
const TOKEN = /<!--[\s\S]*?-->|<\/([a-zA-Z][\w-]*)\s*>|<([a-zA-Z][\w-]*)((?:\s+[^\s=>/]+(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+))?)*)\s*(\/?)>/g;
const ATTR = /([^\s=]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?/g;

const ENTITIES = { "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&#x27;": "'", "&#39;": "'", "&nbsp;": " " };
const decode = (text) => text.replace(/&(?:amp|lt|gt|quot|nbsp|#x27|#39);/g, (m) => ENTITIES[m]);

export function parseHtml(html) {
  const root = { tag: "#root", attrs: {}, children: [], parent: null };
  let node = root;
  let last = 0;
  const pushText = (end) => {
    const chunk = html.slice(last, end);
    if (chunk) node.children.push({ text: decode(chunk), parent: node });
  };
  for (const match of html.matchAll(TOKEN)) {
    pushText(match.index);
    last = match.index + match[0].length;
    if (match[0].startsWith("<!--")) continue;
    if (match[1]) {
      let cursor = node;
      while (cursor && cursor.tag !== match[1].toLowerCase()) cursor = cursor.parent;
      if (cursor && cursor.parent) node = cursor.parent;
      continue;
    }
    const tag = match[2].toLowerCase();
    const attrs = {};
    for (const a of (match[3] ?? "").matchAll(ATTR)) attrs[a[1].toLowerCase()] = decode(a[2] ?? a[3] ?? a[4] ?? "");
    const element = { tag, attrs, children: [], parent: node };
    node.children.push(element);
    if (!VOID.has(tag) && match[4] !== "/") node = element;
  }
  pushText(html.length);
  return root;
}

export function textContent(node) {
  if (node.text !== undefined) return node.text.replace(/\s+/g, " ");
  return node.children.map(textContent).join("").replace(/\s+/g, " ").trim();
}

export function walk(node, visit) {
  if (node.text !== undefined) return;
  visit(node);
  node.children.forEach((child) => walk(child, visit));
}

function byId(root, id) {
  let found = null;
  walk(root, (el) => {
    if (el.attrs.id === id) found = el;
  });
  return found;
}

function root(node) {
  let cursor = node;
  while (cursor.parent) cursor = cursor.parent;
  return cursor;
}

export function roleOf(el) {
  if (el.attrs.role) return el.attrs.role;
  const { tag, attrs } = el;
  if (/^h[1-6]$/.test(tag)) return "heading";
  if (tag === "a" && "href" in attrs) return "link";
  if (tag === "input" && attrs.type === "radio") return "radio";
  if (tag === "th") return attrs.scope === "row" ? "rowheader" : "columnheader";
  if (tag === "section" && (attrs["aria-label"] || attrs["aria-labelledby"])) return "region";
  return { button: "button", table: "table", tr: "row", td: "cell", fieldset: "group", ul: "list", li: "listitem" }[tag] ?? null;
}

export function accessibleName(el) {
  if (el.attrs["aria-label"]) return el.attrs["aria-label"].trim();
  if (el.attrs["aria-labelledby"]) {
    const doc = root(el);
    return el.attrs["aria-labelledby"].split(/\s+/).map((id) => textContent(byId(doc, id) ?? { text: "" })).join(" ").trim();
  }
  if (el.tag === "table") {
    const caption = el.children.find((c) => c.tag === "caption");
    return caption ? textContent(caption) : "";
  }
  if (el.tag === "fieldset") {
    const legend = el.children.find((c) => c.tag === "legend");
    return legend ? textContent(legend) : "";
  }
  if (el.tag === "input") {
    let cursor = el.parent;
    while (cursor && cursor.tag !== "label") cursor = cursor.parent;
    return cursor ? textContent(cursor) : "";
  }
  return textContent(el);
}

const matches = (name, expected) => (expected instanceof RegExp ? expected.test(name) : name === expected);

export function queryAllByRole(container, role, { name, level } = {}) {
  const out = [];
  walk(container, (el) => {
    if (roleOf(el) !== role) return;
    if (level !== undefined && el.tag !== `h${level}`) return;
    if (name !== undefined && !matches(accessibleName(el), name)) return;
    out.push(el);
  });
  return out;
}

export function getByRole(container, role, options = {}) {
  const found = queryAllByRole(container, role, options);
  if (found.length !== 1) {
    const all = queryAllByRole(container, role).map((el) => `"${accessibleName(el).slice(0, 60)}"`).join(", ");
    throw new Error(`Expected exactly one ${role}${options.name ? ` named ${options.name}` : ""}, found ${found.length}. Roles present: [${all}]`);
  }
  return found[0];
}

export const queryByRole = (container, role, options = {}) => queryAllByRole(container, role, options)[0] ?? null;

export function queryAllByText(container, text) {
  const out = [];
  walk(container, (el) => {
    const own = el.children.filter((c) => c.text !== undefined).map((c) => c.text).join("").replace(/\s+/g, " ").trim();
    const full = textContent(el);
    if (matches(own, text) || (text instanceof RegExp && text.test(full) && el.children.every((c) => c.text !== undefined))) out.push(el);
  });
  return out;
}

export const hasText = (container, pattern) => pattern instanceof RegExp ? pattern.test(textContent(container)) : textContent(container).includes(pattern);

export function rowsOf(table) {
  const rows = [];
  walk(table, (el) => {
    if (el.tag === "tr" && el.parent && (el.parent.tag === "tbody")) rows.push(el);
  });
  return rows;
}

export const cellsOf = (row) => row.children.filter((c) => c.tag === "td" || c.tag === "th").map(textContent);

/** Text of the <dd>s that follow the <dt> whose text matches `term` (within the same parent). */
export function definitionOf(container, term) {
  let result = null;
  walk(container, (el) => {
    if (result || el.tag !== "dt") return;
    if (!(term instanceof RegExp ? term.test(textContent(el)) : textContent(el) === term)) return;
    const siblings = el.parent.children;
    const values = [];
    for (let i = siblings.indexOf(el) + 1; i < siblings.length && siblings[i].tag === "dd"; i += 1) values.push(textContent(siblings[i]));
    result = values;
  });
  return result;
}
