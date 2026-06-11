(function () {
  const modal = document.getElementById('termsModal');
  if (!modal) return;

  const required = modal.dataset.required === 'true';
  if (!required) {
    modal.style.display = 'none';
    return;
  }

  const dialog = modal.querySelector('.terms-modal__dialog');
  const errorBox = modal.querySelector('.terms-modal__error');
  const acceptBtn = modal.querySelector('[data-action="accept"]');
  const logoutBtn = modal.querySelector('[data-action="logout"]');
  const acceptUrl = modal.dataset.acceptUrl;
  const logoutUrl = logoutBtn ? logoutBtn.dataset.logoutUrl : '';

  function getCsrfToken() {
    const match = document.cookie.match(/csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : '';
  }

  function showError(message) {
    if (!errorBox) return;
    errorBox.textContent = message || '';
    errorBox.style.display = message ? 'block' : 'none';
  }

  function disableButtons(disabled) {
    if (acceptBtn) acceptBtn.disabled = disabled;
    if (logoutBtn) logoutBtn.disabled = disabled;
  }

  function closeModal() {
    modal.style.display = 'none';
    modal.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('terms-modal-open');
  }

  function openModal() {
    modal.style.display = 'flex';
    modal.setAttribute('aria-hidden', 'false');
    document.body.classList.add('terms-modal-open');
    if (dialog) dialog.focus({ preventScroll: true });
  }

  async function postJson(url) {
    const response = await fetch(url, {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCsrfToken(),
        'X-Requested-With': 'XMLHttpRequest'
      },
      body: '{}'
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const errors = data.errors && (data.errors.__all__ || data.errors);
      const message = Array.isArray(errors) ? errors.join(' ') : (typeof errors === 'string' ? errors : null);
      throw new Error(message || 'Не удалось выполнить запрос.');
    }
    return data;
  }

  if (acceptBtn && acceptUrl) {
    acceptBtn.addEventListener('click', async () => {
      disableButtons(true);
      showError('');
      try {
        await postJson(acceptUrl);
        modal.setAttribute('data-required', 'false');
        closeModal();
      } catch (error) {
        console.error('[terms] accept failed', error);
        showError(error.message);
      } finally {
        disableButtons(false);
      }
    });
  }

  if (logoutBtn && logoutUrl) {
    logoutBtn.addEventListener('click', async () => {
      disableButtons(true);
      showError('');
      try {
        await postJson(logoutUrl);
        closeModal();
        window.location.assign('/');
      } catch (error) {
        console.error('[terms] logout failed', error);
        showError(error.message || 'Не удалось выйти из аккаунта.');
        disableButtons(false);
      }
    });
  }

  openModal();
})();
