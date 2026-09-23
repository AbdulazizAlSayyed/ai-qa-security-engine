"""Turning a rendered DOM into structured application facts.

One script, defined once as a module constant, runs in the page. It is
**read-only**: it queries the document, reads attributes and computes
references. It never writes to the DOM, never submits anything, never reads
an input's value, and never touches storage, cookies or the network.

The script is a constant on purpose, and a test asserts it stays one. No
target data, no operator input and no configuration is ever interpolated
into it, so there is no path by which anything outside this file becomes
code running in the target. Its only input is a limits object passed as
*data*, which is what keeps one enormous page from filling the map.

Selector strategy, best first: ``data-testid``, a unique ``id``, a unique
``name``, an accessible role and name, and only then a short CSS path. The
strategy used is recorded next to every reference, so a later phase can tell
a stable one from a brittle one instead of finding out at execution time.
"""

from __future__ import annotations

from typing import Any, Mapping

from app.engines.discovery.models import (
    DiscoveredElement,
    DiscoveredField,
    DiscoveredForm,
    ElementKind,
    SelectorStrategy,
    is_sensitive_field,
)

#: The one script this module runs. Constant, read-only, never interpolated.
EXTRACTION_SCRIPT = """
(limits) => {
  const MAX_TEXT = 200;

  const clean = (value) =>
    (value == null ? "" : String(value)).replace(/\\s+/g, " ").trim().slice(0, MAX_TEXT);

  const attr = (el, name) => clean(el.getAttribute(name));

  const textOf = (el) => clean(el.innerText || el.textContent || "");

  const isVisible = (el) => {
    if (!el || !el.getClientRects) return false;
    if (el.hidden) return false;
    const style = window.getComputedStyle(el);
    if (!style) return true;
    if (style.display === "none" || style.visibility === "hidden") return false;
    return true;
  };

  const testIdOf = (el) =>
    attr(el, "data-testid") || attr(el, "data-test-id") || attr(el, "data-test") || "";

  const testIdAttrOf = (el) => {
    if (attr(el, "data-testid")) return "data-testid";
    if (attr(el, "data-test-id")) return "data-test-id";
    if (attr(el, "data-test")) return "data-test";
    return "";
  };

  const quote = (value) => String(value).replace(/"/g, '\\\\"');

  const unique = (selector) => {
    try {
      return document.querySelectorAll(selector).length === 1;
    } catch (error) {
      return false;
    }
  };

  const cssPath = (el) => {
    const parts = [];
    let node = el;
    let hops = 0;
    while (node && node.nodeType === 1 && hops < 6) {
      const tag = node.tagName.toLowerCase();
      if (tag === "html" || tag === "body") break;
      const parent = node.parentElement;
      if (!parent) { parts.unshift(tag); break; }
      const siblings = Array.prototype.filter.call(
        parent.children, (child) => child.tagName === node.tagName
      );
      const index = siblings.indexOf(node) + 1;
      parts.unshift(siblings.length > 1 ? tag + ":nth-of-type(" + index + ")" : tag);
      node = parent;
      hops += 1;
    }
    return parts.join(" > ");
  };

  const labelFor = (el) => {
    const aria = attr(el, "aria-label");
    if (aria) return aria;
    const labelledBy = attr(el, "aria-labelledby");
    if (labelledBy) {
      const referenced = document.getElementById(labelledBy);
      if (referenced) return textOf(referenced);
    }
    if (el.id) {
      try {
        const explicit = document.querySelector('label[for="' + quote(el.id) + '"]');
        if (explicit) return textOf(explicit);
      } catch (error) { /* an id that is not a valid selector */ }
    }
    const wrapping = el.closest ? el.closest("label") : null;
    if (wrapping) return textOf(wrapping);
    return "";
  };

  const implicitRole = (el) => {
    const tag = el.tagName.toLowerCase();
    if (tag === "a") return el.hasAttribute("href") ? "link" : "";
    if (tag === "button") return "button";
    if (tag === "select") return "combobox";
    if (tag === "textarea") return "textbox";
    if (tag === "input") {
      const type = (el.getAttribute("type") || "text").toLowerCase();
      if (type === "checkbox") return "checkbox";
      if (type === "radio") return "radio";
      if (type === "submit" || type === "button" || type === "reset") return "button";
      return "textbox";
    }
    return "";
  };

  const reference = (el) => {
    const testId = testIdOf(el);
    if (testId) {
      return { selector: "[" + testIdAttrOf(el) + '="' + quote(testId) + '"]', strategy: "test_id" };
    }
    const id = clean(el.id);
    if (id) {
      const selector = '[id="' + quote(id) + '"]';
      if (unique(selector)) return { selector: selector, strategy: "id" };
    }
    const name = attr(el, "name");
    if (name) {
      const selector = el.tagName.toLowerCase() + '[name="' + quote(name) + '"]';
      if (unique(selector)) return { selector: selector, strategy: "name" };
    }
    const role = attr(el, "role") || implicitRole(el);
    const accessible = labelFor(el) || textOf(el);
    if (role && accessible) {
      return {
        selector: "role=" + role + '[name="' + quote(accessible) + '"]',
        strategy: "role_and_name",
      };
    }
    return { selector: cssPath(el), strategy: "css_path" };
  };

  const kindOf = (el) => {
    const tag = el.tagName.toLowerCase();
    if (tag === "a") return el.hasAttribute("href") ? "link" : "";
    if (tag === "button") return "button";
    if (tag === "select") return "select";
    if (tag === "textarea") return "textarea";
    if (tag === "input") {
      const type = (el.getAttribute("type") || "text").toLowerCase();
      if (type === "checkbox") return "checkbox";
      if (type === "radio") return "radio";
      if (type === "hidden") return "";
      if (type === "submit" || type === "button" || type === "reset") return "button";
      return "input";
    }
    if (attr(el, "role") === "button") return "button";
    return "";
  };

  const describeField = (el) => {
    const ref = reference(el);
    const tag = el.tagName.toLowerCase();
    let type = tag;
    if (tag === "input") type = (el.getAttribute("type") || "text").toLowerCase();
    return {
      name: attr(el, "name"),
      field_id: clean(el.id),
      type: type,
      label: labelFor(el),
      placeholder: attr(el, "placeholder"),
      required: el.required === true || el.hasAttribute("required"),
      selector: ref.selector,
      selector_strategy: ref.strategy,
      input_mode: attr(el, "inputmode"),
      autocomplete: attr(el, "autocomplete"),
    };
  };

  const links = [];
  const anchors = document.querySelectorAll("a[href]");
  for (let i = 0; i < anchors.length && links.length < limits.max_links; i += 1) {
    const anchor = anchors[i];
    links.push({ href: clean(anchor.getAttribute("href")), text: textOf(anchor) });
  }

  const forms = [];
  const formNodes = document.querySelectorAll("form");
  for (let i = 0; i < formNodes.length && forms.length < limits.max_forms; i += 1) {
    const node = formNodes[i];
    const ref = reference(node);
    const fields = [];
    const controls = node.querySelectorAll("input, select, textarea");
    for (let j = 0; j < controls.length && fields.length < limits.max_fields; j += 1) {
      const control = controls[j];
      if ((control.getAttribute("type") || "").toLowerCase() === "hidden") continue;
      fields.push(describeField(control));
    }
    forms.push({
      form_id: clean(node.id),
      name: attr(node, "name"),
      action: attr(node, "action"),
      method: (attr(node, "method") || "get").toLowerCase(),
      selector: ref.selector,
      fields: fields,
    });
  }

  const elements = [];
  const candidates = document.querySelectorAll(
    "a[href], button, input, select, textarea, [role='button']"
  );
  for (let i = 0; i < candidates.length && elements.length < limits.max_elements; i += 1) {
    const el = candidates[i];
    const kind = kindOf(el);
    if (!kind) continue;
    if (!isVisible(el)) continue;
    const ref = reference(el);
    elements.push({
      kind: kind,
      text: labelFor(el) || textOf(el),
      element_id: clean(el.id),
      name: attr(el, "name"),
      selector: ref.selector,
      selector_strategy: ref.strategy,
      role: attr(el, "role") || implicitRole(el),
      disabled: el.disabled === true || el.hasAttribute("disabled"),
      in_form: Boolean(el.closest && el.closest("form")),
    });
  }

  return {
    title: clean(document.title),
    links: links,
    forms: forms,
    elements: elements,
  };
}
"""


def limits_argument(
    *, max_links: int, max_forms: int, max_elements: int, max_fields: int = 60
) -> dict[str, int]:
    """The data the script is given. Data, never code."""
    return {
        "max_links": max_links,
        "max_forms": max_forms,
        "max_elements": max_elements,
        "max_fields": max_fields,
    }


def _strategy(value: Any) -> SelectorStrategy:
    try:
        return SelectorStrategy(str(value))
    except ValueError:
        return SelectorStrategy.CSS_PATH


def parse_field(raw: Mapping[str, Any]) -> DiscoveredField:
    """One control, as structure. A value is never read, so none can leak."""
    name = str(raw.get("name") or "")
    field_id = str(raw.get("field_id") or "")
    field_type = str(raw.get("type") or "")
    label = str(raw.get("label") or "")
    return DiscoveredField(
        name=name,
        field_id=field_id,
        type=field_type,
        label=label,
        placeholder=str(raw.get("placeholder") or ""),
        required=bool(raw.get("required")),
        selector=str(raw.get("selector") or ""),
        selector_strategy=_strategy(raw.get("selector_strategy")),
        input_mode=str(raw.get("input_mode") or ""),
        autocomplete=str(raw.get("autocomplete") or ""),
        sensitive=is_sensitive_field(name, field_id, field_type, label),
    )


def parse_form(raw: Mapping[str, Any], page_url: str) -> DiscoveredForm:
    return DiscoveredForm(
        page_url=page_url,
        form_id=str(raw.get("form_id") or ""),
        name=str(raw.get("name") or ""),
        action=str(raw.get("action") or ""),
        method=str(raw.get("method") or "get").lower(),
        selector=str(raw.get("selector") or ""),
        fields=[parse_field(item) for item in raw.get("fields") or []],
    )


def parse_element(raw: Mapping[str, Any], page_url: str) -> DiscoveredElement | None:
    try:
        kind = ElementKind(str(raw.get("kind")))
    except ValueError:
        return None
    return DiscoveredElement(
        page_url=page_url,
        kind=kind,
        text=str(raw.get("text") or ""),
        element_id=str(raw.get("element_id") or ""),
        name=str(raw.get("name") or ""),
        selector=str(raw.get("selector") or ""),
        selector_strategy=_strategy(raw.get("selector_strategy")),
        role=str(raw.get("role") or ""),
        disabled=bool(raw.get("disabled")),
        in_form=bool(raw.get("in_form")),
    )


def parse_extraction(
    raw: Mapping[str, Any], page_url: str
) -> tuple[str, list[dict[str, str]], list[DiscoveredForm], list[DiscoveredElement]]:
    """Translate the script's answer into the engine's own types."""
    title = str(raw.get("title") or "")
    links = [
        {"href": str(item.get("href") or ""), "text": str(item.get("text") or "")}
        for item in raw.get("links") or []
    ]
    forms = [parse_form(item, page_url) for item in raw.get("forms") or []]
    elements = [
        element
        for element in (parse_element(item, page_url) for item in raw.get("elements") or [])
        if element is not None
    ]
    return title, links, forms, elements
