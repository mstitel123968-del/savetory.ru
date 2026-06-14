(function(){
  const form = document.getElementById('messageComposeForm');
  if (!form) return;

  const thread = document.getElementById('messagesThread');
  const textInput = document.getElementById('messageComposeText');
  const errorBox = document.getElementById('messageComposeError');
  const submit = form.querySelector('.messages-compose__submit');
  const allowedReactions = ['👍', '❤️', '😂', '😮', '😢'];
  const reactionBusy = new Set();
  const messageBusy = new Set();
  const recipientId = form.dataset.recipientId;

  const STATUS_ICON_SENT = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 13l4.5 4.5L20 6"/></svg>';
  const STATUS_ICON_READ = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M1.5 13.5l4.2 4.2L15 7"/><path d="M9 17.7l.7.7L23 6"/></svg>';

  function csrf(){
    const match = document.cookie.match(/csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : '';
  }

  function setError(message){
    if (errorBox) errorBox.textContent = message || '';
  }

  function formatTime(value){
    const date = value ? new Date(value) : new Date();
    if (Number.isNaN(date.getTime())) return '';
    return date.toLocaleString('ru-RU', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  }

  function buildReactionControls(message){
    const fragment = document.createDocumentFragment();
    if (!message.can_react){
      return fragment;
    }
    const panel = document.createElement('div');
    panel.className = 'messages-reaction-panel';
    panel.setAttribute('role', 'group');
    panel.setAttribute('aria-label', 'Реакции');
    allowedReactions.forEach((reaction) => {
      const option = document.createElement('button');
      option.className = 'messages-reaction-option';
      if (message.viewer_reaction === reaction){
        option.classList.add('is-selected');
      }
      option.type = 'button';
      option.dataset.reaction = reaction;
      option.setAttribute('aria-label', `Реакция ${reaction}`);
      option.textContent = reaction;
      panel.appendChild(option);
    });

    const reactions = document.createElement('div');
    reactions.className = 'messages-reactions';
    reactions.setAttribute('aria-label', 'Поставленные реакции');
    renderReactions(reactions, message);
    fragment.append(panel, reactions);
    return fragment;
  }

  function buildMessageMeta(message){
    const meta = document.createElement('div');
    meta.className = 'messages-bubble__meta';
    const time = document.createElement('time');
    time.className = 'messages-bubble__time';
    time.dateTime = message.sent_at || '';
    time.textContent = message.sent_at_display || formatTime(message.sent_at);
    meta.appendChild(time);
    if (message.is_edited){
      const edited = document.createElement('span');
      edited.className = 'messages-bubble__edited';
      edited.textContent = 'изменено';
      meta.appendChild(edited);
    }
    const status = buildStatusIcon(message);
    if (status){
      meta.appendChild(status);
    }
    return meta;
  }

  function buildStatusIcon(message){
    if (!message.is_outgoing || message.is_deleted){
      return null;
    }
    const status = document.createElement('span');
    status.className = `messages-bubble__status${message.is_read ? ' is-read' : ''}`;
    const label = message.is_read ? 'Прочитано' : 'Отправлено';
    status.title = label;
    status.setAttribute('aria-label', label);
    status.innerHTML = message.is_read ? STATUS_ICON_READ : STATUS_ICON_SENT;
    return status;
  }

  function updateMessageStatus(article, message){
    if (!article) return;
    article.dataset.read = message.is_read ? 'true' : 'false';
    const meta = article.querySelector('.messages-bubble__meta');
    if (!meta) return;
    const current = meta.querySelector('.messages-bubble__status');
    const next = buildStatusIcon(message);
    if (next){
      if (current){
        current.replaceWith(next);
      } else {
        meta.appendChild(next);
      }
    } else if (current){
      current.remove();
    }
  }

  function buildMessageActions(message){
    if (!message.can_edit && !message.can_delete){
      return document.createDocumentFragment();
    }
    const actions = document.createElement('div');
    actions.className = 'messages-message-actions';
    actions.setAttribute('aria-label', 'Действия с сообщением');
    if (message.can_edit){
      const edit = document.createElement('button');
      edit.className = 'messages-message-action';
      edit.type = 'button';
      edit.dataset.messageAction = 'edit';
      edit.textContent = 'Редактировать';
      actions.appendChild(edit);
    }
    if (message.can_delete){
      const remove = document.createElement('button');
      remove.className = 'messages-message-action messages-message-action--danger';
      remove.type = 'button';
      remove.dataset.messageAction = 'delete';
      remove.textContent = 'Удалить';
      actions.appendChild(remove);
    }
    return actions;
  }

  function renderReactions(container, message){
    container.textContent = '';
    (message.reactions || []).forEach((item) => {
      const chip = document.createElement('button');
      chip.className = 'messages-reaction-chip';
      if (item.selected){
        chip.classList.add('is-selected');
      }
      chip.type = 'button';
      chip.dataset.reaction = item.reaction;
      chip.setAttribute('aria-label', `Реакция ${item.reaction}, ${item.count}`);
      const emoji = document.createElement('span');
      emoji.textContent = item.reaction;
      const count = document.createElement('span');
      count.textContent = item.count;
      chip.append(emoji, count);
      container.appendChild(chip);
    });
  }

  function renderMessage(message){
    const article = document.createElement('article');
    article.className = `messages-bubble ${message.is_outgoing ? 'messages-bubble--out' : 'messages-bubble--in'}`;
    if (message.is_deleted){
      article.classList.add('messages-bubble--deleted');
    }
    article.dataset.messageId = message.id;
    article.dataset.outgoing = message.is_outgoing ? 'true' : 'false';
    article.dataset.read = message.is_read ? 'true' : 'false';
    const text = document.createElement('div');
    text.className = 'messages-bubble__text';
    text.textContent = message.text || '';
    text.dataset.rawText = message.raw_text || message.text || '';

    article.append(text, buildMessageMeta(message), buildMessageActions(message), buildReactionControls(message));
    return article;
  }

  function appendMessage(message){
    if (!thread || !message) return;
    const empty = thread.querySelector('.messages-empty');
    if (empty) empty.remove();
    const article = renderMessage(message);
    thread.appendChild(article);
    thread.scrollTop = thread.scrollHeight;
  }

  function updateMessageReactions(message){
    if (!thread || !message) return;
    const article = thread.querySelector(`.messages-bubble[data-message-id="${message.id}"]`);
    if (!article) return;
    article.querySelectorAll('.messages-reaction-option').forEach((option) => {
      option.classList.toggle('is-selected', option.dataset.reaction === message.viewer_reaction);
    });
    const reactions = article.querySelector('.messages-reactions');
    if (reactions){
      renderReactions(reactions, message);
    }
  }

  function replaceMessage(message){
    if (!thread || !message) return;
    const article = thread.querySelector(`.messages-bubble[data-message-id="${message.id}"]`);
    if (!article) return;
    article.replaceWith(renderMessage(message));
  }

  function stopEditing(article, textValue){
    const text = article.querySelector('.messages-bubble__text');
    if (!text) return;
    article.classList.remove('is-editing');
    text.textContent = textValue;
  }

  function startEditing(article){
    if (!article || article.classList.contains('is-editing') || article.classList.contains('messages-bubble--deleted')) return;
    const text = article.querySelector('.messages-bubble__text');
    if (!text) return;
    const currentText = text.dataset.rawText || text.textContent || '';
    article.classList.add('is-editing');
    text.textContent = '';

    const input = document.createElement('textarea');
    input.className = 'messages-edit-input';
    input.rows = 3;
    input.maxLength = 4000;
    input.value = currentText;

    const controls = document.createElement('div');
    controls.className = 'messages-edit-controls';
    const save = document.createElement('button');
    save.className = 'messages-edit-save';
    save.type = 'button';
    save.dataset.messageAction = 'save-edit';
    save.textContent = 'Сохранить';
    const cancel = document.createElement('button');
    cancel.className = 'messages-edit-cancel';
    cancel.type = 'button';
    cancel.dataset.messageAction = 'cancel-edit';
    cancel.textContent = 'Отмена';
    controls.append(save, cancel);
    text.append(input, controls);
    input.focus();
    input.setSelectionRange(input.value.length, input.value.length);
  }

  async function saveEdit(article){
    const messageId = article && article.dataset.messageId;
    const input = article ? article.querySelector('.messages-edit-input') : null;
    if (!messageId || !input || messageBusy.has(messageId)) return;
    const text = (input.value || '').trim();
    if (!text){
      setError('Введите текст сообщения.');
      input.focus();
      return;
    }
    messageBusy.add(messageId);
    article.classList.add('is-message-busy');
    try {
      const response = await fetch(`/api/messages/${messageId}/edit/`, {
        method: 'PATCH',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrf(),
        },
        body: JSON.stringify({ text }),
      });
      const data = await response.json().catch(() => null);
      if (!response.ok || !data || data.success === false){
        throw new Error((data && data.error) || 'Не удалось сохранить сообщение.');
      }
      replaceMessage(data.message);
    } catch (error){
      setError(error.message || 'Не удалось сохранить сообщение.');
    } finally {
      messageBusy.delete(messageId);
      article.classList.remove('is-message-busy');
    }
  }

  async function deleteMessage(article){
    const messageId = article && article.dataset.messageId;
    if (!messageId || messageBusy.has(messageId)) return;
    if (!window.confirm('Удалить сообщение?')){
      return;
    }
    messageBusy.add(messageId);
    article.classList.add('is-message-busy');
    try {
      const response = await fetch(`/api/messages/${messageId}/delete/`, {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrf(),
        },
        body: JSON.stringify({}),
      });
      const data = await response.json().catch(() => null);
      if (!response.ok || !data || data.success === false){
        throw new Error((data && data.error) || 'Не удалось удалить сообщение.');
      }
      replaceMessage(data.message);
    } catch (error){
      setError(error.message || 'Не удалось удалить сообщение.');
    } finally {
      messageBusy.delete(messageId);
      article.classList.remove('is-message-busy');
    }
  }

  async function setReaction(messageId, reaction){
    if (!messageId || reactionBusy.has(messageId)) return;
    reactionBusy.add(messageId);
    const article = thread ? thread.querySelector(`.messages-bubble[data-message-id="${messageId}"]`) : null;
    if (article){
      article.classList.add('is-reacting');
    }
    try {
      const response = await fetch(`/api/messages/${messageId}/reaction/`, {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrf(),
        },
        body: JSON.stringify({ reaction }),
      });
      const data = await response.json().catch(() => null);
      if (!response.ok || !data || data.success === false){
        throw new Error((data && data.error) || 'Не удалось изменить реакцию.');
      }
      updateMessageReactions(data.message);
    } catch (error){
      setError(error.message || 'Не удалось изменить реакцию.');
    } finally {
      reactionBusy.delete(messageId);
      if (article){
        article.classList.remove('is-reacting');
      }
    }
  }

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    setError('');
    const text = (textInput.value || '').trim();
    if (!text){
      setError('Введите текст сообщения.');
      textInput.focus();
      return;
    }
    submit.disabled = true;
    try {
      const response = await fetch('/api/messages/send/', {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrf(),
        },
        body: JSON.stringify({
          recipient_id: form.dataset.recipientId,
          text,
        }),
      });
      const data = await response.json().catch(() => null);
      if (!response.ok || !data || data.success === false){
        throw new Error((data && data.error) || 'Не удалось отправить сообщение.');
      }
      appendMessage(data.message);
      textInput.value = '';
      textInput.focus();
    } catch (error){
      setError(error.message || 'Не удалось отправить сообщение.');
    } finally {
      submit.disabled = false;
    }
  });

  if (thread){
    thread.addEventListener('mouseover', (event) => {
      const article = event.target.closest('.messages-bubble[data-message-id]');
      if (article && !article.contains(event.relatedTarget)){
        article.classList.remove('is-reaction-panel-closed');
      }
    });

    thread.addEventListener('click', (event) => {
      const actionButton = event.target.closest('[data-message-action]');
      if (actionButton){
        const article = actionButton.closest('.messages-bubble[data-message-id]');
        if (!article) return;
        const action = actionButton.dataset.messageAction;
        setError('');
        if (action === 'edit'){
          startEditing(article);
        } else if (action === 'delete'){
          deleteMessage(article);
        } else if (action === 'save-edit'){
          saveEdit(article);
        } else if (action === 'cancel-edit'){
          const text = article.querySelector('.messages-bubble__text');
          stopEditing(article, text ? text.dataset.rawText || '' : '');
        }
        return;
      }

      const reactionButton = event.target.closest('.messages-reaction-option, .messages-reaction-chip');
      if (!reactionButton) return;
      const article = reactionButton.closest('.messages-bubble[data-message-id]');
      if (!article) return;
      setError('');
      article.classList.add('is-reaction-panel-closed');
      setReaction(article.dataset.messageId, reactionButton.dataset.reaction || '');
    });
  }

  // ---------------------------------------------------------------------------
  // Read receipts: mark incoming messages read once they are actually visible
  // in the thread viewport while the tab is active. Requests are batched.
  // ---------------------------------------------------------------------------
  const pendingRead = new Set();
  let markReadTimer = null;

  function isBubbleVisible(article){
    if (!thread) return false;
    const threadRect = thread.getBoundingClientRect();
    const rect = article.getBoundingClientRect();
    return rect.bottom > threadRect.top && rect.top < threadRect.bottom;
  }

  function flushPendingRead(){
    markReadTimer = null;
    if (!pendingRead.size || !recipientId) return;
    const ids = Array.from(pendingRead);
    pendingRead.clear();
    fetch(`/api/messages/users/${recipientId}/read/`, {
      method: 'POST',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': csrf(),
      },
      body: JSON.stringify({ message_ids: ids }),
    }).catch(() => {
      // Marking read is best-effort; re-queue on failure for the next pass.
      ids.forEach((id) => pendingRead.add(id));
    });
  }

  function scheduleMarkRead(){
    if (markReadTimer) return;
    markReadTimer = window.setTimeout(flushPendingRead, 400);
  }

  function markVisibleIncoming(){
    if (!thread || document.visibilityState !== 'visible') return;
    thread.querySelectorAll('.messages-bubble--in[data-message-id]').forEach((article) => {
      if (article.dataset.read === 'true' || article.classList.contains('messages-bubble--deleted')){
        return;
      }
      if (isBubbleVisible(article)){
        article.dataset.read = 'true';
        pendingRead.add(article.dataset.messageId);
      }
    });
    if (pendingRead.size){
      scheduleMarkRead();
    }
  }

  // ---------------------------------------------------------------------------
  // Reaction panel positioning: keep the panel on-screen, flipping below the
  // bubble when the fixed topbar would otherwise cover it.
  // ---------------------------------------------------------------------------
  const topbar = document.querySelector('.topbar');
  let activeReactionBubble = null;

  function positionReactionPanel(article){
    if (!article) return;
    const panel = article.querySelector('.messages-reaction-panel');
    if (!panel) return;
    const gap = 8;
    const viewportPadding = 8;
    const bubbleRect = article.getBoundingClientRect();
    const panelRect = panel.getBoundingClientRect();
    const panelWidth = panelRect.width || 194;
    const panelHeight = panelRect.height || 40;
    const topbarBottom = topbar ? topbar.getBoundingClientRect().bottom : 0;
    const spaceAbove = bubbleRect.top - topbarBottom;

    let top;
    if (spaceAbove >= panelHeight + gap){
      top = bubbleRect.top - panelHeight - gap;
      panel.classList.remove('messages-reaction-panel--below');
    } else {
      top = bubbleRect.bottom + gap;
      panel.classList.add('messages-reaction-panel--below');
    }

    let left = bubbleRect.right - panelWidth;
    const maxLeft = window.innerWidth - panelWidth - viewportPadding;
    left = Math.min(Math.max(viewportPadding, left), Math.max(viewportPadding, maxLeft));

    panel.style.position = 'fixed';
    panel.style.left = `${Math.round(left)}px`;
    panel.style.top = `${Math.round(top)}px`;
    panel.style.right = 'auto';
    panel.style.bottom = 'auto';
  }

  function clearReactionPanel(article){
    if (!article) return;
    const panel = article.querySelector('.messages-reaction-panel');
    if (!panel) return;
    panel.style.position = '';
    panel.style.left = '';
    panel.style.top = '';
    panel.style.right = '';
    panel.style.bottom = '';
    panel.classList.remove('messages-reaction-panel--below');
  }

  function repositionActiveReaction(){
    if (activeReactionBubble){
      positionReactionPanel(activeReactionBubble);
    }
  }

  if (thread){
    thread.addEventListener('pointerover', (event) => {
      const article = event.target.closest('.messages-bubble[data-message-id]');
      if (!article || !article.querySelector('.messages-reaction-panel')) return;
      if (article === activeReactionBubble) return;
      if (activeReactionBubble && activeReactionBubble !== article){
        clearReactionPanel(activeReactionBubble);
      }
      activeReactionBubble = article;
      requestAnimationFrame(() => positionReactionPanel(article));
    });

    thread.addEventListener('pointerout', (event) => {
      const article = event.target.closest('.messages-bubble[data-message-id]');
      if (!article || article !== activeReactionBubble) return;
      if (article.contains(event.relatedTarget)) return;
      clearReactionPanel(article);
      if (activeReactionBubble === article){
        activeReactionBubble = null;
      }
    });

    thread.addEventListener('focusin', (event) => {
      const article = event.target.closest('.messages-bubble[data-message-id]');
      if (!article || !article.querySelector('.messages-reaction-panel')) return;
      activeReactionBubble = article;
      requestAnimationFrame(() => positionReactionPanel(article));
    });

    thread.addEventListener('scroll', () => {
      repositionActiveReaction();
      markVisibleIncoming();
    }, { passive: true });
  }

  window.addEventListener('resize', repositionActiveReaction);
  window.addEventListener('scroll', repositionActiveReaction, true);

  // ---------------------------------------------------------------------------
  // Lightweight polling: refresh read receipts and pick up new messages without
  // a full page reload, reusing the existing history endpoint (no marking).
  // ---------------------------------------------------------------------------
  function isNearBottom(){
    if (!thread) return true;
    return thread.scrollHeight - thread.scrollTop - thread.clientHeight < 80;
  }

  function reconcileMessage(message){
    if (!thread) return false;
    const article = thread.querySelector(`.messages-bubble[data-message-id="${message.id}"]`);
    if (!article){
      const empty = thread.querySelector('.messages-empty');
      if (empty) empty.remove();
      thread.appendChild(renderMessage(message));
      return true;
    }
    if (article.classList.contains('is-editing') || article.classList.contains('is-message-busy')){
      return false;
    }
    const wasDeleted = article.classList.contains('messages-bubble--deleted');
    const wasEdited = !!article.querySelector('.messages-bubble__edited');
    if (message.is_deleted !== wasDeleted || message.is_edited !== wasEdited){
      article.replaceWith(renderMessage(message));
      return false;
    }
    if (message.is_outgoing){
      updateMessageStatus(article, message);
    }
    updateMessageReactions(message);
    return false;
  }

  async function pollMessages(){
    if (!recipientId) return;
    try {
      const response = await fetch(`/api/messages/users/${recipientId}/`, {
        credentials: 'include',
        headers: { 'Accept': 'application/json' },
      });
      if (!response.ok) return;
      const data = await response.json().catch(() => null);
      if (!data || data.success === false || !Array.isArray(data.messages)) return;
      const stickToBottom = isNearBottom();
      let appended = false;
      data.messages.forEach((message) => {
        if (reconcileMessage(message)){
          appended = true;
        }
      });
      if (appended && stickToBottom && thread){
        thread.scrollTop = thread.scrollHeight;
      }
      markVisibleIncoming();
    } catch (error){
      // Polling stays silent.
    }
  }

  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible'){
      markVisibleIncoming();
      pollMessages();
    }
  });

  if (thread){
    thread.scrollTop = thread.scrollHeight;
    markVisibleIncoming();
    window.setInterval(pollMessages, 8000);
  }
})();
