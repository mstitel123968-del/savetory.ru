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
    return meta;
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

  if (thread) thread.scrollTop = thread.scrollHeight;
})();
