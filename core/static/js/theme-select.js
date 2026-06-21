/*
 * Reusable themed dropdown. Wraps a native <select> (kept as the source of
 * truth for value/forms) with a button + panel styled from the site theme, so
 * no white system dropdown is shown. Use by adding `data-theme-select` to a
 * <select>, or call window.ThemeSelect.enhance(selectEl).
 */
(function () {
  'use strict';

  let uid = 0;
  // Only one themed dropdown may be open at a time.
  let openCloser = null;

  function enhance(select) {
    if (!select || select.dataset.themed === '1') return;
    // The select must be attached so we can wrap it in place. Enhancing a
    // detached node would otherwise throw and abort the caller mid-render.
    if (!select.parentNode) return;
    select.dataset.themed = '1';
    uid += 1;
    const panelId = 'theme-select-panel-' + uid;

    const wrap = document.createElement('div');
    wrap.className = 'theme-select';
    select.parentNode.insertBefore(wrap, select);
    wrap.appendChild(select);
    select.classList.add('theme-select__native');

    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'theme-select__button';
    button.setAttribute('aria-haspopup', 'listbox');
    button.setAttribute('aria-expanded', 'false');
    button.setAttribute('aria-controls', panelId);
    if (select.disabled) button.disabled = true;
    const label = document.createElement('span');
    label.className = 'theme-select__label';
    button.appendChild(label);
    const caret = document.createElement('span');
    caret.className = 'theme-select__caret';
    caret.setAttribute('aria-hidden', 'true');
    button.appendChild(caret);
    wrap.appendChild(button);

    const panel = document.createElement('div');
    panel.className = 'theme-select__panel';
    panel.id = panelId;
    panel.setAttribute('role', 'listbox');
    panel.hidden = true;
    wrap.appendChild(panel);

    let open = false;
    let activeIndex = -1;
    let scrollCloser = null;

    // The panel is absolutely positioned, so a scrollable/clipping ancestor
    // (e.g. the sidebar filter list) would cut it off. Detect that case so the
    // panel can be promoted to fixed positioning instead.
    function clippingAncestor(el) {
      let node = el.parentElement;
      while (node && node !== document.body) {
        const oy = getComputedStyle(node).overflowY;
        if (oy === 'auto' || oy === 'scroll' || oy === 'hidden') return node;
        node = node.parentElement;
      }
      return null;
    }

    function positionFixed() {
      const r = button.getBoundingClientRect();
      panel.style.position = 'fixed';
      panel.style.left = r.left + 'px';
      panel.style.width = r.width + 'px';
      panel.style.right = 'auto';
      const ph = panel.offsetHeight;
      let top = r.bottom + 6;
      if (top + ph > window.innerHeight - 8 && r.top - ph - 6 > 8) {
        top = r.top - ph - 6;  // flip upward when there is no room below
      }
      panel.style.top = top + 'px';
    }

    function clearFixed() {
      panel.style.position = '';
      panel.style.top = '';
      panel.style.left = '';
      panel.style.width = '';
      panel.style.right = '';
    }

    function syncLabel() {
      const opt = select.options[select.selectedIndex];
      label.textContent = opt ? opt.textContent : '';
      label.classList.toggle('theme-select__label--placeholder', !!opt && opt.value === '');
    }

    function buildOptions() {
      panel.innerHTML = '';
      Array.from(select.options).forEach((opt, index) => {
        const item = document.createElement('button');
        item.type = 'button';
        item.className = 'theme-select__option';
        item.textContent = opt.textContent;
        item.setAttribute('role', 'option');
        if (opt.disabled) {
          item.classList.add('theme-select__option--disabled');
          item.disabled = true;
        }
        if (index === select.selectedIndex) item.classList.add('theme-select__option--selected');
        item.addEventListener('click', () => {
          if (opt.disabled) return;
          select.selectedIndex = index;
          select.dispatchEvent(new Event('change', { bubbles: true }));
          syncLabel();
          markSelected();
          close();
          button.focus();
        });
        panel.appendChild(item);
      });
    }

    function markSelected() {
      Array.from(panel.children).forEach((el, i) =>
        el.classList.toggle('theme-select__option--selected', i === select.selectedIndex));
    }

    function setActive(index) {
      const items = Array.from(panel.children);
      if (!items.length) return;
      activeIndex = (index + items.length) % items.length;
      items.forEach((el, i) => el.classList.toggle('theme-select__option--active', i === activeIndex));
      const el = items[activeIndex];
      if (el) el.scrollIntoView({ block: 'nearest' });
    }

    function openPanel() {
      if (button.disabled) return;
      if (openCloser && openCloser !== close) openCloser();  // single open at a time
      open = true;
      panel.hidden = false;
      wrap.classList.add('theme-select--open');
      button.setAttribute('aria-expanded', 'true');
      openCloser = close;
      setActive(select.selectedIndex >= 0 ? select.selectedIndex : 0);
      // If a scroll/clip ancestor would cut the panel, float it with fixed
      // positioning and close on any ancestor scroll (like a native select).
      if (clippingAncestor(wrap)) {
        positionFixed();
        scrollCloser = function () { close(); };
        window.addEventListener('scroll', scrollCloser, true);
        window.addEventListener('resize', scrollCloser, true);
      }
      document.addEventListener('mousedown', onDoc, true);
      document.addEventListener('keydown', onKey, true);
    }

    function close() {
      open = false;
      panel.hidden = true;
      wrap.classList.remove('theme-select--open');
      button.setAttribute('aria-expanded', 'false');
      clearFixed();
      if (scrollCloser) {
        window.removeEventListener('scroll', scrollCloser, true);
        window.removeEventListener('resize', scrollCloser, true);
        scrollCloser = null;
      }
      if (openCloser === close) openCloser = null;
      document.removeEventListener('mousedown', onDoc, true);
      document.removeEventListener('keydown', onKey, true);
    }

    function chooseActive() {
      const items = Array.from(panel.children);
      const el = items[activeIndex];
      if (el && !el.disabled) el.click();
    }

    function onDoc(event) {
      if (!wrap.contains(event.target)) close();
    }

    function onKey(event) {
      if (event.key === 'Escape') { close(); button.focus(); }
      else if (event.key === 'ArrowDown') { event.preventDefault(); setActive(activeIndex + 1); }
      else if (event.key === 'ArrowUp') { event.preventDefault(); setActive(activeIndex - 1); }
      else if (event.key === 'Home') { event.preventDefault(); setActive(0); }
      else if (event.key === 'End') { event.preventDefault(); setActive(panel.children.length - 1); }
      else if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); chooseActive(); }
    }

    button.addEventListener('click', () => { open ? close() : openPanel(); });
    button.addEventListener('keydown', (e) => {
      if (!open && (e.key === 'ArrowDown' || e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); openPanel(); }
    });
    select.addEventListener('change', () => { syncLabel(); markSelected(); });

    buildOptions();
    syncLabel();
    // Allow callers that mutate <option>s to refresh the themed view.
    select.themeSelectRefresh = () => { buildOptions(); syncLabel(); };
  }

  function enhanceAll(root) {
    (root || document).querySelectorAll('select[data-theme-select]').forEach(enhance);
  }

  window.ThemeSelect = { enhance, enhanceAll };
  document.addEventListener('DOMContentLoaded', () => enhanceAll());
})();
