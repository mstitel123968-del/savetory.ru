(function () {
  'use strict';

  // ---- helpers -----------------------------------------------------------
  function csrf() {
    var m = document.cookie.match(/csrftoken=([^;]+)/);
    if (m) return decodeURIComponent(m[1]);
    return window.__csrfToken || '';
  }
  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function fmtDate(iso) {
    if (!iso) return '';
    var d = new Date(iso);
    if (isNaN(d)) return '';
    return d.toLocaleString('ru-RU', { dateStyle: 'medium', timeStyle: 'short' });
  }
  async function api(url, opts) {
    opts = opts || {};
    var headers = Object.assign({ 'X-CSRFToken': csrf() }, opts.headers || {});
    var resp = await fetch(url, {
      method: opts.method || 'GET',
      credentials: 'include',
      cache: 'no-store',
      headers: headers,
      body: opts.body,
    });
    var data = null;
    try { data = await resp.json(); } catch (e) { data = null; }
    return { resp: resp, data: data };
  }
  function jsonBody(obj) { return { headers: { 'Content-Type': 'application/json' }, method: 'POST', body: JSON.stringify(obj) }; }

  function setStatus(msg) { $('studioStatus').textContent = msg || ''; }

  // ---- auth / shell ------------------------------------------------------
  async function refreshAuth() {
    var r = await api('/api/studio/status/');
    var authed = !!(r.data && r.data.authenticated);
    $('studioLogin').hidden = authed;
    $('studioShell').hidden = !authed;
    if (authed) {
      $('studioWho').textContent = r.data.username || '';
      loadTab(currentTab);
    }
  }

  async function doLogin() {
    $('studioLoginError').textContent = '';
    var r = await api('/api/studio/login/', jsonBody({
      username: $('studioUser').value.trim(),
      password: $('studioPass').value,
    }));
    if (r.data && r.data.success) {
      $('studioPass').value = '';
      refreshAuth();
    } else {
      $('studioLoginError').textContent = (r.data && r.data.error) || 'Ошибка входа.';
    }
  }

  async function doLogout() {
    await api('/api/studio/logout/', { method: 'POST' });
    location.reload();
  }

  // ---- tabs --------------------------------------------------------------
  var currentTab = 'news';
  function switchTab(tab) {
    currentTab = tab;
    document.querySelectorAll('.studio-tab').forEach(function (b) {
      b.classList.toggle('active', b.dataset.tab === tab);
    });
    document.querySelectorAll('.studio-panel').forEach(function (p) {
      p.classList.toggle('active', p.dataset.panel === tab);
    });
    setStatus('');
    loadTab(tab);
  }
  function loadTab(tab) {
    if (tab === 'news') return loadNews();
    if (tab === 'users') return renderUsers([]);
    if (tab === 'listings') return loadListings(currentListingStatus);
    if (tab === 'reviews') return loadReviews();
  }

  // ---- generic reason prompt --------------------------------------------
  var promptResolve = null;
  function askReason(opts) {
    return new Promise(function (resolve) {
      promptResolve = resolve;
      $('promptTitle').textContent = opts.title || 'Действие';
      $('promptLabel').textContent = opts.label || 'Причина';
      $('promptText').value = opts.value || '';
      $('promptText').placeholder = opts.placeholder || '';
      $('studioPrompt').classList.add('open');
      setTimeout(function () { $('promptText').focus(); }, 30);
    });
  }
  function closePrompt(result) {
    $('studioPrompt').classList.remove('open');
    if (promptResolve) { promptResolve(result); promptResolve = null; }
  }

  // ---- NEWS --------------------------------------------------------------
  async function loadNews() {
    var host = $('newsList');
    host.innerHTML = '<div class="studio-empty">Загрузка…</div>';
    var r = await api('/api/studio/news/');
    if (!r.data || !r.data.success) { host.innerHTML = '<div class="studio-empty">Не удалось загрузить.</div>'; return; }
    var items = r.data.news || [];
    if (!items.length) { host.innerHTML = '<div class="studio-empty">Новостей пока нет.</div>'; return; }
    host.innerHTML = items.map(function (n) {
      return '<div class="studio-row" data-id="' + n.id + '">'
        + '<div class="studio-row__head"><span class="studio-row__title">' + esc(n.title) + '</span>'
        + '<span class="studio-badge ' + (n.is_published ? 'on' : 'off') + '">' + (n.is_published ? 'Опубликовано' : 'Черновик') + '</span></div>'
        + '<div class="studio-row__meta">' + fmtDate(n.publish_at) + '</div>'
        + '<div class="studio-row__body">' + esc((n.preview || '').slice(0, 200)) + '</div>'
        + '<div class="studio-row__actions">'
        + '<button class="studio-btn small" data-act="edit">Редактировать</button>'
        + '<button class="studio-btn small" data-act="pub">' + (n.is_published ? 'Снять с публикации' : 'Опубликовать') + '</button>'
        + '<button class="studio-btn small danger" data-act="del">Удалить</button>'
        + '</div></div>';
    }).join('');
    var map = {};
    items.forEach(function (n) { map[n.id] = n; });
    host.querySelectorAll('.studio-row').forEach(function (row) {
      var n = map[row.dataset.id];
      row.querySelector('[data-act=edit]').onclick = function () { openNewsEditor(n); };
      row.querySelector('[data-act=pub]').onclick = async function () {
        await api('/api/studio/news/' + n.id + '/publish/', jsonBody({ is_published: !n.is_published }));
        loadNews();
      };
      row.querySelector('[data-act=del]').onclick = async function () {
        if (!confirm('Удалить новость «' + n.title + '»?')) return;
        await api('/api/studio/news/' + n.id + '/delete/', { method: 'POST' });
        loadNews();
      };
    });
  }

  function openNewsEditor(n) {
    n = n || {};
    $('newsEditorTitle').textContent = n.id ? 'Редактирование новости' : 'Новая новость';
    $('newsId').value = n.id || '';
    $('newsTitle').value = n.title || '';
    $('newsPreview').value = n.preview || '';
    $('newsBody').value = n.body || '';
    $('newsPublished').checked = !!n.is_published;
    $('newsCover').value = '';
    $('newsEditorError').textContent = '';
    if (n.publish_at) {
      var d = new Date(n.publish_at);
      if (!isNaN(d)) {
        d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
        $('newsPublishAt').value = d.toISOString().slice(0, 16);
      }
    } else { $('newsPublishAt').value = ''; }
    $('newsEditor').classList.add('open');
  }

  async function saveNews() {
    var fd = new FormData();
    var id = $('newsId').value;
    if (id) fd.append('id', id);
    fd.append('title', $('newsTitle').value.trim());
    fd.append('preview', $('newsPreview').value);
    fd.append('body', $('newsBody').value);
    fd.append('is_published', $('newsPublished').checked ? '1' : '0');
    if ($('newsPublishAt').value) fd.append('publish_at', $('newsPublishAt').value);
    if ($('newsCover').files[0]) fd.append('cover', $('newsCover').files[0]);
    var r = await api('/api/studio/news/save/', { method: 'POST', body: fd });
    if (r.data && r.data.success) {
      $('newsEditor').classList.remove('open');
      loadNews();
    } else {
      $('newsEditorError').textContent = (r.data && r.data.error) || 'Не удалось сохранить.';
    }
  }

  // ---- USERS -------------------------------------------------------------
  async function searchUsers() {
    var q = $('userSearch').value.trim();
    var r = await api('/api/studio/users/?q=' + encodeURIComponent(q));
    renderUsers((r.data && r.data.users) || []);
  }
  function renderUsers(items) {
    var host = $('userList');
    if (!items.length) { host.innerHTML = '<div class="studio-empty">Введите запрос и нажмите «Найти».</div>'; return; }
    host.innerHTML = items.map(function (u) {
      return '<div class="studio-row" data-id="' + u.id + '">'
        + '<div class="studio-row__head"><span class="studio-row__title">' + esc(u.username) + ' <span class="studio-row__meta">#' + u.id + '</span></span>'
        + '<span class="studio-badge ' + (u.is_blocked ? 'off' : 'on') + '">' + (u.is_blocked ? 'Заблокирован' : 'Активен') + '</span></div>'
        + '<div class="studio-row__meta">' + esc(u.name || '') + (u.email ? ' · ' + esc(u.email) : '') + '</div>'
        + (u.is_blocked && u.block_reason ? '<div class="studio-row__body">Причина: ' + esc(u.block_reason) + '</div>' : '')
        + '<div class="studio-row__actions">'
        + (u.is_superuser ? '<span class="studio-row__meta">администратор</span>'
          : (u.is_blocked
            ? '<button class="studio-btn small" data-act="unblock">Разблокировать</button>'
            : '<button class="studio-btn small danger" data-act="block">Заблокировать</button>'))
        + '</div></div>';
    }).join('');
    var map = {}; items.forEach(function (u) { map[u.id] = u; });
    host.querySelectorAll('.studio-row').forEach(function (row) {
      var u = map[row.dataset.id];
      var blockBtn = row.querySelector('[data-act=block]');
      var unblockBtn = row.querySelector('[data-act=unblock]');
      if (blockBtn) blockBtn.onclick = async function () {
        var reason = await askReason({ title: 'Блокировка пользователя', label: 'Текст блокировки (увидит пользователь)', placeholder: 'Например: нарушение правил сервиса' });
        if (reason === null) return;
        await api('/api/studio/users/' + u.id + '/block/', jsonBody({ reason: reason }));
        searchUsers();
      };
      if (unblockBtn) unblockBtn.onclick = async function () {
        await api('/api/studio/users/' + u.id + '/unblock/', { method: 'POST' });
        searchUsers();
      };
    });
  }

  // ---- LISTINGS ----------------------------------------------------------
  var currentListingStatus = '';
  var LISTING_ACTIONS = [
    { act: 'invalidate', label: 'Недействителен', danger: true },
    { act: 'close', label: 'Закрыть', danger: false },
    { act: 'unpublish', label: 'Снять с публикации', danger: false },
    { act: 'reactivate', label: 'Вернуть в активные', danger: false },
  ];
  async function loadListings(status) {
    currentListingStatus = status || '';
    var host = $('listingList');
    host.innerHTML = '<div class="studio-empty">Загрузка…</div>';
    var r = await api('/api/studio/listings/?status=' + encodeURIComponent(currentListingStatus));
    var items = (r.data && r.data.listings) || [];
    if (!items.length) { host.innerHTML = '<div class="studio-empty">Ничего не найдено.</div>'; return; }
    host.innerHTML = items.map(function (l) {
      return '<div class="studio-row" data-id="' + l.id + '">'
        + '<div class="studio-row__head"><span class="studio-row__title">' + esc(l.title) + ' <span class="studio-row__meta">#' + l.id + '</span></span>'
        + '<span class="studio-badge">' + esc(l.state) + '</span></div>'
        + '<div class="studio-row__meta">' + esc(l.type) + ' · продавец ' + esc(l.seller) + ' · ' + fmtDate(l.created_at) + '</div>'
        + (l.moderation_reason ? '<div class="studio-row__body">Причина: ' + esc(l.moderation_reason) + '</div>' : '')
        + '<div class="studio-row__actions">'
        + LISTING_ACTIONS.map(function (a) { return '<button class="studio-btn small' + (a.danger ? ' danger' : '') + '" data-act="' + a.act + '">' + a.label + '</button>'; }).join('')
        + '</div></div>';
    }).join('');
    host.querySelectorAll('.studio-row').forEach(function (row) {
      var id = row.dataset.id;
      row.querySelectorAll('[data-act]').forEach(function (btn) {
        btn.onclick = async function () {
          var act = btn.dataset.act;
          var reason = '';
          if (act !== 'reactivate') {
            reason = await askReason({ title: btn.textContent, label: 'Причина (сохранится в истории)' });
            if (reason === null) return;
          }
          await api('/api/studio/listings/' + id + '/action/', jsonBody({ action: act, reason: reason }));
          loadListings(currentListingStatus);
        };
      });
    });
  }

  // ---- REVIEWS -----------------------------------------------------------
  async function loadReviews() {
    var host = $('reviewList');
    host.innerHTML = '<div class="studio-empty">Загрузка…</div>';
    var r = await api('/api/studio/reviews/');
    var items = (r.data && r.data.reviews) || [];
    if (!items.length) { host.innerHTML = '<div class="studio-empty">Отзывов пока нет.</div>'; return; }
    host.innerHTML = items.map(function (rv) {
      return '<div class="studio-row" data-id="' + rv.id + '">'
        + '<div class="studio-row__head"><span class="studio-row__title">' + esc(rv.author) + ' · ' + rv.rating + '★</span>'
        + '<span class="studio-badge ' + (rv.is_hidden ? 'off' : 'on') + '">' + (rv.is_hidden ? 'Скрыт' : 'Виден') + '</span></div>'
        + '<div class="studio-row__body">' + esc(rv.text) + '</div>'
        + (rv.hidden_reason ? '<div class="studio-row__meta">Причина: ' + esc(rv.hidden_reason) + '</div>' : '')
        + '<div class="studio-row__actions">'
        + (rv.is_hidden ? '<button class="studio-btn small" data-act="restore">Вернуть</button>'
          : '<button class="studio-btn small" data-act="hide">Скрыть</button>')
        + '<button class="studio-btn small danger" data-act="delete">Удалить</button>'
        + '</div></div>';
    }).join('');
    host.querySelectorAll('.studio-row').forEach(function (row) {
      var id = row.dataset.id;
      var hide = row.querySelector('[data-act=hide]');
      var restore = row.querySelector('[data-act=restore]');
      var del = row.querySelector('[data-act=delete]');
      if (hide) hide.onclick = async function () {
        var reason = await askReason({ title: 'Скрыть отзыв', label: 'Причина' });
        if (reason === null) return;
        await api('/api/studio/reviews/' + id + '/action/', jsonBody({ action: 'hide', reason: reason }));
        loadReviews();
      };
      if (restore) restore.onclick = async function () {
        await api('/api/studio/reviews/' + id + '/action/', jsonBody({ action: 'restore' }));
        loadReviews();
      };
      if (del) del.onclick = async function () {
        if (!confirm('Удалить отзыв безвозвратно?')) return;
        await api('/api/studio/reviews/' + id + '/action/', jsonBody({ action: 'delete' }));
        loadReviews();
      };
    });
  }

  // ---- wire up -----------------------------------------------------------
  document.addEventListener('DOMContentLoaded', function () {
    $('studioLoginBtn').onclick = doLogin;
    $('studioPass').addEventListener('keydown', function (e) { if (e.key === 'Enter') doLogin(); });
    $('studioLogout').onclick = doLogout;
    document.querySelectorAll('.studio-tab').forEach(function (b) { b.onclick = function () { switchTab(b.dataset.tab); }; });

    $('newsCreate').onclick = function () { openNewsEditor(null); };
    $('newsSave').onclick = saveNews;
    $('newsCancel').onclick = function () { $('newsEditor').classList.remove('open'); };

    $('userSearchBtn').onclick = searchUsers;
    $('userSearch').addEventListener('keydown', function (e) { if (e.key === 'Enter') searchUsers(); });

    document.querySelectorAll('#listingFilters [data-status]').forEach(function (b) {
      b.onclick = function () {
        document.querySelectorAll('#listingFilters [data-status]').forEach(function (x) { x.classList.toggle('active', x === b); });
        loadListings(b.dataset.status);
      };
    });

    $('promptConfirm').onclick = function () { closePrompt($('promptText').value.trim()); };
    $('promptCancel').onclick = function () { closePrompt(null); };
    $('studioPrompt').addEventListener('click', function (e) { if (e.target === $('studioPrompt')) closePrompt(null); });
    $('newsEditor').addEventListener('click', function (e) { if (e.target === $('newsEditor')) $('newsEditor').classList.remove('open'); });

    refreshAuth();
  });
})();
