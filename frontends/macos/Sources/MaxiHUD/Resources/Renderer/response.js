(() => {
  'use strict';
  const root = document.getElementById('response');
  const copyButtons = new Map();
  let sequence = 0;
  let lastHeight = 0;
  const send = value => window.webkit?.messageHandlers?.hud?.postMessage(value);
  DOMPurify.addHook('uponSanitizeAttribute', (node, attribute) => {
    if (attribute.attrName === 'style') {
      attribute.keepAttr = /^(TH|TD)$/.test(node.nodeName) && /^\s*text-align:\s*(left|center|right);?\s*$/.test(attribute.attrValue);
    }
  });
  function resize() {
    // WebKit can pause animation frames while the panel is occluded. Layout
    // measurement must still reach SwiftUI before its first visible frame.
    const height = Math.ceil(root.getBoundingClientRect().height);
    if (height === lastHeight) return;
    lastHeight = height;
    send({ type: 'height', height });
  }
  window.copyFinished = (id, success) => {
    const button = copyButtons.get(id);
    if (!button) return;
    button.textContent = success ? 'Copied' : 'Try again';
    button.setAttribute('aria-label', success ? 'Code copied' : 'Copy code');
    setTimeout(() => { button.textContent = 'Copy'; button.setAttribute('aria-label', 'Copy code'); }, 1800);
  };
  function previewDocument(source) {
    // Each preview has a separate opaque origin and no network/file access.
    // Place this policy before user HTML, including any user-supplied <head>.
    const policy = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; font-src data:; connect-src 'none'; frame-src 'none'; form-action 'none'; base-uri 'none'";
    return '<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="' + policy + '"><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{font:14px system-ui;margin:16px;color:#181b23;background:white}button,input,select,textarea{font:inherit}img{max-width:100%}</style></head><body>' + source + '</body></html>';
  }
  window.renderMarkdown = source => {
    copyButtons.clear();
    // A standalone HTML document gets the same explicit Code / Preview controls.
    const standaloneHTML = /^\s*(?:<!doctype\s+html|<html[\s>])/i.test(source);
    const fragment = standaloneHTML ? document.createDocumentFragment() : DOMPurify.sanitize(
      marked.parse(source, { gfm: true, breaks: false }),
      { RETURN_DOM_FRAGMENT: true, USE_PROFILES: { html: true },
        FORBID_TAGS: ['style', 'script', 'iframe', 'form', 'button', 'textarea', 'select', 'meta', 'link'],
        ADD_TAGS: ['input'], ADD_ATTR: ['checked', 'disabled', 'type'],
        FORBID_ATTR: ['srcdoc', 'id', 'name'] }
    );
    root.replaceChildren(fragment);
    if (standaloneHTML) {
      const pre = document.createElement('pre');
      const code = document.createElement('code');
      code.className = 'language-html'; code.textContent = source;
      pre.append(code); root.append(pre);
    }
    root.querySelectorAll('input').forEach(input => {
      // GFM task lists are display-only; never permit response HTML form controls.
      if (input.type !== 'checkbox') input.remove(); else input.disabled = true;
    });
    root.querySelectorAll('a').forEach(link => {
      const href = link.getAttribute('href') || '';
      if (!/^(https?:|mailto:|#)/i.test(href)) link.removeAttribute('href');
      link.setAttribute('rel', 'noopener noreferrer');
    });
    root.querySelectorAll('table').forEach(table => {
      const wrapper = document.createElement('div'); wrapper.className = 'table-scroll';
      wrapper.setAttribute('role', 'region'); wrapper.setAttribute('aria-label', 'Markdown table'); wrapper.tabIndex = 0;
      table.replaceWith(wrapper); wrapper.append(table);
    });
    root.querySelectorAll('pre > code').forEach(code => {
      const pre = code.parentElement;
      const sourceCode = code.textContent;
      const language = (code.className.match(/language-([\w+-]+)/) || [])[1] || 'text';
      const block = document.createElement('section'); block.className = 'code-block';
      const header = document.createElement('div'); header.className = 'code-header';
      const label = document.createElement('span'); label.textContent = language;
      const copy = document.createElement('button'); copy.type = 'button'; copy.textContent = 'Copy';
      copy.setAttribute('aria-label', 'Copy code');
      const id = ++sequence; copyButtons.set(id, copy);
      copy.addEventListener('click', () => send({ type: 'copy', text: sourceCode, id }));
      header.append(label, copy);
      pre.replaceWith(block); block.append(header, pre);
      if (hljs.getLanguage(language)) {
        code.innerHTML = hljs.highlight(sourceCode, { language, ignoreIllegals: true }).value;
      }
      if (['html', 'htm', 'html5'].includes(language.toLowerCase())) {
        const toggle = document.createElement('button'); toggle.type = 'button'; toggle.textContent = 'Preview';
        toggle.setAttribute('aria-label', 'Preview HTML'); toggle.setAttribute('aria-expanded', 'false');
        const preview = document.createElement('div'); preview.className = 'preview'; preview.hidden = true;
        toggle.addEventListener('click', () => {
          const opening = preview.hidden;
          if (opening && !preview.firstChild) {
            const description = document.createElement('div'); description.className = 'preview-label';
            description.textContent = 'Interactive HTML preview · local assets only';
            const frame = document.createElement('iframe'); frame.title = 'Interactive HTML preview';
            frame.setAttribute('sandbox', 'allow-scripts'); frame.setAttribute('referrerpolicy', 'no-referrer');
            frame.srcdoc = previewDocument(sourceCode);
            preview.append(description, frame);
          }
          preview.hidden = !opening; pre.hidden = opening;
          toggle.textContent = opening ? 'Code' : 'Preview';
          toggle.setAttribute('aria-label', opening ? 'Show HTML code' : 'Preview HTML');
          toggle.setAttribute('aria-expanded', String(opening)); resize();
        });
        header.append(toggle); block.append(preview);
      }
    });
    resize();
  };
  new ResizeObserver(resize).observe(root);
  root.addEventListener('load', resize, true);
  root.addEventListener('toggle', resize, true);
})();
