(function(){
  function csrf(){
    const m = document.cookie.match(/csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : '';
  }

  function showRegisterErrors(data, regLoginErr, regPassErr, regEmailErr){
    const errors = data && data.errors ? data.errors : null;
    if (!errors){
      if (regLoginErr) regLoginErr.textContent = 'Ошибка регистрации';
      return;
    }

    if (errors.username && regLoginErr){
      regLoginErr.textContent = String(errors.username[0] || 'Некорректный логин');
    }
    if ((errors.password1 || errors.password2) && regPassErr){
      regPassErr.textContent = String(
        (errors.password1 && errors.password1[0]) ||
        (errors.password2 && errors.password2[0]) ||
        'Некорректный пароль'
      );
    }
    if (errors.email && regEmailErr){
      regEmailErr.textContent = String(errors.email[0] || 'Некорректный email');
    }

    const fallback = Object.values(errors).flat().map(String).find(Boolean);
    if (!regLoginErr?.textContent && !regPassErr?.textContent && !regEmailErr?.textContent && fallback && regLoginErr){
      regLoginErr.textContent = fallback;
    }
  }

  function buildStrongPassword(length = 16){
    const lower = 'abcdefghijkmnopqrstuvwxyz';
    const upper = 'ABCDEFGHJKLMNPQRSTUVWXYZ';
    const digits = '23456789';
    const symbols = '!@#$%^&*()-_=+[]{};:,.?/';
    const all = lower + upper + digits + symbols;

    const cryptoObj = window.crypto || window.msCrypto;
    function pick(source){
      if (!cryptoObj || !cryptoObj.getRandomValues){
        return source[Math.floor(Math.random() * source.length)];
      }
      const arr = new Uint32Array(1);
      cryptoObj.getRandomValues(arr);
      return source[arr[0] % source.length];
    }

    const chars = [
      pick(lower), pick(upper), pick(digits), pick(symbols),
    ];
    while (chars.length < Math.max(12, length)){
      chars.push(pick(all));
    }
    for (let i = chars.length - 1; i > 0; i -= 1){
      const j = Math.floor(Math.random() * (i + 1));
      [chars[i], chars[j]] = [chars[j], chars[i]];
    }
    return chars.join('');
  }

  async function copyToClipboard(text){
    if (navigator.clipboard && window.isSecureContext){
      await navigator.clipboard.writeText(text);
      return;
    }

    const temp = document.createElement('textarea');
    temp.value = text;
    temp.setAttribute('readonly', 'readonly');
    temp.style.position = 'fixed';
    temp.style.opacity = '0';
    temp.style.pointerEvents = 'none';
    document.body.appendChild(temp);
    temp.select();
    temp.setSelectionRange(0, text.length);
    const ok = document.execCommand('copy');
    document.body.removeChild(temp);
    if (!ok){
      throw new Error('copy command failed');
    }
  }

  function mountPasswordTools(regPass, regPass2, regPassErr){
    if (!regPass || !regPass2 || regPass.dataset.generatorMounted === '1') return;

    const row = document.createElement('div');
    row.className = 'modal-pass-tools';

    const genBtn = document.createElement('button');
    genBtn.type = 'button';
    genBtn.className = 'btn modal-pass-tools__btn';
    genBtn.textContent = 'Сгенерировать пароль';

    const copyBtn = document.createElement('button');
    copyBtn.type = 'button';
    copyBtn.className = 'btn modal-pass-tools__btn';
    copyBtn.textContent = 'Скопировать';

    const copyFeedback = document.createElement('small');
    copyFeedback.className = 'modal-pass-tools__feedback';

    genBtn.addEventListener('click', ()=>{
      const generated = buildStrongPassword(16);
      regPass.value = generated;
      regPass2.value = generated;
      if (regPassErr) regPassErr.textContent = '';
      copyFeedback.textContent = '';
      regPass.dispatchEvent(new Event('input', { bubbles: true }));
      regPass2.dispatchEvent(new Event('input', { bubbles: true }));
    });

    copyBtn.addEventListener('click', async ()=>{
      const currentPassword = String(regPass.value || '');
      if (!currentPassword){
        if (regPassErr) regPassErr.textContent = 'Сначала сгенерируйте или введите пароль';
        return;
      }

      try {
        await copyToClipboard(currentPassword);
        copyFeedback.textContent = 'Пароль скопирован в буфер обмена';
        copyBtn.textContent = 'Скопировано';
        setTimeout(()=>{
          copyBtn.textContent = 'Скопировать';
          copyFeedback.textContent = '';
        }, 1600);
      } catch (e){
        console.error('[auth] copy password failed', e);
        copyFeedback.textContent = 'Не удалось скопировать пароль';
      }
    });

    row.appendChild(genBtn);
    row.appendChild(copyBtn);
    regPass2.insertAdjacentElement('afterend', row);
    row.insertAdjacentElement('afterend', copyFeedback);
    regPass.dataset.generatorMounted = '1';
  }

  function bindAuthModal(){
    const modal = document.getElementById('authModal');
    const tabs = Array.from(document.querySelectorAll('.tab'));
    const tabContents = Array.from(document.querySelectorAll('.tab-content'));
    const openBtns = Array.from(document.querySelectorAll('[data-open-auth]'));

    const loginUser = document.getElementById('loginUser');
    const loginPass = document.getElementById('loginPass');
    const loginBtn = document.querySelector('#login .btn');
    const loginErr = document.getElementById('loginAuthError');

    const regLogin = document.getElementById('regLogin');
    const regPass = document.getElementById('regPass');
    const regPass2 = document.getElementById('regPass2');
    const regEmail = document.getElementById('regEmail');
    const regBtn = document.getElementById('registerSubmit');
    const regLoginErr = document.getElementById('loginError');
    const regPassErr = document.getElementById('passError');
    const regEmailErr = document.getElementById('emailError');
    const registrationFields = document.getElementById('registrationFields');
    const verification = document.getElementById('registrationVerification');
    const codeMessage = document.getElementById('registrationCodeMessage');
    const codeInputs = verification ? Array.from(verification.querySelectorAll('.code-input')) : [];
    const codeError = document.getElementById('registrationCodeError');
    const verifyBtn = document.getElementById('registrationVerify');
    const resendBtn = document.getElementById('registrationResend');
    const resendNote = document.getElementById('registrationResendNote');
    const expiresNote = document.getElementById('registrationExpiresNote');
    const changeEmailBtn = document.getElementById('registrationChangeEmail');

    mountPasswordTools(regPass, regPass2, regPassErr);

    function getAuthRedirectUrl(){
      const raw = modal ? String(modal.dataset.authRedirect || '') : '';
      if (raw && raw.startsWith('/') && !raw.startsWith('//')){
        return raw;
      }
      return '/archive/';
    }

    function activateTab(target){
      if (!target) return;
      tabs.forEach((tab)=>{
        const isActive = tab.getAttribute('data-tab') === target;
        tab.classList.toggle('active', isActive);
      });
      tabContents.forEach((tc)=>tc.classList.toggle('active', tc.id === target));
    }

    const regTermsModal = document.getElementById('registrationTermsModal');
    const regTermsDialog = regTermsModal ? regTermsModal.querySelector('.reg-terms-modal__dialog') : null;
    const regTermsError = regTermsModal ? regTermsModal.querySelector('.reg-terms-modal__error') : null;
    const regTermsAcceptBtn = regTermsModal ? regTermsModal.querySelector('[data-action="accept"]') : null;
    const regTermsDeclineBtn = regTermsModal ? regTermsModal.querySelector('[data-action="decline"]') : null;
    const termsVersion = regTermsModal ? String(regTermsModal.dataset.termsVersion || '') : '';

    let pendingRegistrationPayload = null;
    let verificationEmail = '';
    let verificationBusy = false;
    let resendDeadline = 0;
    let expiryDeadline = 0;
    let countdownTimer = null;

    function codeValue(){ return codeInputs.map((input)=>input.value).join(''); }

    function syncCodeButton(){
      if (verifyBtn) verifyBtn.disabled = verificationBusy || !/^\d{6}$/.test(codeValue());
    }

    function updateCountdowns(){
      const now = Date.now();
      const resendSeconds = Math.max(0, Math.ceil((resendDeadline - now) / 1000));
      const expirySeconds = Math.max(0, Math.ceil((expiryDeadline - now) / 1000));
      if (resendBtn) resendBtn.disabled = verificationBusy || resendSeconds > 0;
      if (resendNote) resendNote.textContent = resendSeconds > 0 ? `Повторная отправка через ${resendSeconds} сек.` : 'Код можно отправить повторно.';
      if (expiresNote) expiryNoteText(expirySeconds);
    }

    function expiryNoteText(seconds){
      if (!expiresNote) return;
      const minutes = Math.floor(seconds / 60);
      const rest = seconds % 60;
      expiresNote.textContent = seconds > 0 ? `Код действует ещё ${minutes}:${String(rest).padStart(2, '0')}.` : 'Срок действия кода истёк.';
    }

    function startCountdowns(resendIn, expiresIn){
      resendDeadline = Date.now() + Number(resendIn || 60) * 1000;
      expiryDeadline = Date.now() + Number(expiresIn || 600) * 1000;
      if (countdownTimer) clearInterval(countdownTimer);
      updateCountdowns();
      countdownTimer = setInterval(updateCountdowns, 1000);
    }

    function showVerification(email, resendIn, expiresIn){
      verificationEmail = email || (regEmail ? regEmail.value.trim() : '');
      if (registrationFields) registrationFields.hidden = true;
      if (verification) verification.hidden = false;
      if (codeMessage) codeMessage.textContent = `Мы отправили код на адрес ${verificationEmail}`;
      if (codeError) codeError.textContent = '';
      codeInputs.forEach((input)=>{ input.value = ''; });
      startCountdowns(resendIn, expiresIn);
      syncCodeButton();
      if (codeInputs[0]) codeInputs[0].focus();
    }

    function showRegistrationFields(){
      if (verification) verification.hidden = true;
      if (registrationFields) registrationFields.hidden = false;
      if (countdownTimer) clearInterval(countdownTimer);
      verificationBusy = false;
      if (regEmail) regEmail.focus();
    }

    function setTermsModalBusy(isBusy){
      if (regTermsAcceptBtn) regTermsAcceptBtn.disabled = isBusy;
      if (regTermsDeclineBtn) regTermsDeclineBtn.disabled = isBusy;
    }

    function showTermsModalError(message){
      if (!regTermsError) return;
      regTermsError.textContent = message || '';
      regTermsError.style.display = message ? 'block' : 'none';
    }

    function openRegistrationTermsModal(payload){
      if (!regTermsModal || !regTermsDialog) {
        return false;
      }
      pendingRegistrationPayload = payload;
      showTermsModalError('');
      setTermsModalBusy(false);
      regTermsModal.style.display = 'flex';
      regTermsModal.setAttribute('aria-hidden', 'false');
      document.body.classList.add('reg-terms-modal-open');
      regTermsDialog.focus({ preventScroll: true });
      return true;
    }

    function closeRegistrationTermsModal(){
      if (!regTermsModal) return;
      regTermsModal.style.display = 'none';
      regTermsModal.setAttribute('aria-hidden', 'true');
      document.body.classList.remove('reg-terms-modal-open');
      showTermsModalError('');
      setTermsModalBusy(false);
      pendingRegistrationPayload = null;
    }

    async function submitRegistrationAfterTerms(){
      if (!pendingRegistrationPayload) return;
      setTermsModalBusy(true);
      showTermsModalError('');
      const body = new URLSearchParams({
        code: pendingRegistrationPayload.code,
        terms_accepted: '1',
        terms_version: termsVersion,
      });
      try {
        const resp = await fetch('/api/auth/register/verify/', {
          method: 'POST',
          credentials: 'same-origin',
          headers: { 'X-CSRFToken': csrf(), 'Content-Type': 'application/x-www-form-urlencoded' },
          body,
        });
        const data = await resp.json().catch(() => ({ success: false }));

        if (!resp.ok || !data.success){
          console.error('[auth] verification failed after terms accept', { status: resp.status, data });
          showTermsModalError(data.error || Object.values(data.errors || {}).flat()[0] || 'Не удалось подтвердить код.');
          setTermsModalBusy(false);
          return;
        }

        closeRegistrationTermsModal();
        if (countdownTimer) clearInterval(countdownTimer);
        hideModal();
        window.location.assign('/archive/');
      } catch (err){
        console.error('[auth] register request error after terms accept', err);
        showTermsModalError('Не удалось завершить регистрацию. Попробуйте ещё раз.');
        setTermsModalBusy(false);
      }
    }

    if (regTermsAcceptBtn){
      regTermsAcceptBtn.addEventListener('click', submitRegistrationAfterTerms);
    }

    if (regTermsDeclineBtn){
      regTermsDeclineBtn.addEventListener('click', ()=>{
        closeRegistrationTermsModal();
      });
    }

    if (regTermsModal){
      regTermsModal.addEventListener('click', (e)=>{
        if (e.target === regTermsModal){
          closeRegistrationTermsModal();
        }
      });
      document.addEventListener('keydown', (e)=>{
        if (e.key === 'Escape' && regTermsModal.getAttribute('aria-hidden') === 'false'){
          closeRegistrationTermsModal();
        }
      });
    }

    codeInputs.forEach((input, index)=>{
      input.addEventListener('input', ()=>{
        input.value = input.value.replace(/\D/g, '').slice(-1);
        if (input.value && codeInputs[index + 1]) codeInputs[index + 1].focus();
        if (codeError) codeError.textContent = '';
        syncCodeButton();
      });
      input.addEventListener('keydown', (event)=>{
        if (event.key === 'Backspace' && !input.value && codeInputs[index - 1]) codeInputs[index - 1].focus();
      });
      input.addEventListener('paste', (event)=>{
        const digits = String(event.clipboardData?.getData('text') || '').replace(/\D/g, '').slice(0, 6);
        if (!digits) return;
        event.preventDefault();
        codeInputs.forEach((field, i)=>{ field.value = digits[i] || ''; });
        (codeInputs[Math.min(digits.length, 6) - 1] || input).focus();
        syncCodeButton();
      });
    });

    if (verifyBtn){
      verifyBtn.addEventListener('click', ()=>{
        const code = codeValue();
        if (verificationBusy || !/^\d{6}$/.test(code)) return;
        if (codeError) codeError.textContent = '';
        const opened = openRegistrationTermsModal({ code });
        if (!opened){
          if (codeError) codeError.textContent = 'Не удалось открыть пользовательское соглашение.';
        }
      });
    }

    if (resendBtn){
      resendBtn.addEventListener('click', async ()=>{
        if (verificationBusy || Date.now() < resendDeadline) return;
        verificationBusy = true;
        updateCountdowns();
        try {
          const resp = await fetch('/api/auth/register/resend/', {
            method:'POST', credentials:'same-origin',
            headers:{'X-CSRFToken':csrf(),'Content-Type':'application/x-www-form-urlencoded'},
            body:new URLSearchParams(),
          });
          const data = await resp.json().catch(()=>({success:false}));
          if (!resp.ok || !data.success){
            if (data.retry_after) resendDeadline = Date.now() + Number(data.retry_after) * 1000;
            if (codeError) codeError.textContent = data.error || 'Не удалось отправить код.';
            return;
          }
          if (codeError) codeError.textContent = '';
          codeInputs.forEach((input)=>{ input.value=''; });
          startCountdowns(data.resend_in, data.expires_in);
          syncCodeButton();
          if (codeInputs[0]) codeInputs[0].focus();
        } catch (err){
          if (codeError) codeError.textContent = 'Не удалось отправить код. Попробуйте ещё раз.';
        } finally {
          verificationBusy = false;
          updateCountdowns();
        }
      });
    }

    if (changeEmailBtn) changeEmailBtn.addEventListener('click', showRegistrationFields);

    let debounceTimer = null;
    let availabilityRequestId = 0;
    let availabilityAbortController = null;
    let usernameAvailable = true;
    let emailAvailable = true;

    function syncRegisterButtonState(){
      if (!regBtn) return;
      regBtn.disabled = !usernameAvailable || !emailAvailable;
    }

    function showModal(){ if (modal) modal.style.display = 'flex'; }
    function hideModal(){ if (modal) modal.style.display = 'none'; }

    function clearErrors(){
      if (loginErr) loginErr.textContent = '';
      if (regLoginErr) regLoginErr.textContent = '';
      if (regPassErr) regPassErr.textContent = '';
      if (regEmailErr) regEmailErr.textContent = '';
    }

    async function runAvailabilityCheck(){
      const username = (regLogin && regLogin.value || '').trim();
      const email = (regEmail && regEmail.value || '').trim();

      if (!username && !email){
        usernameAvailable = true;
        emailAvailable = true;
        if (regLoginErr) regLoginErr.textContent = '';
        if (regEmailErr) regEmailErr.textContent = '';
        syncRegisterButtonState();
        return;
      }

      availabilityRequestId += 1;
      const currentId = availabilityRequestId;

      if (availabilityAbortController){
        availabilityAbortController.abort();
      }
      availabilityAbortController = new AbortController();

      try {
        const params = new URLSearchParams();
        if (username) params.set('username', username);
        if (email) params.set('email', email);

        const resp = await fetch(`/api/auth/check-availability/?${params.toString()}`, {
          method: 'GET',
          credentials: 'same-origin',
          signal: availabilityAbortController.signal,
        });
        const data = await resp.json().catch(()=>({ success: false }));

        if (currentId !== availabilityRequestId){
          return;
        }

        if (!resp.ok || !data.success){
          console.error('[auth] availability check failed', { status: resp.status, data });
          return;
        }

        usernameAvailable = data.username_available !== false;
        emailAvailable = data.email_available !== false;

        if (regLoginErr){
          regLoginErr.textContent = usernameAvailable ? '' : 'Этот логин уже занят';
        }
        if (regEmailErr){
          regEmailErr.textContent = emailAvailable ? '' : 'Этот email уже используется';
        }
        syncRegisterButtonState();
      } catch (err){
        if (err && err.name === 'AbortError') return;
        console.error('[auth] availability request error', err);
      }
    }

    function scheduleAvailabilityCheck(){
      if (debounceTimer) clearTimeout(debounceTimer);
      debounceTimer = setTimeout(runAvailabilityCheck, 350);
    }

    openBtns.forEach((btn)=>btn.addEventListener('click', ()=>{
      const targetTab = btn.getAttribute('data-auth-tab');
      if (targetTab){
        activateTab(targetTab);
      }
      showModal();
    }));
    if (modal){
      window.addEventListener('click', (e)=>{ if (e.target === modal) hideModal(); });
    }

    tabs.forEach((tab)=>{
      tab.addEventListener('click', ()=>{
        activateTab(tab.getAttribute('data-tab'));
      });
    });

    if (regLogin) regLogin.addEventListener('input', scheduleAvailabilityCheck);
    if (regEmail) regEmail.addEventListener('input', scheduleAvailabilityCheck);

    if (loginBtn){
      loginBtn.addEventListener('click', async (e)=>{
        e.preventDefault();
        clearErrors();
        const username = (loginUser && loginUser.value || '').trim();
        const password = (loginPass && loginPass.value || '').trim();

        if (!username || !password){
          if (loginErr) loginErr.textContent = 'Заполните логин и пароль.';
          return;
        }

        try {
          const body = new URLSearchParams({ username, password });
          const resp = await fetch('/api/auth/login/', {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'X-CSRFToken': csrf(), 'Content-Type': 'application/x-www-form-urlencoded' },
            body,
          });
          const data = await resp.json().catch(() => ({ success: false }));

          if (!resp.ok || !data.success){
            console.error('[auth] login failed', { status: resp.status, data });
            if (loginErr) loginErr.textContent = 'Неверные логин или пароль';
            return;
          }

          hideModal();
          window.location.assign(getAuthRedirectUrl());
        } catch (err){
          console.error('[auth] login request error', err);
          if (loginErr) loginErr.textContent = 'Неверные логин или пароль';
        }
      });
    }

    if (regBtn){
      regBtn.addEventListener('click', async (e)=>{
        e.preventDefault();
        clearErrors();

        const username = (regLogin && regLogin.value || '').trim();
        const email = (regEmail && regEmail.value || '').trim();
        const password1 = (regPass && regPass.value || '').trim();
        const password2 = (regPass2 && regPass2.value || '').trim();

        if (!username || !email || !password1 || !password2){
          if (regLoginErr) regLoginErr.textContent = 'Заполните все поля.';
          return;
        }
        if (password1 !== password2){
          if (regPassErr) regPassErr.textContent = 'Пароли не совпадают';
          return;
        }

        if (!usernameAvailable || !emailAvailable){
          if (!usernameAvailable && regLoginErr) regLoginErr.textContent = 'Этот логин уже занят';
          if (!emailAvailable && regEmailErr) regEmailErr.textContent = 'Этот email уже используется';
          return;
        }

        regBtn.disabled = true;
        try {
          const resp = await fetch('/api/auth/register/', {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'X-CSRFToken': csrf(), 'Content-Type': 'application/x-www-form-urlencoded' },
            body: new URLSearchParams({ username, email, password1, password2 }),
          });
          const data = await resp.json().catch(() => ({ success: false }));
          if (!resp.ok || !data.success){
            showRegisterErrors(data, regLoginErr, regPassErr, regEmailErr);
            return;
          }
          showVerification(data.email || email, data.resend_in, data.expires_in);
        } catch (err){
          console.error('[auth] registration code request error', err);
          if (regEmailErr) regEmailErr.textContent = 'Не удалось отправить код. Попробуйте ещё раз.';
        } finally {
          syncRegisterButtonState();
        }
      });
    }

  }

  if (document.readyState === 'loading'){
    document.addEventListener('DOMContentLoaded', bindAuthModal);
  } else {
    bindAuthModal();
  }
})();
