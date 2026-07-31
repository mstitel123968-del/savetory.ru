(function () {
  'use strict';

  if (window.__savetoryMetrikaBootstrap) return;
  window.__savetoryMetrikaBootstrap = true;

  const configNode = document.currentScript;
  const counterId = Number(configNode && configNode.dataset.counterId) || 111189704;
  const cookieName = (configNode && configNode.dataset.consentCookie) || 'savetory_analytics_consent';
  const serverConsent = (configNode && configNode.dataset.consent) || '';
  const webvisorEnabled = Boolean(configNode && configNode.dataset.webvisor === 'true');
  const storageKey = 'savetory_analytics_consent_v1';
  const allowedGoals = new Set([
    'start_click',
    'registration_open',
    'registration_code_sent',
    'registration_complete',
    'login_complete',
    'rubric_created',
    'card_created',
    'market_publish',
    'tariff_open',
    'payment_started',
    'payment_success',
  ]);

  function storedConsent() {
    let localValue = '';
    try { localValue = window.localStorage.getItem(storageKey) || ''; } catch (error) {}
    const cookieMatch = document.cookie.match(new RegExp('(?:^|;\\s*)' + cookieName + '=([^;]*)'));
    const cookieValue = cookieMatch ? decodeURIComponent(cookieMatch[1]) : serverConsent;
    if (localValue === 'declined' || cookieValue === 'declined') return 'declined';
    if (localValue === 'accepted' || cookieValue === 'accepted') return 'accepted';
    return '';
  }

  function saveConsent(value) {
    try { window.localStorage.setItem(storageKey, value); } catch (error) {}
    const secure = window.location.protocol === 'https:' ? '; Secure' : '';
    document.cookie = cookieName + '=' + encodeURIComponent(value)
      + '; Path=/; Max-Age=31536000; SameSite=Lax' + secure;
  }

  function sanitizedPath(pathname) {
    let path = String(pathname || '/').split('?')[0].split('#')[0] || '/';
    path = path.replace(/^\/u\/[^/]+\/[^/]+\/?$/i, '/u/public-collection/');
    path = path.replace(/^\/community\/users\/[^/]+\/?$/i, '/community/users/profile/');
    path = path.replace(/^\/messages\/\d+\/?$/i, '/messages/dialog/');
    return path;
  }

  function sanitizedReferrer() {
    if (!document.referrer) return '';
    try {
      const referrer = new URL(document.referrer);
      if (referrer.origin !== window.location.origin) return '';
      return sanitizedPath(referrer.pathname);
    } catch (error) {
      return '';
    }
  }

  function protectPrivateContent(root) {
    const scope = root && root.querySelectorAll ? root : document;
    const hiddenSelector = '#authModal, #registrationTermsModal, [data-profile-menu], '
      + '[data-cookie-consent], [data-message-dialog], [data-public-card-id]';
    if (scope.nodeType === 1 && scope.matches && scope.matches(hiddenSelector)) {
      scope.classList.add('ym-hide-content');
    }
    scope.querySelectorAll('input, textarea, [contenteditable="true"]').forEach(function (node) {
      node.classList.add('ym-disable-keys');
    });
    scope.querySelectorAll(hiddenSelector).forEach(function (node) {
      node.classList.add('ym-hide-content');
    });
  }

  function startPrivacyObserver() {
    protectPrivateContent(document);
    if (!window.MutationObserver || !document.documentElement) return;
    const observer = new MutationObserver(function (mutations) {
      mutations.forEach(function (mutation) {
        mutation.addedNodes.forEach(function (node) {
          if (node.nodeType !== 1) return;
          if (node.matches && node.matches('input, textarea, [contenteditable="true"]')) {
            node.classList.add('ym-disable-keys');
          }
          protectPrivateContent(node);
        });
      });
    });
    observer.observe(document.documentElement, { childList: true, subtree: true });
  }

  function createYmStub() {
    window.ym = window.ym || function () {
      (window.ym.a = window.ym.a || []).push(arguments);
    };
    window.ym.l = window.ym.l || Number(new Date());
  }

  function loadMetrika() {
    if (window.__savetoryMetrikaLoaded) return;
    window.__savetoryMetrikaLoaded = true;
    window.dataLayer = window.dataLayer || [];
    createYmStub();

    const tag = document.createElement('script');
    tag.id = 'yandex-metrika-tag';
    tag.async = true;
    tag.src = 'https://mc.yandex.ru/metrika/tag.js';
    const firstScript = document.getElementsByTagName('script')[0];
    if (firstScript && firstScript.parentNode) firstScript.parentNode.insertBefore(tag, firstScript);
    else document.head.appendChild(tag);

    window.ym(counterId, 'init', {
      ssr: true,
      webvisor: webvisorEnabled,
      clickmap: true,
      ecommerce: 'dataLayer',
      accurateTrackBounce: true,
      trackLinks: true,
      defer: true,
      sendTitle: false,
    });
    window.ym(counterId, 'hit', sanitizedPath(window.location.pathname), {
      title: '',
      referer: sanitizedReferrer(),
    });
  }

  window.savetoryReachGoal = function (goal) {
    if (!allowedGoals.has(goal) || storedConsent() !== 'accepted') return false;
    loadMetrika();
    if (typeof window.ym !== 'function') return false;
    window.ym(counterId, 'reachGoal', goal);
    return true;
  };

  function bindConsentBanner() {
    const banner = document.querySelector('[data-cookie-consent]');
    const consent = storedConsent();
    if (consent === 'accepted') {
      if (banner) banner.hidden = true;
      loadMetrika();
      return;
    }
    if (consent === 'declined') {
      window['disableYaCounter' + counterId] = true;
      if (banner) banner.hidden = true;
      return;
    }
    if (!banner) return;
    banner.hidden = false;
    const accept = banner.querySelector('[data-cookie-consent-accept]');
    const decline = banner.querySelector('[data-cookie-consent-decline]');
    if (accept) accept.addEventListener('click', function () {
      saveConsent('accepted');
      banner.hidden = true;
      loadMetrika();
      bindPaymentSuccess();
    });
    if (decline) decline.addEventListener('click', function () {
      saveConsent('declined');
      window['disableYaCounter' + counterId] = true;
      banner.hidden = true;
    });
  }

  function bindPaymentSuccess() {
    const node = document.querySelector('[data-metrika-payment-success]');
    if (!node) return;
    const paymentKey = String(node.dataset.metrikaPaymentSuccess || '').replace(/[^a-zA-Z0-9-]/g, '');
    if (!paymentKey) return;
    const dedupeKey = 'savetory_metrika_payment_success_' + paymentKey;
    try {
      if (window.localStorage.getItem(dedupeKey) === 'sent') return;
    } catch (error) {}
    if (window.savetoryReachGoal('payment_success')) {
      try { window.localStorage.setItem(dedupeKey, 'sent'); } catch (error) {}
    }
  }

  startPrivacyObserver();
  document.addEventListener('DOMContentLoaded', function () {
    protectPrivateContent(document);
    bindConsentBanner();
    bindPaymentSuccess();
  });
})();
