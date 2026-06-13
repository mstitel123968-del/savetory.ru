(function(){
  const form = document.getElementById('messageComposeForm');
  if (!form) return;

  const thread = document.getElementById('messagesThread');
  const textInput = document.getElementById('messageComposeText');
  const errorBox = document.getElementById('messageComposeError');
  const submit = form.querySelector('.messages-compose__submit');

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

  function appendMessage(message){
    if (!thread || !message) return;
    const empty = thread.querySelector('.messages-empty');
    if (empty) empty.remove();

    const article = document.createElement('article');
    article.className = `messages-bubble ${message.is_outgoing ? 'messages-bubble--out' : 'messages-bubble--in'}`;

    const text = document.createElement('div');
    text.className = 'messages-bubble__text';
    text.textContent = message.text || '';

    const time = document.createElement('time');
    time.className = 'messages-bubble__time';
    time.dateTime = message.sent_at || '';
    time.textContent = formatTime(message.sent_at);

    article.append(text, time);
    thread.appendChild(article);
    thread.scrollTop = thread.scrollHeight;
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

  if (thread) thread.scrollTop = thread.scrollHeight;
})();
