DOM_SCRIPT = r"""
() => {
  const cssPath = (el) => {
    if (!(el instanceof Element)) return "";
    const parts = [];
    while (el && el.nodeType === 1 && parts.length < 6) {
      let selector = el.nodeName.toLowerCase();
      if (el.id) {
        selector += `#${CSS.escape(el.id)}`;
        parts.unshift(selector);
        break;
      }
      const cls = [...el.classList].slice(0, 2).map(c => `.${CSS.escape(c)}`).join("");
      selector += cls;
      const parent = el.parentElement;
      if (parent) {
        const same = [...parent.children].filter(c => c.nodeName === el.nodeName);
        if (same.length > 1) selector += `:nth-of-type(${same.indexOf(el) + 1})`;
      }
      parts.unshift(selector);
      el = el.parentElement;
    }
    return parts.join(" > ");
  };

  const fingerprint = (el) => {
    const t = (el.innerText || "").trim().slice(0, 40);
    return `${el.tagName}:${el.id}:${el.getAttribute("name") || ""}:${t}`.slice(0, 120);
  };

  const isInteractive = (el) => {
    const tag = el.tagName.toLowerCase();
    if (["a", "button", "input", "select", "textarea", "summary"].includes(tag)) return true;
    const role = el.getAttribute("role");
    if (role && ["button", "link", "menuitem", "tab", "checkbox"].includes(role)) return true;
    return el.hasAttribute("onclick") || el.tabIndex >= 0;
  };

  const nodes = [...document.querySelectorAll("html, body, img, a, button, input, select, textarea, form, h1, h2, h3, h4, h5, h6, nav, header, footer, [role], [onclick]")];
  const extra = [...document.querySelectorAll("div, span, p, li")].slice(0, 80);
  const all = [...new Set([...nodes, ...extra])].slice(0, 400);

  const elements = all.map(el => {
    const rect = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    const visible = style.display !== "none" && style.visibility !== "hidden" && rect.width + rect.height > 0;
    const labeled = !!(el.labels && el.labels.length) || !!el.getAttribute("aria-label");
    const attrs = {};
    for (const name of el.getAttributeNames()) attrs[name] = el.getAttribute(name) || "";
    if (el.tagName === "IMG") {
      attrs.naturalWidth = String(el.naturalWidth || 0);
      attrs.broken = String(el.naturalWidth === 0);
      attrs.src = el.currentSrc || el.src || "";
      if (!el.hasAttribute("alt")) delete attrs.alt;
      else attrs.alt = el.getAttribute("alt") || "";
    }
    if (el.tagName === "FORM") {
      attrs.hasRequired = String(!!el.querySelector("[required]"));
      attrs.novalidate = String(el.noValidate);
    }
    if (labeled) attrs.labeled = "true";
    return {
      selector: cssPath(el),
      fingerprint: fingerprint(el),
      tag: el.tagName.toLowerCase(),
      role: el.getAttribute("role"),
      text: (el.innerText || el.getAttribute("aria-label") || "").trim().slice(0, 120),
      href: el.getAttribute("href"),
      type: el.getAttribute("type"),
      name: el.getAttribute("name"),
      id: el.id || null,
      visible,
      interactive: isInteractive(el),
      disabled: !!el.disabled,
      box: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
      styles: {
        overflow: style.overflow,
        position: style.position,
        zIndex: style.zIndex,
        textOverflow: style.textOverflow,
        display: style.display,
      },
      attributes: attrs,
    };
  });

  return {
    url: location.href,
    title: document.title,
    html_lang: document.documentElement.getAttribute("lang"),
    scroll_width: document.documentElement.scrollWidth,
    client_width: document.documentElement.clientWidth,
    scroll_height: document.documentElement.scrollHeight,
    client_height: document.documentElement.clientHeight,
    elements,
  };
}
"""
