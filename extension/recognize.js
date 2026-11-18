// Runs in the extension's isolated world. Read current DOM properties on every scan.
globalThis.singleChoiceReader ??= (() => {
  const radio = 'input[type="radio"], [role="radio"]';
  const otherChoice = 'input[type="checkbox"], [role="checkbox"], [role="switch"]';
  const toggles = '[aria-pressed], [data-selected]';
  const stateAttr = el => el.matches('[role="radio"]') ? "aria-checked"
    : el.hasAttribute("aria-pressed") ? "aria-pressed" : "data-selected";
  const clean = value => (value || "").replace(/\s+/g, " ").trim();
  const text = el => clean(el?.innerText);
  const isNative = el => el.matches('input[type="radio"]');

  function visible(el) {
    return !!el && !el.closest('[hidden], [inert], [aria-hidden="true"]') &&
      el.checkVisibility({visibilityProperty: true, opacityProperty: true});
  }

  function labelledBy(el) {
    const ids = clean(el.getAttribute("aria-labelledby"));
    return ids ? ids.split(" ").map(id => el.ownerDocument.getElementById(id)).filter(Boolean) : [];
  }

  function illustrations(roots) {
    const images = new Set();
    for (const root of roots) {
      const media = "img, svg, canvas";
      const nodes = root.matches(media) ? [root] : root.querySelectorAll(media);
      for (const node of nodes) {
        if (visible(node) && !node.parentElement?.closest("svg") &&
            !node.closest('[role="presentation"], [role="none"]')) images.add(node);
      }
    }
    return [...images];
  }

  function optionContent(el) {
    const refs = labelledBy(el);
    const labels = isNative(el) ? [...el.labels].filter(visible) : [el];
    const roots = [...labels, ...refs];
    const row = el.parentElement;
    if (isNative(el) && row.matches("li, div, p, span") && row.querySelectorAll(radio).length === 1 &&
        !row.querySelector('button, a, select, textarea, input:not([type="radio"])')) roots.push(row);
    const label = clean(refs.map(text).join(" ")) || clean(el.getAttribute("aria-label")) ||
      clean(labels.map(text).join(" ")) || (roots.includes(row) ? text(row) : "");
    return {label, images: illustrations(roots)};
  }

  function usable(el) {
    if (el.matches(":disabled") || el.closest('[aria-disabled="true"], [inert], [hidden]')) return false;
    const labels = isNative(el) ? Array.from(el.labels || []) : [];
    if (!visible(el) && !labels.some(visible)) return false;
    // A custom radio implemented as a form submitter must never be activated.
    if (!isNative(el) && (el.closest('a[href], summary, label') ||
        el.querySelector('button, input, textarea, select, a[href], label'))) return false;
    const button = el.closest("button, input[type=submit], input[type=image], input[type=reset]");
    if (button?.form && button.type !== "button") return false;
    return isNative(el) || ["true", "false"].includes(el.getAttribute(stateAttr(el)));
  }

  function groups(doc) {
    const groups = [];
    const nativeForms = new Map();
    const ariaGroups = new Map();
    for (const el of doc.querySelectorAll(radio)) {
      let map, key;
      if (isNative(el)) {
        if (!el.name) continue; // Nameless radios do not form an exclusive native group.
        if (!nativeForms.has(el.form)) nativeForms.set(el.form, new Map());
        map = nativeForms.get(el.form);
        key = el.name;
      } else {
        map = ariaGroups;
        key = el.closest('[role="radiogroup"]');
        if (!key) continue;
      }
      if (!map.has(key)) {
        const elements = [];
        map.set(key, elements);
        groups.push(elements);
      }
      map.get(key).push(el);
    }
    // Without a radio role, accept only a complete row of sibling choices
    // exposing the same state attribute; scan() also requires a single-choice prompt.
    const seen = new Set();
    for (const el of doc.querySelectorAll(toggles)) {
      const parent = el.parentElement;
      if (!parent || seen.has(parent) || el.matches(radio)) continue;
      seen.add(parent);
      const siblings = Array.from(parent.children);
      if (siblings.every(node => node.matches(toggles) && !node.matches(radio) &&
          stateAttr(node) === stateAttr(el))) groups.push(siblings);
    }
    groups.sort((a, b) => a[0].compareDocumentPosition(b[0]) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1);
    return groups;
  }

  function questionContent(elements, optionImages) {
    const first = elements[0];
    const boundary = 'fieldset, [role="radiogroup"]';
    if (!elements.every(el => el.closest(boundary) === first.closest(boundary))) return null;
    const set = new Set(elements);
    const images = new Set();
    function collect(roots) {
      for (const image of illustrations(roots)) {
        if (!optionImages.has(image)) images.add(image);
      }
    }
    let scope = first.parentElement;
    while (scope && !elements.every(el => scope.contains(el))) scope = scope.parentElement;
    for (; scope && scope !== first.ownerDocument.body; scope = scope.parentElement) {
      if (scope.querySelector(otherChoice) ||
          Array.from(scope.querySelectorAll(radio)).some(el => !set.has(el))) break;

      // Walk the leading branches before the first radio. Keep the prompt local
      // and reject competing prompts rather than pairing a heading with a later question.
      const candidates = [];
      for (const child of scope.children) {
        if (child.contains(first)) break;
        if (!visible(child) || child.matches('label, nav, header, footer, aside, button, input') ||
            child.querySelector('label, input, button, select, textarea, nav, aside')) continue;
        const value = text(child);
        const heading = child.matches('legend, h1, h2, h3, h4, h5, h6, [role="heading"]');
        const prompt = !child.matches("a") &&
          (heading || /[?？]|单选|下列|以下|选择|哪一|哪项|哪个|[（(]\s*[)）]/u.test(value));
        if (value && prompt) candidates.push(value);
        // Question figures are often links to a larger version of the image.
        if (prompt || !value || child.matches("figure, picture")) collect([child]);
      }
      if (scope.matches('fieldset, [role="radiogroup"], [role="group"]')) {
        const refs = labelledBy(scope);
        collect(refs);
        // A figure may sit between an external question heading and its labelled group.
        for (const ref of refs) {
          if (scope.parentElement !== ref.parentElement ||
              !(ref.compareDocumentPosition(scope) & Node.DOCUMENT_POSITION_FOLLOWING)) continue;
          for (let node = ref.nextElementSibling; node && node !== scope; node = node.nextElementSibling) {
            if (node.matches("img, picture, figure, svg, canvas")) collect([node]);
          }
        }
        const label = clean(refs.map(text).join(" ")) || clean(scope.getAttribute("aria-label")) ||
          text(scope.querySelector(":scope > legend"));
        if (label) return {label, images: [...images]};
      }
      if (candidates.length === 1) return {label: candidates[0], images: [...images]};
      if (candidates.length > 1) return null;
      if (scope.matches(boundary) && images.size) break;
    }
    return images.size ? {label: "", images: [...images]} : null;
  }

  // Intern long data URLs once. Re-scans and pause/resume use the same identities.
  const sources = new Map();
  function sourceId(src) {
    if (!sources.has(src)) sources.set(src, sources.size + 1);
    return sources.get(src);
  }
  function contentKey(part) {
    return JSON.stringify([part.label, part.images.map(img =>
      [sourceId(img.currentSrc || img.src), sourceId(img.getAttribute("src"))])]);
  }

  function scan(doc = document) {
    const questions = [];
    for (const elements of groups(doc)) {
      if (elements.length < 2 || !elements.every(usable)) continue;
      const parts = elements.map(optionContent);
      const prompt = questionContent(elements, new Set(parts.flatMap(p => p.images)));
      if (!prompt) continue;
      const stem = prompt.label;
      if (!elements[0].matches(radio) && !/单选|单项选择|single[ -]choice|choose one/i.test(stem)) continue;
      if (parts.some(p => !p.label && !p.images.length)) continue;
      const allParts = [prompt, ...parts];
      const images = allParts.flatMap((p, part) => p.images.map(node => ({part, node})));
      if (images.length > 12 || images.some(({node}) => node.localName !== "img")) continue;
      const keys = parts.map(contentKey);
      if (new Set(keys).size !== keys.length) continue;
      questions.push({stem, options: parts.map(p => p.label), images, elements,
        key: JSON.stringify([contentKey(prompt), keys])});
    }
    for (const frame of doc.querySelectorAll("iframe")) {
      if (visible(frame) && frame.contentDocument) questions.push(...scan(frame.contentDocument));
    }
    return questions;
  }

  function selected(el) {
    return isNative(el) ? el.checked : el.getAttribute(stateAttr(el)) === "true";
  }

  function find(key) {
    const matches = scan().filter(question => question.key === key);
    return matches.length === 1 ? matches[0] : null;
  }

  function findUnanswered(key) {
    const question = find(key);
    return question && !question.elements.some(selected) ? question : null;
  }

  async function choose(key, index, running) {
    const question = findUnanswered(key);
    const target = question?.elements[index];
    if (!target || !running()) return;
    target.click();

    // Some frameworks replace every option node or apply state asynchronously.
    let stableSince = null;
    const deadline = performance.now() + 1500;
    while (performance.now() < deadline) {
      if (!running()) return;
      const live = find(key);
      if (live?.elements.every((el, i) => selected(el) === (index === i))) {
        stableSince ??= performance.now();
        if (performance.now() - stableSince >= 200) return;
      } else {
        stableSince = null;
      }
      await new Promise(resolve => setTimeout(resolve, 55));
    }
    throw new Error("未能确认页面勾选状态，请查看原题。");
  }
  return {scan, findUnanswered, choose};
})();
