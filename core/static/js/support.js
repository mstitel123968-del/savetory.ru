(() => {
  const dialog = document.querySelector('#ticket-dialog');
  let opener;
  document.addEventListener('click', async event => {
    if (event.target.closest('[data-reply-focus]')) {
      event.preventDefault();
      document.querySelector('.support-reply textarea')?.focus();
      return;
    }
    if (event.target.closest('[data-ticket-close]') && dialog?.open) {
      event.preventDefault(); dialog.close(); return;
    }
    const row = event.target.closest('[data-ticket-url]');
    if (!row || !dialog || event.ctrlKey || event.metaKey || event.shiftKey) return;
    event.preventDefault(); opener = row.querySelector('a');
    try {
      const response = await fetch(row.dataset.ticketUrl + '?modal=1');
      if (!response.ok || response.redirected) { location.href = row.dataset.ticketUrl; return; }
      dialog.querySelector('[data-ticket-content]').innerHTML = await response.text();
      dialog.setAttribute('aria-labelledby', 'ticket-title');
      if (!dialog.open) dialog.showModal();
    } catch { location.href = row.dataset.ticketUrl; }
  });
  dialog?.addEventListener('close', () => opener?.focus());
  document.addEventListener('submit', async event => {
    const form = event.target.closest('[data-support-form]');
    if (!form) return;
    event.preventDefault();
    const button = form.querySelector('[type=submit]');
    if (button.disabled) return;
    button.disabled = true;
    const status = form.querySelector('[data-form-status]');
    status.textContent = 'Отправка…';
    try {
      const response = await fetch(form.action, { method: 'POST', body: new FormData(form), headers: { 'X-Requested-With': 'XMLHttpRequest' } });
      const data = await response.json();
      if (!response.ok) { status.textContent = data.error || Object.values(data.errors || {}).flat().map(error => error.message).join('\n') || 'Не удалось отправить сообщение.'; button.disabled = false; return; }
      const message = document.createElement('p'); message.setAttribute('role', 'status'); message.textContent = data.message;
      form.replaceWith(message);
      const originalToken = document.querySelector('#support')?.content.querySelector('[name=submission_id]');
      if (originalToken && crypto.randomUUID) originalToken.value = crypto.randomUUID();
    } catch { status.textContent = 'Ошибка соединения. Повторите отправку.'; button.disabled = false; }
  });
})();
