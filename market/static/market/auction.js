(function () {
  'use strict';

  function getCookie(name) {
    const match = document.cookie.match('(^|;)\\s*' + name + '\\s*=\\s*([^;]+)');
    return match ? decodeURIComponent(match.pop()) : '';
  }

  async function postJSON(url, body) {
    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
      credentials: 'include',
      body: JSON.stringify(body || {}),
    });
    let data = null;
    try { data = await response.json(); } catch (e) {}
    return { ok: response.ok && data && data.success, data: data || {} };
  }

  function firstError(data) {
    if (!data || !data.errors) return 'Не удалось выполнить действие.';
    const errors = data.errors;
    const parts = [];
    Object.keys(errors).forEach((key) => {
      const value = errors[key];
      parts.push(Array.isArray(value) ? value.join(' ') : String(value));
    });
    return parts.join('\n') || 'Не удалось выполнить действие.';
  }

  function money(value) {
    return (value === '' || value == null) ? '' : value;
  }

  // ---- Detail page: share ---------------------------------------------------
  function initShare() {
    document.querySelectorAll('[data-share-button]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const url = window.location.href;
        const title = btn.getAttribute('data-share-title') || document.title;
        if (navigator.share) {
          try { await navigator.share({ title: title, url: url }); return; } catch (e) {}
        }
        try {
          await navigator.clipboard.writeText(url);
          const original = btn.textContent;
          btn.textContent = 'Ссылка скопирована';
          setTimeout(() => { btn.textContent = original; }, 1800);
        } catch (e) {
          window.prompt('Скопируйте ссылку на лот:', url);
        }
      });
    });
  }

  // ---- Detail page: gallery -------------------------------------------------
  function initGallery() {
    document.querySelectorAll('[data-gallery]').forEach((gallery) => {
      const main = gallery.querySelector('[data-gallery-main]');
      if (!main) return;
      gallery.querySelectorAll('[data-gallery-thumb]').forEach((thumb) => {
        thumb.addEventListener('click', () => {
          const src = thumb.getAttribute('data-src');
          if (src) main.src = src;
          gallery.querySelectorAll('[data-gallery-thumb]').forEach((t) => t.classList.remove('is-active'));
          thumb.classList.add('is-active');
        });
      });
    });
  }

  // ---- Detail page: bid / buy-now / edit ------------------------------------
  function initBid() {
    const form = document.querySelector('[data-bid-form]');
    if (!form) return;
    const feedback = form.querySelector('[data-bid-feedback]');
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      if (feedback) feedback.textContent = '';
      const amount = form.querySelector('[name="amount"]').value;
      const { ok, data } = await postJSON(form.getAttribute('data-bid-url'), { amount: amount });
      if (ok) { window.location.reload(); return; }
      if (feedback) feedback.textContent = firstError(data);
    });
  }

  function initBuyNow() {
    document.querySelectorAll('[data-buynow-button]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        if (!window.confirm('Купить лот по цене моментальной покупки?')) return;
        const { ok, data } = await postJSON(btn.getAttribute('data-buynow-url'), {});
        if (ok) { window.location.href = (data && data.lot_url) || window.location.href; return; }
        window.alert(firstError(data));
      });
    });
  }

  function initEdit() {
    const form = document.querySelector('[data-edit-form]');
    if (!form) return;
    const feedback = form.querySelector('[data-edit-feedback]');
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      if (feedback) feedback.textContent = '';
      const payload = {};
      form.querySelectorAll('[name]').forEach((input) => {
        if (input.value !== '') payload[input.name] = input.value;
      });
      const { ok, data } = await postJSON(form.getAttribute('data-edit-url'), payload);
      if (ok) { window.location.reload(); return; }
      if (feedback) feedback.textContent = firstError(data);
    });
  }

  // ---- Create-lot flow ------------------------------------------------------
  function initCreateFlow() {
    const root = document.querySelector('[data-auction-create]');
    if (!root) return;

    const configNode = document.querySelector('[data-create-config]');
    let config = { endpoints: {}, fieldIds: [] };
    try { config = JSON.parse(configNode.textContent); } catch (e) {}

    const errorBox = root.querySelector('[data-create-error]');
    const steps = {};
    root.querySelectorAll('[data-step]').forEach((node) => { steps[node.getAttribute('data-step')] = node; });

    const state = { source: null, card: null, cardData: {}, terms: {} };

    function showStep(name) {
      Object.keys(steps).forEach((key) => steps[key].classList.toggle('is-hidden', key !== name));
      if (errorBox) errorBox.textContent = '';
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }
    function showError(message) { if (errorBox) errorBox.textContent = message; }

    // Step 1 -> choose
    root.querySelectorAll('[data-choose]').forEach((btn) => {
      btn.addEventListener('click', () => {
        state.source = btn.getAttribute('data-choose');
        showStep(state.source === 'archive' ? 'pick' : 'newcard');
      });
    });
    root.querySelectorAll('[data-back]').forEach((btn) => {
      btn.addEventListener('click', () => showStep(btn.getAttribute('data-back')));
    });
    root.querySelectorAll('[data-back-dynamic]').forEach((btn) => {
      btn.addEventListener('click', () => showStep(state.source === 'archive' ? 'pick' : 'newcard'));
    });

    // Step 2a: pick a card
    function renderCardSummary() {
      const host = root.querySelector('[data-card-summary]');
      if (!host) return;
      if (state.source === 'archive' && state.card) {
        host.innerHTML = '';
        const title = document.createElement('div');
        title.className = 'auction-create__summary-title';
        title.textContent = 'Карточка: ' + (state.card.title || '');
        host.appendChild(title);
        if (state.card.description) {
          const desc = document.createElement('div');
          desc.className = 'auction-create__summary-desc';
          desc.textContent = state.card.description;
          host.appendChild(desc);
        }
        host.classList.remove('is-hidden');
      } else {
        host.classList.add('is-hidden');
      }
    }

    function selectArchiveCard(cardEl) {
      state.source = 'archive';
      state.card = {
        id: cardEl.getAttribute('data-card-id'),
        title: cardEl.getAttribute('data-card-title') || '',
        description: cardEl.getAttribute('data-card-description') || '',
      };
      renderCardSummary();
      showStep('terms');
    }

    root.querySelectorAll('[data-card-id]').forEach((card) => {
      card.addEventListener('click', () => selectArchiveCard(card));
    });

    // Step 2b: new card
    const newcardForm = root.querySelector('[data-newcard-form]');
    const newcardNext = root.querySelector('[data-newcard-next]');
    if (newcardNext) {
      newcardNext.addEventListener('click', () => {
        const data = {};
        (config.fieldIds || []).forEach((id) => {
          const node = newcardForm.querySelector('[data-field="' + id + '"]');
          if (node && node.value) data[id] = node.value;
        });
        if (!data.title) { showError('Укажите наименование товара.'); return; }
        state.source = 'new';
        state.cardData = data;
        state.card = null;
        renderCardSummary();
        showStep('terms');
      });
    }

    // Step 3: terms -> preview
    const termsForm = root.querySelector('[data-terms-form]');
    const termsNext = root.querySelector('[data-terms-next]');

    function readTerms() {
      const get = (name) => {
        const node = termsForm.querySelector('[name="' + name + '"]');
        return node ? node.value : '';
      };
      return {
        category: get('category'),
        start_price: get('start_price'),
        min_bid_step: get('min_bid_step'),
        start_at: get('start_at'),
        end_at: get('end_at'),
        buy_now_price: get('buy_now_price'),
        reserve_price: get('reserve_price'),
      };
    }

    function validateTerms(t) {
      if (!t.category) return 'Выберите категорию товара.';
      const sp = parseFloat(t.start_price);
      const step = parseFloat(t.min_bid_step);
      if (!(sp > 0)) return 'Стартовая цена должна быть больше нуля.';
      if (!(step > 0)) return 'Шаг ставки должен быть больше нуля.';
      if (!t.start_at || !t.end_at) return 'Укажите даты начала и завершения торгов.';
      if (new Date(t.end_at) <= new Date(t.start_at)) return 'Завершение должно быть позже начала.';
      if (t.buy_now_price && parseFloat(t.buy_now_price) < sp) return 'Цена «Купить сейчас» не может быть ниже стартовой.';
      return '';
    }

    function buildPreview(t) {
      const title = state.source === 'archive' ? (state.card && state.card.title) : (state.cardData.title || '');
      const rows = [
        ['Источник', state.source === 'archive' ? 'Карточка из архива' : 'Новая карточка'],
        ['Наименование', title || '—'],
        ['Категория', termsForm.querySelector('[name="category"] option:checked').textContent],
        ['Стартовая цена', money(t.start_price) + ' ₽'],
        ['Шаг ставки', money(t.min_bid_step) + ' ₽'],
        ['Начало', t.start_at.replace('T', ' ')],
        ['Завершение', t.end_at.replace('T', ' ')],
      ];
      if (t.buy_now_price) rows.push(['Купить сейчас', t.buy_now_price + ' ₽']);
      const preview = root.querySelector('[data-preview]');
      preview.innerHTML = '';
      rows.forEach((row) => {
        const div = document.createElement('div');
        div.className = 'auction-create__preview-row';
        const dt = document.createElement('span'); dt.textContent = row[0];
        const dd = document.createElement('b'); dd.textContent = row[1];
        div.appendChild(dt); div.appendChild(dd);
        preview.appendChild(div);
      });
    }

    if (termsNext) {
      termsNext.addEventListener('click', () => {
        const t = readTerms();
        const error = validateTerms(t);
        if (error) { showError(error); return; }
        state.terms = t;
        buildPreview(t);
        showStep('preview');
      });
    }

    // Step 4: publish
    function buildPayload(mode) {
      const t = state.terms;
      const payload = {
        mode: mode,
        category: t.category,
        start_price: t.start_price,
        min_bid_step: t.min_bid_step,
        start_at: t.start_at,
        end_at: t.end_at,
      };
      if (t.buy_now_price) payload.buy_now_price = t.buy_now_price;
      if (t.reserve_price) payload.reserve_price = t.reserve_price;
      if (state.source === 'archive') {
        payload.file_id = state.card.id;
      } else {
        payload.title = state.cardData.title;
        payload.data = state.cardData;
        payload.description = state.cardData.description || '';
      }
      return payload;
    }

    root.querySelectorAll('[data-publish]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const mode = btn.getAttribute('data-publish');
        if (mode === 'schedule' && new Date(state.terms.start_at) <= new Date()) {
          showStep('preview'); showError('Для планирования начало торгов должно быть в будущем.'); return;
        }
        const url = state.source === 'archive' ? config.endpoints.createFromCard : config.endpoints.createNew;
        btn.disabled = true;
        const { ok, data } = await postJSON(url, buildPayload(mode));
        btn.disabled = false;
        if (ok) { window.location.href = (data && data.lot_url) || '/market/auction/'; return; }
        showStep('preview'); showError(firstError(data));
      });
    });

    // Deep link from «В Маркет → Аукцион»: preselect a card by ?file_id and jump
    // straight to the terms step with the card data shown.
    (function preselectFromQuery() {
      const params = new URLSearchParams(window.location.search);
      const fileId = params.get('file_id');
      if (!fileId) return;
      const selector = '[data-card-id="' + (window.CSS && CSS.escape ? CSS.escape(fileId) : fileId) + '"]';
      const cardEl = root.querySelector(selector);
      if (cardEl) {
        selectArchiveCard(cardEl);
      } else {
        showError('Эта карточка недоступна для нового лота — возможно, она уже участвует в аукционе.');
      }
    })();
  }

  // Small DOM builders for the seller edit modal.
  function _txt(v) { const i = document.createElement('input'); i.type = 'text'; i.value = v || ''; return i; }
  function _ta(v) { const t = document.createElement('textarea'); t.rows = 3; t.value = v || ''; return t; }
  function _num(v) { const i = document.createElement('input'); i.type = 'number'; i.step = '0.01'; i.min = '0'; if (v != null && v !== '') i.value = v; return i; }
  function _sel(opts, val) {
    const s = document.createElement('select'); s.setAttribute('data-theme-select', '');
    (opts || []).forEach((o) => { const op = document.createElement('option'); op.value = o.value; op.textContent = o.label; if (o.value === val) op.selected = true; s.appendChild(op); });
    return s;
  }
  function _isoLocal(iso) {
    if (!iso) return '';
    const d = new Date(iso); if (Number.isNaN(d.getTime())) return '';
    const p = (n) => String(n).padStart(2, '0');
    return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate()) + 'T' + p(d.getHours()) + ':' + p(d.getMinutes());
  }

  // ===================== Auction lot detail page =====================
  function initAuctionDetail() {
    const root = document.querySelector('[data-auction-detail]');
    if (!root) return;
    let config = {};
    const cfgNode = root.querySelector('[data-auction-config]');
    try { config = JSON.parse(cfgNode.textContent); } catch (e) { return; }
    const endpoints = config.endpoints || {};
    let state = config.state || {};
    const step = parseFloat(config.step) || 0;

    const RESERVE = { not_set: 'Резервная цена не установлена', reached: 'Резерв достигнут', not_reached: 'Резерв пока не достигнут' };
    const STATUS_TEXT = { scheduled: 'Аукцион начнётся', active: 'Аукцион идёт', completed: 'Аукцион завершён', cancelled: 'Аукцион отменён' };

    // ---- Gallery ----
    const gallery = root.querySelector('[data-gallery]');
    if (gallery) {
      const main = gallery.querySelector('[data-gallery-main]');
      const thumbs = Array.from(gallery.querySelectorAll('[data-gallery-thumb]'));
      let idx = 0;
      const show = (i) => {
        if (!thumbs.length) return;
        idx = (i + thumbs.length) % thumbs.length;
        const src = thumbs[idx].getAttribute('data-src');
        if (src && main) main.src = src;
        thumbs.forEach((t, k) => { t.classList.toggle('is-active', k === idx); t.setAttribute('aria-selected', k === idx ? 'true' : 'false'); });
      };
      thumbs.forEach((t, k) => t.addEventListener('click', () => show(k)));
      const prev = gallery.querySelector('[data-gallery-prev]');
      const next = gallery.querySelector('[data-gallery-next]');
      if (prev) prev.addEventListener('click', () => show(idx - 1));
      if (next) next.addEventListener('click', () => show(idx + 1));
      gallery.setAttribute('tabindex', '0');
      gallery.addEventListener('keydown', (e) => {
        if (e.key === 'ArrowLeft') { e.preventDefault(); show(idx - 1); }
        else if (e.key === 'ArrowRight') { e.preventDefault(); show(idx + 1); }
      });
      const zoom = gallery.querySelector('[data-gallery-zoom]');
      if (zoom) zoom.addEventListener('click', () => openLightbox(thumbs.map((t) => t.getAttribute('data-src')), idx));
    }

    function openLightbox(srcs, start) {
      let i = start || 0;
      const overlay = document.createElement('div');
      overlay.className = 'auction-lightbox';
      overlay.setAttribute('role', 'dialog');
      overlay.setAttribute('aria-modal', 'true');
      overlay.setAttribute('aria-label', 'Просмотр фотографии');
      const img = document.createElement('img'); img.className = 'auction-lightbox__img'; img.alt = '';
      const close = document.createElement('button'); close.className = 'auction-lightbox__close'; close.textContent = '✕'; close.setAttribute('aria-label', 'Закрыть');
      const prev = document.createElement('button'); prev.className = 'auction-lightbox__nav auction-lightbox__nav--prev'; prev.textContent = '‹'; prev.setAttribute('aria-label', 'Предыдущее');
      const next = document.createElement('button'); next.className = 'auction-lightbox__nav auction-lightbox__nav--next'; next.textContent = '›'; next.setAttribute('aria-label', 'Следующее');
      const render = () => { img.src = srcs[(i + srcs.length) % srcs.length]; };
      const onKey = (e) => { if (e.key === 'Escape') destroy(); else if (e.key === 'ArrowLeft') { i--; render(); } else if (e.key === 'ArrowRight') { i++; render(); } };
      function destroy() { document.removeEventListener('keydown', onKey); overlay.remove(); }
      close.addEventListener('click', destroy);
      overlay.addEventListener('click', (e) => { if (e.target === overlay) destroy(); });
      prev.addEventListener('click', () => { i--; render(); });
      next.addEventListener('click', () => { i++; render(); });
      if (srcs.length < 2) { prev.style.display = 'none'; next.style.display = 'none'; }
      overlay.append(close, prev, img, next);
      document.body.appendChild(overlay);
      document.addEventListener('keydown', onKey);
      render(); close.focus();
    }

    // ---- Timer ----
    const timerWrap = root.querySelector('[data-timer-wrap]');
    const timerValue = root.querySelector('[data-timer-value]');
    function fmtDur(ms) {
      if (ms <= 0) return '00:00:00';
      const s = Math.floor(ms / 1000);
      const days = Math.floor(s / 86400);
      const h = String(Math.floor((s % 86400) / 3600)).padStart(2, '0');
      const m = String(Math.floor((s % 3600) / 60)).padStart(2, '0');
      const ss = String(s % 60).padStart(2, '0');
      return (days > 0 ? days + ' дн ' : '') + h + ':' + m + ':' + ss;
    }
    function timerTarget() {
      if (!timerWrap) return null;
      const mode = timerWrap.getAttribute('data-timer-mode');
      const iso = mode === 'start' ? state.auction_start : state.auction_end;
      return iso ? new Date(iso) : null;
    }
    function tickTimer() {
      if (!timerWrap || !timerValue) return;
      const t = timerTarget();
      if (!t) return;
      const ms = t.getTime() - Date.now();
      timerValue.textContent = ms <= 0 ? 'Завершается…' : fmtDur(ms);
      if (ms <= 0) syncState();
    }

    // ---- State apply ----
    const els = {
      priceLabel: root.querySelector('[data-price-label]'),
      currentPrice: root.querySelector('[data-current-price]'),
      bidCount: root.querySelector('[data-bid-count]'),
      bidCountWrap: root.querySelector('[data-bidcount-wrap]'),
      minNext: root.querySelector('[data-min-next]'),
      reserve: root.querySelector('[data-reserve]'),
      statusText: root.querySelector('[data-status-text]'),
      leading: root.querySelector('[data-leading]'),
      bidInput: root.querySelector('[data-bid-input]'),
    };

    function applyState(s) {
      const prevStatus = state.status;
      state = s;
      if (els.priceLabel) els.priceLabel.textContent = s.has_bids ? 'Текущая цена' : 'Стартовая цена';
      if (els.currentPrice) els.currentPrice.textContent = s.current_price + ' ₽';
      if (els.bidCount) els.bidCount.textContent = s.bid_count;
      if (els.bidCountWrap) els.bidCountWrap.hidden = !s.has_bids;
      if (els.minNext) els.minNext.textContent = s.minimum_bid;
      if (els.reserve) { els.reserve.textContent = RESERVE[s.reserve_status] || ''; els.reserve.setAttribute('data-reserve-status', s.reserve_status); }
      if (els.statusText) els.statusText.textContent = STATUS_TEXT[s.status] || els.statusText.textContent;
      if (els.leading) els.leading.hidden = !s.is_leading;
      if (els.bidInput && document.activeElement !== els.bidInput && !els.bidInput.value) {
        els.bidInput.value = s.minimum_bid;
        els.bidInput.placeholder = 'от ' + s.minimum_bid;
      }
      if (prevStatus && prevStatus !== s.status && (s.status === 'completed' || s.status === 'cancelled')) {
        stopPolling();
        window.location.reload(); // re-render the finished UI (no bid form)
      }
    }

    function syncState() {
      return fetch(endpoints.state, { headers: { 'X-Requested-With': 'XMLHttpRequest' }, credentials: 'include' })
        .then((r) => r.json()).then((d) => { if (d && d.ok) applyState(d); return d; }).catch(() => {});
    }

    // ---- Polling ----
    let pollId = null;
    function startPolling() {
      if (pollId) return;
      if (state.status !== 'active' && state.status !== 'scheduled') return;
      pollId = window.setInterval(syncState, 12000);
    }
    function stopPolling() { if (pollId) { clearInterval(pollId); pollId = null; } }
    document.addEventListener('visibilitychange', () => { if (document.hidden) stopPolling(); else startPolling(); });
    window.addEventListener('beforeunload', stopPolling);

    // ---- History ----
    const historyEl = root.querySelector('[data-bid-history]');
    const historyEmpty = root.querySelector('[data-bid-empty]');
    const historyToggle = root.querySelector('[data-history-toggle]');
    let historyExpanded = false;
    function formatTime(iso) { try { return new Date(iso).toLocaleString('ru-RU'); } catch (e) { return iso; } }
    function bidRow(b) {
      const li = document.createElement('li');
      li.className = 'auction-detail__bid' + (b.is_winning ? ' is-winning' : '');
      const who = document.createElement('span'); who.className = 'auction-detail__bidder'; who.textContent = b.bidder;
      const amt = document.createElement('span'); amt.className = 'auction-detail__bidamount'; amt.textContent = b.amount + ' ₽';
      const when = document.createElement('span'); when.className = 'auction-detail__bidtime'; when.textContent = formatTime(b.created_at);
      li.append(who, amt, when);
      if (b.is_winning) { const lead = document.createElement('span'); lead.className = 'auction-detail__bidlead'; lead.textContent = 'Лидирует'; li.appendChild(lead); }
      return li;
    }
    function refreshHistory() {
      return fetch(endpoints.bids, { credentials: 'include' }).then((r) => r.json()).then((d) => {
        if (!d || !d.ok) return;
        const bids = d.bids || [];
        if (historyEl) {
          historyEl.innerHTML = '';
          (historyExpanded ? bids : bids.slice(0, 5)).forEach((b) => historyEl.appendChild(bidRow(b)));
        }
        if (historyEmpty) historyEmpty.hidden = bids.length > 0;
        if (historyToggle) { historyToggle.hidden = bids.length <= 5; historyToggle.textContent = historyExpanded ? 'Скрыть' : 'Показать всю историю'; }
      }).catch(() => {});
    }
    if (historyToggle) historyToggle.addEventListener('click', () => { historyExpanded = !historyExpanded; refreshHistory(); });

    // ---- Bid form ----
    const form = root.querySelector('[data-bid-form]');
    if (form) {
      const input = form.querySelector('[data-bid-input]');
      const submit = form.querySelector('[data-bid-submit]');
      const errorEl = form.querySelector('[data-bid-error]');
      if (input && !input.value) input.value = state.minimum_bid;

      form.querySelectorAll('[data-quick]').forEach((btn) => {
        btn.addEventListener('click', () => {
          const kind = btn.getAttribute('data-quick');
          let val = parseFloat(state.minimum_bid) || 0;
          if (kind === '3') val = 3 * step;
          else if (kind === '5') val = 5 * step;
          input.value = String(val);
          if (errorEl) errorEl.textContent = '';
          input.focus();
        });
      });

      form.addEventListener('submit', (e) => {
        e.preventDefault();
        if (errorEl) errorEl.textContent = '';
        const amount = input.value;
        if (!amount || parseFloat(amount) <= 0) { if (errorEl) errorEl.textContent = 'Введите сумму ставки.'; return; }
        confirmBid(amount, () => doBid(amount, input, submit, errorEl));
      });
    }

    function formatMoney(v) {
      const n = parseFloat(v);
      if (Number.isNaN(n)) return v;
      return n % 1 === 0 ? n.toLocaleString('ru-RU') : n.toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }

    function confirmBid(amount, onConfirm) {
      const overlay = document.createElement('div');
      overlay.className = 'auction-confirm';
      overlay.setAttribute('role', 'dialog');
      overlay.setAttribute('aria-modal', 'true');
      overlay.setAttribute('aria-labelledby', 'auctionConfirmTitle');
      const box = document.createElement('div'); box.className = 'auction-confirm__box';
      const title = document.createElement('p'); title.id = 'auctionConfirmTitle'; title.className = 'auction-confirm__text';
      title.textContent = 'Вы делаете ставку ' + formatMoney(amount) + ' ₽. Подтвердить?';
      const actions = document.createElement('div'); actions.className = 'auction-confirm__actions';
      const yes = document.createElement('button'); yes.className = 'ios-button ios-button--primary'; yes.textContent = 'Подтвердить';
      const no = document.createElement('button'); no.className = 'ios-button'; no.textContent = 'Отмена';
      const onKey = (e) => { if (e.key === 'Escape') destroy(); };
      function destroy() { document.removeEventListener('keydown', onKey); overlay.remove(); }
      no.addEventListener('click', destroy);
      overlay.addEventListener('click', (e) => { if (e.target === overlay) destroy(); });
      yes.addEventListener('click', () => { destroy(); onConfirm(); });
      actions.append(yes, no); box.append(title, actions); overlay.appendChild(box);
      document.body.appendChild(overlay);
      document.addEventListener('keydown', onKey);
      yes.focus();
    }

    function doBid(amount, input, submit, errorEl) {
      if (submit.disabled) return;
      submit.disabled = true; submit.classList.add('is-loading');
      const restore = submit.textContent; submit.textContent = 'Отправка…';
      fetch(endpoints.bid, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
        credentials: 'include',
        body: JSON.stringify({ amount: amount, seen_minimum: state.minimum_bid, seen_current_price: state.current_price }),
      }).then((r) => r.json().catch(() => null).then((d) => ({ data: d || {} })))
        .then(({ data }) => {
          submit.disabled = false; submit.classList.remove('is-loading'); submit.textContent = restore;
          if (data.ok) {
            if (input) input.value = '';
            syncState();
            refreshHistory();
            return;
          }
          handleBidError(data, errorEl, input);
        }).catch(() => {
          submit.disabled = false; submit.classList.remove('is-loading'); submit.textContent = restore;
          if (errorEl) errorEl.textContent = 'Ошибка соединения. Попробуйте ещё раз.';
        });
    }

    function handleBidError(data, errorEl, input) {
      let message = (data.errors && data.errors.amount) || 'Не удалось сделать ставку.';
      if (data.code === 'concurrent_bid_conflict') {
        message = 'Другой участник сделал ставку раньше. Минимальная сумма обновлена';
        syncState().then(() => { if (input) input.value = state.minimum_bid; });
        refreshHistory();
      } else if (data.code === 'bid_too_low' || data.code === 'auction_ended' || data.code === 'auction_not_started' || data.code === 'auction_cancelled') {
        syncState();
        refreshHistory();
      }
      if (errorEl) errorEl.textContent = message;
    }

    // ---- Seller management: cancel / relist / edit ----
    function manageRequest(url, method, body) {
      const opts = { method: method, headers: { 'X-CSRFToken': getCookie('csrftoken') }, credentials: 'include' };
      if (body !== undefined) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
      return fetch(url, opts).then((r) => r.json().catch(() => null).then((d) => ({ status: r.status, data: d || {} })));
    }

    root.querySelectorAll('[data-manage-cancel]').forEach((btn) => {
      btn.addEventListener('click', () => openCancelModal(btn.hasAttribute('data-admin')));
    });
    root.querySelectorAll('[data-manage-relist]').forEach((btn) => {
      btn.addEventListener('click', () => {
        btn.disabled = true; btn.classList.add('is-loading');
        manageRequest(config.endpoints.relist, 'POST', {}).then(({ data }) => {
          if (data.ok && data.redirect) { window.location.href = data.redirect; return; }
          btn.disabled = false; btn.classList.remove('is-loading');
          window.setTimeout(() => { btn.textContent = firstError(data) || 'Не удалось'; }, 0);
        });
      });
    });
    root.querySelectorAll('[data-manage-edit]').forEach((btn) => btn.addEventListener('click', openEditModal));

    function openCancelModal(isAdmin) {
      const overlay = document.createElement('div');
      overlay.className = 'auction-confirm';
      overlay.setAttribute('role', 'dialog'); overlay.setAttribute('aria-modal', 'true'); overlay.setAttribute('aria-labelledby', 'cancelTitle');
      const box = document.createElement('div'); box.className = 'auction-confirm__box';
      const title = document.createElement('p'); title.id = 'cancelTitle'; title.className = 'auction-confirm__text';
      title.textContent = isAdmin ? 'Отменить аукцион (модерация)?' : 'Снять лот с аукциона?';
      const label = document.createElement('label'); label.className = 'auction-detail__bidlabel';
      label.textContent = isAdmin ? 'Причина (обязательно)' : 'Причина (необязательно)';
      const ta = document.createElement('textarea'); ta.rows = 3; ta.className = 'auction-confirm__reason'; label.appendChild(ta);
      const err = document.createElement('p'); err.className = 'auction-detail__biderror';
      const actions = document.createElement('div'); actions.className = 'auction-confirm__actions';
      const yes = document.createElement('button'); yes.className = 'ios-button ios-button--primary'; yes.textContent = 'Подтвердить';
      const no = document.createElement('button'); no.className = 'ios-button'; no.textContent = 'Отмена';
      const onKey = (e) => { if (e.key === 'Escape') destroy(); };
      function destroy() { document.removeEventListener('keydown', onKey); overlay.remove(); }
      no.addEventListener('click', destroy);
      overlay.addEventListener('click', (e) => { if (e.target === overlay) destroy(); });
      yes.addEventListener('click', () => {
        err.textContent = '';
        if (isAdmin && !ta.value.trim()) { err.textContent = 'Укажите причину.'; return; }
        yes.disabled = true;
        manageRequest(config.endpoints.cancel, 'POST', { reason: ta.value }).then(({ data }) => {
          if (data.ok) { destroy(); window.location.reload(); return; }
          yes.disabled = false; err.textContent = firstError(data);
        });
      });
      actions.append(yes, no);
      box.append(title, label, err, actions); overlay.appendChild(box);
      document.body.appendChild(overlay); document.addEventListener('keydown', onKey); ta.focus();
    }

    function openEditModal() {
      manageRequest(config.endpoints.detail, 'GET').then(({ data }) => {
        if (data && data.ok) buildEditModal(data);
      });
    }

    function buildEditModal(detail) {
      const hasBids = !!config.has_bids;
      const POST_BID = ['description', 'location', 'delivery_note', 'delivery_cost', 'delivery_methods'];
      const opts = detail.options || {};

      const overlay = document.createElement('div');
      overlay.className = 'auction-edit';
      overlay.setAttribute('role', 'dialog'); overlay.setAttribute('aria-modal', 'true'); overlay.setAttribute('aria-labelledby', 'editTitle');
      const box = document.createElement('div'); box.className = 'auction-edit__box';
      const head = document.createElement('div'); head.className = 'auction-edit__head';
      const h = document.createElement('h2'); h.id = 'editTitle'; h.textContent = 'Редактирование лота';
      const close = document.createElement('button'); close.className = 'auction-edit__close'; close.textContent = '✕'; close.setAttribute('aria-label', 'Закрыть');
      head.append(h, close);
      const bodyEl = document.createElement('div'); bodyEl.className = 'auction-edit__body';
      const foot = document.createElement('div'); foot.className = 'auction-edit__foot';

      function field(labelText, control, key, lockable) {
        const wrap = document.createElement('div'); wrap.className = 'aw-field';
        const lab = document.createElement('label'); lab.className = 'aw-field__label';
        const span = document.createElement('span'); span.textContent = labelText; lab.append(span, control);
        wrap.appendChild(lab);
        if (hasBids && lockable && POST_BID.indexOf(key) === -1) {
          control.disabled = true;
          const note = document.createElement('small'); note.className = 'aw-field__hint';
          note.textContent = 'После первой ставки этот параметр нельзя изменить';
          wrap.appendChild(note);
        }
        return wrap;
      }

      const titleI = _txt(detail.title);
      const descI = _ta(detail.description);
      const catI = _sel([{ value: '', label: '—' }].concat(opts.category || []), detail.category);
      const condI = _sel([{ value: '', label: '—' }].concat(opts.condition || []), detail.condition);
      const locI = _txt(detail.location);
      const dmWrap = document.createElement('div'); dmWrap.className = 'auction-edit__methods';
      const dmBoxes = [];
      (opts.delivery_methods || []).forEach((o) => {
        const l = document.createElement('label'); l.className = 'aw-check';
        const cb = document.createElement('input'); cb.type = 'checkbox'; cb.value = o.value;
        cb.checked = (detail.delivery_methods || []).indexOf(o.value) !== -1;
        l.append(cb, document.createTextNode(' ' + o.label)); dmWrap.appendChild(l); dmBoxes.push(cb);
      });
      const costI = _num(detail.delivery_cost);
      const noteI = _ta(detail.delivery_note);
      const priceI = _num(detail.auction_start_price);
      const stepI = _num(detail.auction_step);
      const reserveI = _num(detail.auction_reserve_price);
      const endI = document.createElement('input'); endI.type = 'datetime-local'; endI.value = _isoLocal(detail.auction_end);
      const extendI = document.createElement('input'); extendI.type = 'checkbox'; extendI.checked = detail.auction_auto_extend !== false;

      bodyEl.append(
        field('Название', titleI, 'title', true),
        field('Описание', descI, 'description', false),
        field('Категория', catI, 'category', true),
        field('Состояние', condI, 'condition', true),
        field('Местоположение', locI, 'location', false),
        field('Способы получения', dmWrap, 'delivery_methods', false),
        field('Стоимость доставки, ₽', costI, 'delivery_cost', false),
        field('Комментарий по передаче', noteI, 'delivery_note', false),
        field('Стартовая цена, ₽', priceI, 'auction_start_price', true),
        field('Шаг ставки, ₽', stepI, 'auction_step', true),
        field('Резервная цена, ₽', reserveI, 'auction_reserve_price', true),
        field('Завершение торгов', endI, 'auction_end', true),
      );
      const exWrap = document.createElement('label'); exWrap.className = 'aw-check';
      exWrap.append(extendI, document.createTextNode(' Продлевать на 2 минуты при ставке в финале'));
      if (hasBids) extendI.disabled = true;
      bodyEl.appendChild(exWrap);

      const err = document.createElement('p'); err.className = 'auction-detail__biderror';
      const save = document.createElement('button'); save.className = 'ios-button ios-button--primary'; save.textContent = 'Сохранить';
      const cancel = document.createElement('button'); cancel.className = 'ios-button'; cancel.textContent = 'Отмена';
      foot.append(err, cancel, save);

      box.append(head, bodyEl, foot); overlay.appendChild(box); document.body.appendChild(overlay);
      if (window.ThemeSelect) window.ThemeSelect.enhanceAll(bodyEl);

      const onKey = (e) => { if (e.key === 'Escape') destroy(); };
      function destroy() { document.removeEventListener('keydown', onKey); overlay.remove(); }
      close.addEventListener('click', destroy);
      cancel.addEventListener('click', destroy);
      overlay.addEventListener('click', (e) => { if (e.target === overlay) destroy(); });
      document.addEventListener('keydown', onKey);

      save.addEventListener('click', () => {
        err.textContent = '';
        const payload = {};
        const methods = dmBoxes.filter((c) => c.checked).map((c) => c.value);
        payload.description = descI.value;
        payload.location = locI.value;
        payload.delivery_note = noteI.value;
        payload.delivery_cost = costI.value || null;
        payload.delivery_methods = methods;
        if (!hasBids) {
          payload.title = titleI.value;
          payload.category = catI.value;
          payload.condition = condI.value;
          payload.auction_start_price = priceI.value || null;
          payload.auction_step = stepI.value || null;
          payload.auction_reserve_price = reserveI.value || null;
          if (endI.value) payload.auction_end = endI.value;
          payload.auction_auto_extend = extendI.checked;
        }
        save.disabled = true; save.classList.add('is-loading');
        manageRequest(config.endpoints.manage, 'PATCH', payload).then(({ data }) => {
          if (data.ok) { destroy(); window.location.reload(); return; }
          save.disabled = false; save.classList.remove('is-loading');
          err.textContent = firstError(data);
        });
      });
      close.focus();
    }

    // Init
    applyState(state);
    if (timerWrap) { tickTimer(); window.setInterval(tickTimer, 1000); }
    refreshHistory();
    startPolling();
  }

  document.addEventListener('DOMContentLoaded', () => {
    initShare();
    initGallery();
    initBid();
    initBuyNow();
    initEdit();
    initCreateFlow();
    initAuctionDetail();
  });
})();
