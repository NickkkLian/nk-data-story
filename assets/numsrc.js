(function () {
  'use strict';
  if (window.NkSources) return;

  var manifest = { sources: Object.create(null), inputs: [], not_checked: [] };
  var panel, heading, hint, active = null, activeId = null;
  var warned = new Set();
  var started = false;

  function node(tag, text, className) {
    var el = document.createElement(tag);
    if (text !== undefined) el.textContent = String(text);
    if (className) el.setAttribute('class', className);
    return el;
  }

  function uniqueId(base) {
    var id = base, index = 0;
    while (document.getElementById(id)) id = base + '-' + (++index);
    return id;
  }

  function decorate(el) {
    el.classList.add('nk-src');
    if (!el.matches('a[href],area[href],button,input,select,textarea,summary,[tabindex]') &&
        !el.isContentEditable) el.setAttribute('tabindex', '0');
    el.setAttribute('role', 'button');
    el.setAttribute('aria-haspopup', 'dialog');
    el.setAttribute('aria-expanded', el === active ? 'true' : 'false');
    var described = (el.getAttribute('aria-describedby') || '').split(/\s+/).filter(Boolean);
    if (described.indexOf(hint.id) < 0) described.push(hint.id);
    el.setAttribute('aria-describedby', described.join(' '));
  }

  function refresh() {
    if (!started) return;
    document.querySelectorAll('[data-nk-src]').forEach(decorate);
    if (active && (!active.isConnected || active.getAttribute('data-nk-src') !== activeId)) close(false);
  }

  function close(restore) {
    if (!active) return;
    var previous = active;
    active = null;
    activeId = null;
    panel.hidden = true;
    previous.setAttribute('aria-expanded', 'false');
    if (restore && previous.isConnected) previous.focus();
  }

  function section(title) {
    panel.appendChild(node('h3', title, 'nk-src-section'));
  }

  function render() {
    var focused = panel.contains(document.activeElement);
    var onClose = document.activeElement && document.activeElement.classList.contains('nk-src-close');
    while (panel.firstChild) panel.removeChild(panel.firstChild);
    var entry = manifest.sources[activeId];
    heading = node('h2', entry ? entry.label : 'Number source', 'nk-src-heading');
    heading.setAttribute('id', panel.getAttribute('aria-labelledby'));
    heading.setAttribute('tabindex', '-1');
    panel.appendChild(heading);
    panel.appendChild(node('p', entry && entry.value !== undefined ? entry.value : active.textContent,
      'nk-src-value'));
    if (!entry) {
      panel.appendChild(node('p', 'No source recorded for this number.'));
      if (!warned.has(activeId)) {
        warned.add(activeId);
        console.warn('No source recorded for number: ' + activeId);
      }
    } else {
      section('Source');
      var list = node('ul', undefined, 'nk-src-list');
      (entry.from || []).forEach(function (item) {
        var parts = [];
        if (item.input) {
          var input = (manifest.inputs || []).find(function (candidate) { return candidate.id === item.input; });
          parts.push(input ? input.name : item.input);
          if (input && input.sha256) parts.push('sha256 ' + input.sha256.slice(0, 12));
          if (input && input.synthetic) parts.push('synthetic');
        }
        if (item.rows) {
          parts.push('Rows ' + item.rows.join(', '));
          if (item.rows_total > item.rows.length) parts.push('and ' + (item.rows_total - item.rows.length) + ' more');
        } else if (item.rows_total !== undefined) parts.push('Rows total: ' + item.rows_total);
        if (item.cells) parts.push('Cells: ' + (Array.isArray(item.cells) ? item.cells.join(', ') : item.cells));
        if (item.text) parts.push(item.text);
        list.appendChild(node('li', parts.join('; ')));
      });
      panel.appendChild(list);
      section('How');
      var how = entry.how || {};
      panel.appendChild(node('p', how.kind || '', 'nk-src-kind'));
      panel.appendChild(node('p', how.text || '', 'nk-src-mono'));
      if (how.command) {
        panel.appendChild(node('p', 'Command', 'nk-src-kind'));
        panel.appendChild(node('p', how.command, 'nk-src-mono'));
      }
      section('Not checked');
      list = node('ul', undefined, 'nk-src-list');
      (entry.not_checked || []).concat(manifest.not_checked || []).forEach(function (item) {
        list.appendChild(node('li', item));
      });
      panel.appendChild(list);
    }
    var button = node('button', 'Close', 'nk-src-close');
    button.setAttribute('type', 'button');
    panel.appendChild(button);
    if (focused) (onClose ? button : heading).focus();
  }

  function position() {
    if (!active) return;
    panel.style.left = '';
    panel.style.top = '';
    if (window.innerWidth < 600) return;
    var anchor = active.getBoundingClientRect();
    var bounds = panel.getBoundingClientRect();
    var top = anchor.bottom + 8;
    if (top + bounds.height > window.innerHeight - 8) top = anchor.top - bounds.height - 8;
    panel.style.left = Math.max(8, Math.min(anchor.left, window.innerWidth - bounds.width - 8)) + 'px';
    panel.style.top = Math.max(8, Math.min(top, window.innerHeight - bounds.height - 8)) + 'px';
  }

  function open(el) {
    if (active) active.setAttribute('aria-expanded', 'false');
    active = el;
    activeId = el.getAttribute('data-nk-src');
    decorate(el);
    render();
    panel.hidden = false;
    position();
    heading.focus();
  }

  function traced(target) {
    return target instanceof Element ? target.closest('[data-nk-src]') : null;
  }

  function start() {
    if (started || !document.body) return;
    started = true;
    var block = document.getElementById('nk-sources');
    try {
      var parsed = block ? JSON.parse(block.textContent) : null;
      if (parsed && parsed.sources && typeof parsed.sources === 'object') {
        // Entries set or updated before start (a live page's first render) are laid over the manifest's own.
        var early = manifest.sources;
        parsed.sources = Object.assign(Object.create(null), parsed.sources);
        Object.keys(early).forEach(function (id) {
          parsed.sources[id] = Object.assign({}, parsed.sources[id] || {}, early[id]);
        });
        manifest = parsed;
      }
    } catch (error) { /* An absent or malformed manifest still permits an explanation. */ }
    // A null prototype also keeps unknown ids from inheriting object properties.
    manifest.sources = Object.assign(Object.create(null), manifest.sources);
    hint = node('span', 'Show where this number comes from', 'nk-src-hint');
    hint.setAttribute('id', uniqueId('nk-src-hint'));
    // hidden: never drawn or printed (an in-flow 1px box added a page to a printed deck), still read as a description
    hint.hidden = true;
    document.body.appendChild(hint);
    panel = node('div', undefined, 'nk-src-panel');
    panel.setAttribute('role', 'dialog');
    panel.setAttribute('aria-modal', 'false');
    panel.setAttribute('aria-labelledby', uniqueId('nk-src-heading'));
    panel.hidden = true;
    document.body.appendChild(panel);
    refresh();
    new MutationObserver(refresh).observe(document.body, {
      childList: true, subtree: true, attributes: true, attributeFilter: ['data-nk-src']
    });
    document.addEventListener('click', function (event) {
      if (panel.contains(event.target)) {
        if (event.target.closest('.nk-src-close')) close(true);
        return;
      }
      var el = traced(event.target);
      if (el) { event.preventDefault(); open(el); }
      else close(false);
    });
    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' && active) { event.preventDefault(); close(true); return; }
      var el = traced(event.target);
      if (el && (event.key === 'Enter' || event.key === ' ')) {
        event.preventDefault();
        open(el);
      }
    });
    panel.addEventListener('focusout', function (event) {
      if (event.relatedTarget && !panel.contains(event.relatedTarget)) close(false);
      else if (!event.relatedTarget) {
        Promise.resolve().then(function () {
          if (active && !panel.contains(document.activeElement)) close(false);
        });
      }
    });
    window.addEventListener('resize', position);
    // A printout carries no panel: the numbers print as plain text.
    window.addEventListener('beforeprint', function () { close(false); });
    document.addEventListener('scroll', function (event) {
      if (active && event.target !== panel && !panel.contains(event.target)) close(false);
    }, true);
  }

  window.NkSources = {
    refresh: refresh,
    set: function (id, entry) {
      manifest.sources[id] = entry;
      if (activeId === id) { render(); position(); }
    },
    update: function (id, patch) {
      this.set(id, Object.assign({}, manifest.sources[id] || {}, patch));
    }
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, { once: true });
  else start();
}());
