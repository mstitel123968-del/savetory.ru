(function(){
  const root = document.querySelector('.community-main');
  if (!root) return;

  const state = {
    tab: root.dataset.initialTab || 'search',
    requestsView: root.dataset.initialRequestsView || 'incoming',
    searchQuery: '',
    searchPage: 1,
    searchTimer: null,
    friendsQuery: '',
    requestsQuery: '',
    requestsData: null,
    busy: new Set(),
  };

  const els = {
    tabs: Array.from(document.querySelectorAll('.community-tab')),
    panels: Array.from(document.querySelectorAll('.community-panel')),
    notice: document.getElementById('communityNotice'),
    searchInput: document.getElementById('communitySearchInput'),
    searchClear: document.getElementById('communitySearchClear'),
    searchButton: document.getElementById('communitySearchButton'),
    searchbars: Array.from(document.querySelectorAll('[data-search-tab]')),
    searchMeta: document.getElementById('communitySearchMeta'),
    searchState: document.getElementById('communitySearchState'),
    searchGrid: document.getElementById('communitySearchGrid'),
    pagination: document.getElementById('communityPagination'),
    friendsSearch: document.getElementById('communityFriendsSearch'),
    friendsClear: document.getElementById('communityFriendsClear'),
    friendsState: document.getElementById('communityFriendsState'),
    friendsGrid: document.getElementById('communityFriendsGrid'),
    requestsSearch: document.getElementById('communityRequestsSearch'),
    requestsClear: document.getElementById('communityRequestsClear'),
    requestsState: document.getElementById('communityRequestsState'),
    requestsList: document.getElementById('communityRequestsList'),
    requestSwitches: Array.from(document.querySelectorAll('.community-request-switch [data-requests-view]')),
    friendsPreview: document.getElementById('communityFriendsPreview'),
  };

  function csrf(){
    const match = document.cookie.match(/csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : '';
  }

  async function api(url, options){
    const response = await fetch(url, Object.assign({
      credentials: 'include',
      headers: { 'X-CSRFToken': csrf() },
    }, options || {}));
    let data = null;
    try { data = await response.json(); } catch (error) {}
    if (!response.ok || !data || data.success === false){
      throw new Error((data && data.error) || `Ошибка запроса (${response.status})`);
    }
    return data;
  }

  function showNotice(message, tone){
    if (!els.notice) return;
    els.notice.textContent = message || '';
    els.notice.hidden = !message;
    els.notice.dataset.tone = tone || 'info';
    window.clearTimeout(showNotice.timer);
    if (message){
      showNotice.timer = window.setTimeout(() => { els.notice.hidden = true; }, 3200);
    }
  }

  function setUrl(){
    const url = new URL(window.location.href);
    url.searchParams.set('tab', state.tab);
    if (state.tab === 'requests'){
      url.searchParams.set('requests', state.requestsView);
    } else {
      url.searchParams.delete('requests');
    }
    window.history.replaceState({}, '', url);
  }

  function setTab(tab, requestsView){
    state.tab = ['search', 'friends', 'requests'].includes(tab) ? tab : 'search';
    if (requestsView){
      state.requestsView = requestsView;
    }
    els.tabs.forEach((button) => {
      const active = button.dataset.tab === state.tab;
      button.classList.toggle('active', active);
      button.setAttribute('aria-selected', active ? 'true' : 'false');
    });
    els.panels.forEach((panel) => {
      panel.hidden = panel.dataset.panel !== state.tab;
    });
    els.requestSwitches.forEach((button) => {
      button.classList.toggle('active', button.dataset.requestsView === state.requestsView);
    });
    els.searchbars.forEach((bar) => {
      bar.hidden = bar.dataset.searchTab !== state.tab;
    });
    setUrl();
    if (state.tab === 'friends') loadFriends();
    if (state.tab === 'requests') loadRequests();
    if (state.tab === 'search') {
      loadSearch(state.searchPage);
      loadSummary();
    }
  }

  function setState(el, message){
    if (!el) return;
    el.textContent = message || '';
    el.hidden = !message;
  }

  function updateCounts(counts){
    if (!counts) return;
    if (Object.prototype.hasOwnProperty.call(counts, 'friends')){
      document.querySelectorAll('[data-count="friends"]').forEach((el) => { el.textContent = counts.friends || 0; });
    }
    if (Object.prototype.hasOwnProperty.call(counts, 'incoming')){
      document.querySelectorAll('[data-count="incoming"]').forEach((el) => { el.textContent = counts.incoming || 0; });
    }
    if (Object.prototype.hasOwnProperty.call(counts, 'outgoing')){
      document.querySelectorAll('[data-count="outgoing"]').forEach((el) => { el.textContent = counts.outgoing || 0; });
    }
  }

  function avatar(user){
    const box = document.createElement('div');
    box.className = 'community-avatar';
    if (user && user.avatar_data){
      const img = document.createElement('img');
      img.alt = '';
      img.src = user.avatar_data;
      box.appendChild(img);
    } else {
      const name = (user && (user.display_name || user.username)) || '?';
      box.textContent = name.trim().slice(0, 1).toUpperCase() || '?';
    }
    return box;
  }

  function friendshipButton(user){
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'community-action community-action--primary';
    button.dataset.userId = user.id;
    if (user.friendship_state === 'accepted'){
      button.classList.add('community-action--muted');
      button.textContent = 'В друзьях ✓';
      button.disabled = true;
    } else if (user.friendship_state === 'outgoing'){
      button.classList.add('community-action--muted');
      button.textContent = 'Заявка отправлена';
      button.disabled = true;
    } else if (user.friendship_state === 'incoming'){
      button.textContent = 'Ответить на заявку';
      button.addEventListener('click', () => setTab('requests', 'incoming'));
    } else {
      button.textContent = 'Добавить в друзья';
      button.addEventListener('click', () => runFriendshipAction('send', user.id, button));
    }
    return button;
  }

  function isInteractiveTarget(target, rootElement){
    if (!target) return false;
    const interactive = target.closest('button, a, input, select, textarea, [role="button"]');
    return !!(interactive && interactive !== rootElement);
  }

  function userCard(user, options){
    const opts = options || {};
    const card = document.createElement('article');
    card.className = 'community-card';
    card.dataset.userId = user.id;
    card.tabIndex = 0;
    card.setAttribute('role', 'button');
    card.setAttribute('aria-label', `Открыть профиль ${user.display_name || user.username}`);
    card.addEventListener('click', (event) => {
      if (isInteractiveTarget(event.target, card)) return;
      openProfileCard(user);
    });
    card.addEventListener('keydown', (event) => {
      if (event.key !== 'Enter' && event.key !== ' ') return;
      if (isInteractiveTarget(event.target, card)) return;
      event.preventDefault();
      openProfileCard(user);
    });
    card.appendChild(avatar(user));

    const body = document.createElement('div');
    body.className = 'community-card__body';
    const name = document.createElement('div');
    name.className = 'community-card__name';
    name.textContent = user.display_name || user.username;
    if (opts.mode === 'friend' && user.presence && user.presence.label){
      const presence = document.createElement('span');
      presence.className = `community-presence ${user.presence.is_online ? 'community-presence--online' : 'community-presence--offline'}`;
      presence.textContent = user.presence.label;
      name.appendChild(presence);
    }
    const username = document.createElement('div');
    username.className = 'community-card__username';
    username.textContent = `@${user.username}`;
    body.append(name, username);
    if (user.city){
      const city = document.createElement('div');
      city.className = 'community-card__meta';
      city.textContent = user.city;
      body.appendChild(city);
    }
    if (user.interests){
      const interests = document.createElement('div');
      interests.className = 'community-card__interests';
      interests.textContent = user.interests;
      body.appendChild(interests);
    }

    if (opts.mode === 'friend'){
      const actions = document.createElement('div');
      actions.className = 'community-card__actions';
      actions.appendChild(friendMenu(user));
      body.appendChild(actions);
    } else if (opts.mode === 'incoming'){
      const actions = document.createElement('div');
      actions.className = 'community-card__actions';
      actions.appendChild(requestActions(user, 'incoming'));
      body.appendChild(actions);
    } else if (opts.mode === 'outgoing'){
      const actions = document.createElement('div');
      actions.className = 'community-card__actions';
      actions.appendChild(requestActions(user, 'outgoing'));
      body.appendChild(actions);
    }
    card.appendChild(body);
    return card;
  }

  function openProfileCard(user){
    const overlay = document.createElement('div');
    overlay.className = 'community-profile-modal';
    const dialog = document.createElement('div');
    dialog.className = 'community-profile-modal__dialog';
    dialog.setAttribute('role', 'dialog');
    dialog.setAttribute('aria-modal', 'true');

    const close = document.createElement('button');
    close.type = 'button';
    close.className = 'community-profile-modal__close';
    close.setAttribute('aria-label', 'Закрыть');
    close.textContent = '×';
    close.addEventListener('click', () => overlay.remove());

    const head = document.createElement('div');
    head.className = 'community-profile-modal__head';
    head.appendChild(avatar(user));
    const title = document.createElement('div');
    const name = document.createElement('h2');
    name.textContent = user.display_name || user.username;
    if (user.presence && user.presence.label){
      const presence = document.createElement('span');
      presence.className = `community-presence ${user.presence.is_online ? 'community-presence--online' : 'community-presence--offline'}`;
      presence.textContent = user.presence.label;
      name.appendChild(presence);
    }
    const login = document.createElement('p');
    login.textContent = `@${user.username}`;
    title.append(name, login);
    head.appendChild(title);

    const details = document.createElement('div');
    details.className = 'community-profile-modal__details';
    const city = document.createElement('div');
    city.textContent = user.city ? `Город: ${user.city}` : 'Город скрыт настройками приватности';
    const interests = document.createElement('div');
    interests.textContent = user.interests ? `Интересы: ${user.interests}` : 'Интересы скрыты настройками приватности';
    details.append(city, interests);

    const actions = document.createElement('div');
    actions.className = 'community-profile-modal__actions';
    const openProfile = document.createElement('a');
    openProfile.className = 'community-action';
    openProfile.href = user.profile_url || '#';
    openProfile.textContent = 'Открыть профиль';
    actions.appendChild(openProfile);
    actions.appendChild(friendshipButton(user));

    dialog.append(close, head, details, actions);
    overlay.appendChild(dialog);
    overlay.addEventListener('click', (event) => {
      if (event.target === overlay) overlay.remove();
    });
    document.addEventListener('keydown', function onKey(event){
      if (event.key === 'Escape'){
        overlay.remove();
        document.removeEventListener('keydown', onKey);
      }
    });
    document.body.appendChild(overlay);
    close.focus();
  }

  function formatDate(value){
    if (!value) return '';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '';
    return date.toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });
  }

  function friendMenu(user){
    const wrap = document.createElement('div');
    wrap.className = 'community-card-menu';
    const button = document.createElement('button');
    button.className = 'community-action community-card-menu__button';
    button.type = 'button';
    button.textContent = 'Действия';
    const list = document.createElement('div');
    list.className = 'community-card-menu__list';
    list.hidden = true;
    const message = document.createElement('a');
    message.className = 'community-action community-card-menu__item';
    message.href = user.message_url || `/messages/${encodeURIComponent(user.id)}/`;
    message.textContent = 'Сообщение';
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'community-action community-action--danger community-card-menu__item';
    remove.textContent = 'Удалить из друзей';
    remove.addEventListener('click', () => {
      list.hidden = true;
      const ok = window.confirm(`Удалить пользователя “${user.display_name || user.username}” из друзей?`);
      if (ok) runFriendshipAction('remove', user.id, remove);
    });
    button.addEventListener('click', () => { list.hidden = !list.hidden; });
    wrap.append(button, list);
    list.append(message, remove);
    return wrap;
  }

  function requestActions(user, mode){
    const wrap = document.createElement('div');
    wrap.className = 'community-card__actions';
    if (mode === 'incoming'){
      const accept = document.createElement('button');
      accept.type = 'button';
      accept.className = 'community-action community-action--primary';
      accept.textContent = 'Принять';
      accept.addEventListener('click', () => runFriendshipAction('accept', user.id, accept));
      const reject = document.createElement('button');
      reject.type = 'button';
      reject.className = 'community-action community-action--danger';
      reject.textContent = 'Отклонить';
      reject.addEventListener('click', () => {
        if (window.confirm(`Отклонить заявку от “${user.display_name || user.username}”?`)){
          runFriendshipAction('reject', user.id, reject);
        }
      });
      wrap.append(accept, reject);
    } else {
      const status = document.createElement('span');
      status.className = 'community-action community-action--muted';
      status.textContent = 'Ожидает ответа';
      const cancel = document.createElement('button');
      cancel.type = 'button';
      cancel.className = 'community-action community-action--danger';
      cancel.textContent = 'Отменить заявку';
      cancel.addEventListener('click', () => {
        if (window.confirm(`Отменить заявку пользователю “${user.display_name || user.username}”?`)){
          runFriendshipAction('cancel', user.id, cancel);
        }
      });
      wrap.append(status, cancel);
    }
    return wrap;
  }

  async function runFriendshipAction(action, userId, button){
    const key = `${action}:${userId}`;
    if (state.busy.has(key)) return;
    state.busy.add(key);
    if (button) button.disabled = true;
    try {
      const data = await api('/api/community/friendship/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf() },
        body: JSON.stringify({ action, target_id: userId }),
      });
      showNotice(data.message || 'Готово');
      if (action === 'send' && button){
        button.textContent = 'Заявка отправлена';
        button.classList.add('community-action--muted');
        button.dataset.keepDisabled = 'true';
      }
      updateCounts(data.counts);
      await Promise.all([loadSummary(), refreshCurrent()]);
    } catch (error){
      showNotice(error.message || 'Не удалось выполнить действие.', 'error');
    } finally {
      state.busy.delete(key);
      if (button && button.dataset.keepDisabled !== 'true') button.disabled = false;
    }
  }

  async function refreshCurrent(){
    if (state.tab === 'search') return loadSearch(state.searchPage);
    if (state.tab === 'friends') return loadFriends();
    if (state.tab === 'requests') return loadRequests();
  }

  async function loadSummary(){
    try {
      const data = await api('/api/community/summary/');
      updateCounts(data.counts);
      renderFriendsPreview(data.friends_preview || [], data.friends_extra || 0);
    } catch (error){
      showNotice(error.message || 'Не удалось обновить сводку.', 'error');
    }
  }

  function renderFriendsPreview(friends, extra){
    if (!els.friendsPreview) return;
    els.friendsPreview.textContent = '';
    if (!friends.length){
      els.friendsPreview.textContent = 'Пока нет друзей.';
      return;
    }
    friends.forEach((user) => els.friendsPreview.appendChild(avatar(user)));
    if (extra > 0){
      const more = document.createElement('div');
      more.className = 'community-avatar-extra';
      more.textContent = `+${extra}`;
      els.friendsPreview.appendChild(more);
    }
  }

  async function loadSearch(page){
    state.searchPage = page || 1;
    const query = (els.searchInput.value || '').trim();
    state.searchQuery = query;
    const apiQuery = query.length >= 2 ? query : '';
    els.searchGrid.textContent = '';
    els.pagination.hidden = true;
    setState(els.searchState, apiQuery ? 'Ищем пользователей...' : 'Загружаем пользователей...');
    try {
      const data = await api(`/api/community/search/?q=${encodeURIComponent(apiQuery)}&page=${state.searchPage}`);
      setState(els.searchState, '');
      els.searchMeta.textContent = apiQuery
        ? `Найдено пользователей: ${data.count}`
        : `Пользователи с открытым аккаунтом: ${data.count}`;
      if (!data.users.length){
        setState(els.searchState, apiQuery ? 'Никого не нашли. Попробуйте другой запрос.' : 'Пока нет пользователей с открытым аккаунтом.');
      }
      data.users.forEach((user) => els.searchGrid.appendChild(userCard(user)));
      renderPagination(data.page, data.num_pages);
    } catch (error){
      setState(els.searchState, 'Не удалось выполнить поиск. Проверьте соединение и попробуйте снова.');
    }
  }

  function renderPagination(page, numPages){
    els.pagination.textContent = '';
    if (numPages <= 1){
      els.pagination.hidden = true;
      return;
    }
    els.pagination.hidden = false;
    const prev = document.createElement('button');
    prev.className = 'side-btn';
    prev.type = 'button';
    prev.textContent = 'Назад';
    prev.disabled = page <= 1;
    prev.addEventListener('click', () => loadSearch(page - 1));
    const label = document.createElement('span');
    label.textContent = `${page} / ${numPages}`;
    const next = document.createElement('button');
    next.className = 'side-btn';
    next.type = 'button';
    next.textContent = 'Вперёд';
    next.disabled = page >= numPages;
    next.addEventListener('click', () => loadSearch(page + 1));
    els.pagination.append(prev, label, next);
  }

  async function loadFriends(){
    const query = (els.friendsSearch.value || '').trim();
    setState(els.friendsState, 'Загружаем друзей...');
    els.friendsGrid.textContent = '';
    try {
      const data = await api(`/api/community/friends/?q=${encodeURIComponent(query)}`);
      updateCounts({ friends: data.count });
      setState(els.friendsState, '');
      if (!data.users.length){
        if (query){
          setState(els.friendsState, 'По этому запросу друзей не найдено.');
        } else {
          els.friendsState.hidden = false;
          els.friendsState.textContent = 'Пока нет друзей. ';
          const button = document.createElement('button');
          button.type = 'button';
          button.className = 'side-btn';
          button.textContent = 'Перейти к поиску';
          button.addEventListener('click', () => setTab('search'));
          els.friendsState.appendChild(button);
        }
      }
      data.users.forEach((user) => els.friendsGrid.appendChild(userCard(user, { mode: 'friend' })));
    } catch (error){
      setState(els.friendsState, 'Не удалось загрузить друзей.');
    }
  }

  async function loadRequests(){
    setState(els.requestsState, 'Загружаем заявки...');
    els.requestsList.textContent = '';
    try {
      const data = await api('/api/community/requests/');
      state.requestsData = data;
      renderRequests();
    } catch (error){
      setState(els.requestsState, 'Не удалось загрузить заявки.');
    }
  }

  function renderRequests(){
    const data = state.requestsData;
    if (!data) return;
    const query = (els.requestsSearch ? els.requestsSearch.value : '').trim().toLowerCase();
      updateCounts(data.counts);
      els.requestSwitches.forEach((button) => {
        button.classList.toggle('active', button.dataset.requestsView === state.requestsView);
      });
    let list = state.requestsView === 'outgoing' ? data.outgoing : data.incoming;
    if (query){
      list = list.filter((item) => {
        const user = item.user || {};
        return `${user.display_name || ''} ${user.username || ''}`.toLowerCase().includes(query);
      });
    }
    els.requestsList.textContent = '';
      setState(els.requestsState, '');
      if (!list.length){
      if (query){
        setState(els.requestsState, 'По этому запросу заявок не найдено.');
      } else {
        setState(els.requestsState, state.requestsView === 'outgoing' ? 'Исходящих заявок пока нет.' : 'Входящих заявок пока нет.');
      }
      }
      list.forEach((item) => {
        const card = userCard(item.user, { mode: state.requestsView });
        const body = card.querySelector('.community-card__body');
        const dateLine = document.createElement('div');
        dateLine.className = 'community-card__meta';
        dateLine.textContent = state.requestsView === 'outgoing'
          ? `Дата отправки: ${formatDate(item.created_at)}`
          : `Дата заявки: ${formatDate(item.created_at)}`;
        if (body){
          body.insertBefore(dateLine, body.querySelector('.community-card__actions'));
        }
        els.requestsList.appendChild(card);
      });
  }

  function scheduleSearch(){
    window.clearTimeout(state.searchTimer);
    state.searchTimer = window.setTimeout(() => loadSearch(1), 420);
  }

  els.tabs.forEach((button) => button.addEventListener('click', () => setTab(button.dataset.tab)));
  document.querySelectorAll('[data-go-tab]').forEach((button) => {
    button.addEventListener('click', () => setTab(button.dataset.goTab, button.dataset.requestsView));
  });
  els.requestSwitches.forEach((button) => {
    button.addEventListener('click', () => setTab('requests', button.dataset.requestsView));
  });
  els.searchInput.addEventListener('input', scheduleSearch);
  els.searchInput.addEventListener('keydown', (event) => {
    if (event.key === 'Enter'){
      event.preventDefault();
      window.clearTimeout(state.searchTimer);
      loadSearch(1);
    }
  });
  if (els.searchButton){
    els.searchButton.addEventListener('click', () => loadSearch(1));
  }
  els.searchClear.addEventListener('click', () => {
    els.searchInput.value = '';
    loadSearch(1);
    els.searchInput.focus();
  });
  els.friendsSearch.addEventListener('input', () => {
    window.clearTimeout(state.friendsTimer);
    state.friendsTimer = window.setTimeout(loadFriends, 350);
  });
  els.friendsClear.addEventListener('click', () => {
    els.friendsSearch.value = '';
    loadFriends();
    els.friendsSearch.focus();
  });
  if (els.requestsSearch){
    els.requestsSearch.addEventListener('input', () => {
      window.clearTimeout(state.requestsTimer);
      state.requestsTimer = window.setTimeout(renderRequests, 250);
    });
  }
  if (els.requestsClear){
    els.requestsClear.addEventListener('click', () => {
      els.requestsSearch.value = '';
      renderRequests();
      els.requestsSearch.focus();
    });
  }
  document.addEventListener('click', (event) => {
    document.querySelectorAll('.community-card-menu__list').forEach((list) => {
      if (!list.parentElement.contains(event.target)){
        list.hidden = true;
      }
    });
  });

  setTab(state.tab, state.requestsView);
})();
