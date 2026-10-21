"use strict";
globalThis.SentraEnrollmentDom = function(command) {
  // These functions are inlined from the same reviewed Python enrollment source.
  /*__EXTRACTORS__*/
  const visible = element => Boolean(element.getClientRects().length) &&
    getComputedStyle(element).visibility !== "hidden" && getComputedStyle(element).display !== "none";
  const normalized = value => String(value || "").replace(/\s+/g, " ").trim();
  function matches(value, specification) {
    if (!specification) return true;
    if (typeof specification.literal === "string") return normalized(value) === normalized(specification.literal);
    if (typeof specification.source !== "string" || specification.source.length > 2048 || !/^(?:i)?$/.test(specification.flags)) return false;
    return new RegExp(specification.source, specification.flags).test(normalized(value));
  }
  function role(element) {
    if (element.hasAttribute("role")) return element.getAttribute("role").split(/\s+/)[0];
    const tag = element.tagName.toLowerCase();
    if (tag === "button" || (tag === "input" && /^(button|submit|reset)$/.test(element.type))) return "button";
    if (tag === "input" && element.type === "radio") return "radio";
    if (tag === "input" && element.type === "checkbox") return "checkbox";
    if (tag === "textarea" || (tag === "input" && /^(text|email|search|tel|url|password)$/.test(element.type))) return "textbox";
    if (tag === "option") return "option";
    if (tag === "select") return "combobox";
    if (tag === "dialog") return "dialog";
    if (tag === "a" && element.hasAttribute("href")) return "link";
    return "";
  }
  function name(element) {
    const labelled = (element.getAttribute("aria-labelledby") || "").trim().split(/\s+/).filter(Boolean);
    if (labelled.length) return labelled.map(id => document.getElementById(id)?.textContent || "").join(" ");
    if (element.hasAttribute("aria-label")) return element.getAttribute("aria-label");
    if (element.labels?.length) return [...element.labels].map(label => label.textContent || "").join(" ");
    return element.innerText || element.getAttribute("title") || element.getAttribute("placeholder") || element.value || "";
  }
  function locate(steps) {
    let nodes = [document];
    if (!Array.isArray(steps) || steps.length > 16) throw Error("bridge_selector_ambiguous");
    for (const step of steps) {
      switch (step.kind) {
        case "css": {
          if (typeof step.selector !== "string" || step.selector.length > 2048) throw Error("bridge_selector_ambiguous");
          const selectors = step.selector.split(",").map(part => part.trim());
          nodes = nodes.flatMap(scope => selectors.flatMap(selector => {
            const onlyVisible = selector.includes(":visible");
            return [...scope.querySelectorAll(selector.replace(/:visible/g, ""))].filter(element => !onlyVisible || visible(element));
          }));
          break;
        }
        case "role": nodes = nodes.flatMap(scope => [...scope.querySelectorAll("*")].filter(element =>
          role(element) === step.role && visible(element) && matches(name(element), step.name))); break;
        case "text": nodes = nodes.flatMap(scope => [...scope.querySelectorAll("*")].filter(element =>
          visible(element) && matches(element.textContent, step.name) && ![...element.children].some(child =>
            visible(child) && matches(child.textContent, step.name)))); break;
        case "nth": nodes = Number.isSafeInteger(step.index) && step.index >= 0 && nodes[step.index] ? [nodes[step.index]] : []; break;
        case "visible": nodes = nodes.filter(element => visible(element) === step.value); break;
        default: throw Error("bridge_selector_ambiguous");
      }
      nodes = [...new Set(nodes)];
      if (nodes.length > 10000) throw Error("bridge_selector_ambiguous");
    }
    return nodes;
  }
  try {
    if (location.origin !== "https://platform.openai.com" ||
        !/^\/settings\/organization\/(?:tunnels|api-keys)(?:\/|$)/.test(location.pathname)) throw Error("bridge_origin_changed");
    if (command.operation === "extract") {
      if (command.kind === "tunnels" && /^\/settings\/organization\/tunnels(?:\/|$)/.test(location.pathname)) return {ok: true, result: extractTunnels()};
      if (command.kind === "new_key" && /^\/settings\/organization\/api-keys(?:\/|$)/.test(location.pathname)) return {ok: true, result: extractKey()};
      throw Error("bridge_origin_changed");
    }
    if (command.operation !== "dom" || !new Set(["count", "visible", "enabled", "checked", "attribute", "text", "click", "pointer_click", "fill", "press", "select_label"]).has(command.action)) {
      throw Error("bridge_selector_ambiguous");
    }
    const nodes = locate(command.steps);
    if (command.action === "count") return {ok: true, result: nodes.length};
    if (command.action === "visible") return {ok: true, result: nodes.length === 1 && visible(nodes[0])};
    if (nodes.length !== 1) throw Error(nodes.length ? "bridge_selector_ambiguous" : "bridge_element_missing");
    const element = nodes[0];
    if (!(element instanceof HTMLElement)) throw Error("bridge_selector_ambiguous");
    const enabled = !element.disabled && element.getAttribute("aria-disabled") !== "true";
    let result = null;
    switch (command.action) {
      case "enabled": result = enabled; break;
      case "checked": result = element.checked === true || element.getAttribute("aria-checked") === "true"; break;
      case "attribute":
        if (!["id", "aria-checked"].includes(command.name)) throw Error("bridge_selector_ambiguous");
        result = element.getAttribute(command.name); break;
      case "text": result = (element.innerText || "").slice(0, 5000); break;
      case "select_label": {
        if (!(element instanceof HTMLSelectElement) || element.multiple || !enabled || !visible(element) ||
            typeof command.label !== "string" || !command.label || command.label.length > 500) throw Error("bridge_element_disabled");
        const options = [...element.options].filter(option => normalized(option.textContent) === normalized(command.label));
        if (options.length !== 1) throw Error(options.length ? "bridge_selector_ambiguous" : "bridge_element_missing");
        const option = options[0];
        if (option.disabled || option.closest("optgroup[disabled]")) throw Error("bridge_element_disabled");
        // Use the browser's native value setter so controlled form libraries
        // receive the same input/change events as a real selection. Option
        // values stay in the browser; only the chosen visible label returns.
        Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value").set.call(element, option.value);
        element.dispatchEvent(new Event("input", {bubbles: true}));
        element.dispatchEvent(new Event("change", {bubbles: true}));
        result = normalized(element.selectedOptions[0]?.textContent || ""); break;
      }
      case "click":
        if (!enabled || !visible(element)) throw Error("bridge_element_disabled");
        element.click(); result = true; break;
      case "pointer_click": {
        if (!enabled || !visible(element)) throw Error("bridge_element_disabled");
        // Custom select triggers/items often handle pointerdown/pointerup,
        // rather than HTMLElement.click(). Keep this a fixed DOM action;
        // no scripts, coordinates or option values come from the client.
        const rect = element.getBoundingClientRect();
        const common = {bubbles: true, cancelable: true, composed: true,
          view: window, button: 0, clientX: rect.left + rect.width / 2,
          clientY: rect.top + rect.height / 2};
        element.focus({preventScroll: true});
        const compatible = element.dispatchEvent(new PointerEvent("pointerdown", {
          ...common, buttons: 1, pointerId: 1, pointerType: "mouse", isPrimary: true}));
        if (compatible) element.dispatchEvent(new MouseEvent("mousedown", {...common, buttons: 1}));
        element.dispatchEvent(new PointerEvent("pointerup", {
          ...common, buttons: 0, pointerId: 1, pointerType: "mouse", isPrimary: true}));
        if (compatible) element.dispatchEvent(new MouseEvent("mouseup", {...common, buttons: 0}));
        element.click(); result = true; break;
      }
      case "fill": {
        if (!enabled || !visible(element) || element.readOnly || !["INPUT", "TEXTAREA"].includes(element.tagName) ||
            /^(?:password|hidden|file)$/.test(element.type) || typeof command.value !== "string" || command.value.length > 2048) throw Error("bridge_element_disabled");
        const prototype = element.tagName === "INPUT" ? HTMLInputElement.prototype : HTMLTextAreaElement.prototype;
        Object.getOwnPropertyDescriptor(prototype, "value").set.call(element, command.value);
        element.dispatchEvent(new Event("input", {bubbles: true}));
        element.dispatchEvent(new Event("change", {bubbles: true})); result = true; break;
      }
      case "press":
        if (command.value !== "Escape") throw Error("bridge_selector_ambiguous");
        element.dispatchEvent(new KeyboardEvent("keydown", {key: "Escape", code: "Escape", bubbles: true}));
        element.dispatchEvent(new KeyboardEvent("keyup", {key: "Escape", code: "Escape", bubbles: true})); result = true; break;
      default: throw Error("bridge_selector_ambiguous");
    }
    return {ok: true, result};
  } catch (error) {
    const safe = new Set(["bridge_origin_changed", "bridge_selector_ambiguous", "bridge_element_missing", "bridge_element_disabled"]);
    return {ok: false, error: safe.has(error.message) ? error.message : "browser_dom_needs_attention"};
  }
};
// Firefox clones the completion value of a packaged injection. The assignment
// above evaluates to a function, which cannot cross that boundary.
void 0;
