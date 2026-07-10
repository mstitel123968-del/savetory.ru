(function(){
  const load = window.__loadUIPrefs || (() => ({}));
  const apply = window.__applyUIPrefs || (() => {});
  const savePrefs = window.__saveUIPrefs || ((prefs) => {
    localStorage.setItem('ui_prefs_v1', JSON.stringify(prefs));
    return prefs;
  });
  const allowedThemes = ['dark','light','custom','retro','sepia','contrast','midnight','aurora','pastel'];
  const allowedAccents = ['blue','black','red','green','custom','violet','emerald','amber','rose','sky','mint','copper'];
  const allowedFontFamilies = ['system','arial','montserrat','roboto','playfair','lato','kudry'];
  const allowedLineHeights = ['normal','relaxed','compact'];
  const allowedDensity = ['cozy','compact','spacious'];
  const allowedSidebar = ['narrow','normal','wide'];
  const allowedCardStyles = ['elevated','flat','outline'];
  const allowedTopbar = ['floating','static','hidden'];
  const allowedBackgrounds = ['gradient','mesh','soft'];
  const allowedBodyWeight = ['regular','medium','strong'];
  const allowedHeadingFont = ['sans','serif','display'];
  const allowedHeadingStyle = ['minimal','soft','caps'];
  const allowedHeadingColor = ['auto','accent','muted'];
  const allowedTextTone = ['balanced','soft','bold'];
  const allowedArchiveView = ['cards','list'];
  const allowedArchiveSort = ['created','title','rubric','manual'];
  const allowedArchiveCardSize = ['small','medium','large'];
  const allowedArchiveEmptyFields = ['dash','hide'];
  const allowedArchiveThumbnails = ['always','hidden'];
  const allowedPrivacy = ['public','friends','private'];
  const booleanPrefs = new Set(['reduceMotion','plainBackground','focusStrong','showHints','expandNews']);
  const canCustomizeColors = window.__settingsCanCustomizeColors === true;

  function csrf(){
    const match = document.cookie.match(/csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : '';
  }

  const defaults = Object.assign({
    theme: 'dark',
    accent: 'blue',
    customThemeColor: '#102a43',
    customAccentColor: '#3b82f6',
    fontScale: 1,
    bgIntensity: 1,
    fontFamily: 'system',
    lineHeight: 'normal',
    density: 'cozy',
    sidebarSize: 'normal',
    cardStyle: 'elevated',
    backgroundStyle: 'gradient',
    bodyWeight: 'regular',
    headingFont: 'sans',
    headingStyle: 'minimal',
    headingColor: 'auto',
    textTone: 'balanced',
    reduceMotion: false,
    plainBackground: false,
    focusStrong: false,
    showHints: true,
    topbarMode: 'floating',
    expandNews: false,
    archiveView: 'cards',
    archiveSort: 'created',
    archiveCardSize: 'medium',
    archiveEmptyFields: 'dash',
    archiveThumbnails: 'always',
    privacy: 'public',
  }, window.__uiPrefsDefaults || {});
  defaults.privacy = 'public';

  const savedPrefs = load();
  let storedPrivacy = null;
  try {
    storedPrivacy = localStorage.getItem('profile_privacy_v1');
  } catch (e) {
    storedPrivacy = null;
  }

  const state = Object.assign({}, defaults, savedPrefs || {});
  if (typeof storedPrivacy === 'string' && allowedPrivacy.includes(storedPrivacy)) {
    state.privacy = storedPrivacy;
  }

  const fontRange = document.getElementById('fontRange');
  const fontLabel = document.getElementById('fontLabel');
  const bgRange = document.getElementById('bgIntensityRange');
  const bgLabel = document.getElementById('bgIntensityLabel');
  const cancelSettingsBtn = document.getElementById('cancelSettingsBtn');
  const settingsSaveBtn = document.getElementById('settingsSaveBtn');
  const customThemeInput = document.getElementById('customThemeColor');
  const customAccentInput = document.getElementById('customAccentColor');
  const themeColorTrigger = document.querySelector('[data-color-trigger="theme"]');
  const accentColorTrigger = document.querySelector('[data-color-trigger="accent"]');
  const themeColorPreview = document.querySelector('[data-theme-color-preview]');
  const accentColorPreview = document.querySelector('[data-accent-color-preview]');
  const prefControls = Array.from(document.querySelectorAll('input[data-pref], select[data-pref]'));
  const privacyControl = document.querySelector('.privacy-control');
  const privacyToggle = document.getElementById('privacyToggle');
  const privacyMenu = document.getElementById('privacyMenu');
  const privacyOptions = privacyMenu ? Array.from(privacyMenu.querySelectorAll('.privacy-option')) : [];
  const privacyMap = {
    public: 'Публичный',
    friends: 'Только друзьям',
    private: 'Закрытый',
  };

  function clampFont(value) {
    const num = Number(value);
    if (!Number.isFinite(num)) {
      return 1;
    }
    return Math.min(1.6, Math.max(0.85, num));
  }

  function clampIntensity(value) {
    const num = Number(value);
    if (!Number.isFinite(num)) {
      return defaults.bgIntensity;
    }
    return Math.min(1, Math.max(0, num));
  }

  function normalizeColor(value, fallback) {
    const text = String(value || '').trim();
    return /^#[0-9a-f]{6}$/i.test(text) ? text.toLowerCase() : fallback;
  }

  const dropdownControls = Array.from(document.querySelectorAll('.pref-dropdown[data-pref]')).map((control) => {
    const key = control.dataset.pref;
    const toggle = control.querySelector('.pref-dropdown__toggle');
    const menu = control.querySelector('.pref-dropdown__menu');
    const options = menu ? Array.from(menu.querySelectorAll('.pref-dropdown__option')) : [];
    options.forEach((opt, index) => {
      if (!opt.id) {
        opt.id = `${key}Option${index}`;
      }
    });
    return { key, control, toggle, menu, options, toast: control.dataset.toast || (toggle ? toggle.dataset.toast : undefined) };
  });
  let activeDropdown = null;

  function sanitizeState() {
    if (!allowedThemes.includes(state.theme)) state.theme = defaults.theme;
    if (!allowedAccents.includes(state.accent)) state.accent = defaults.accent;
    state.customThemeColor = normalizeColor(state.customThemeColor, defaults.customThemeColor);
    state.customAccentColor = normalizeColor(state.customAccentColor, defaults.customAccentColor);
    if (!canCustomizeColors && state.theme === 'custom') state.theme = defaults.theme;
    if (!canCustomizeColors && state.accent === 'custom') state.accent = defaults.accent;
    if (!allowedFontFamilies.includes(state.fontFamily)) state.fontFamily = defaults.fontFamily;
    if (!allowedLineHeights.includes(state.lineHeight)) state.lineHeight = defaults.lineHeight;
    if (!allowedDensity.includes(state.density)) state.density = defaults.density;
    if (!allowedSidebar.includes(state.sidebarSize)) state.sidebarSize = defaults.sidebarSize;
    if (!allowedCardStyles.includes(state.cardStyle)) state.cardStyle = defaults.cardStyle;
    if (!allowedTopbar.includes(state.topbarMode)) state.topbarMode = defaults.topbarMode;
    if (!allowedBackgrounds.includes(state.backgroundStyle)) state.backgroundStyle = defaults.backgroundStyle;
    if (!allowedBodyWeight.includes(state.bodyWeight)) state.bodyWeight = defaults.bodyWeight;
    if (!allowedHeadingFont.includes(state.headingFont)) state.headingFont = defaults.headingFont;
    if (!allowedHeadingStyle.includes(state.headingStyle)) state.headingStyle = defaults.headingStyle;
    if (!allowedHeadingColor.includes(state.headingColor)) state.headingColor = defaults.headingColor;
    if (!allowedTextTone.includes(state.textTone)) state.textTone = defaults.textTone;
    if (!allowedArchiveView.includes(state.archiveView)) state.archiveView = defaults.archiveView;
    if (!allowedArchiveSort.includes(state.archiveSort)) state.archiveSort = defaults.archiveSort;
    if (!allowedArchiveCardSize.includes(state.archiveCardSize)) state.archiveCardSize = defaults.archiveCardSize;
    if (!allowedArchiveEmptyFields.includes(state.archiveEmptyFields)) state.archiveEmptyFields = defaults.archiveEmptyFields;
    if (!allowedArchiveThumbnails.includes(state.archiveThumbnails)) state.archiveThumbnails = defaults.archiveThumbnails;
    if (!allowedPrivacy.includes(state.privacy)) state.privacy = defaults.privacy;
    state.reduceMotion = !!state.reduceMotion;
    state.plainBackground = !!state.plainBackground;
    state.focusStrong = !!state.focusStrong;
    state.showHints = state.showHints !== false;
    state.expandNews = !!state.expandNews;
    state.fontScale = clampFont(state.fontScale);
    state.bgIntensity = clampIntensity(state.bgIntensity);
  }

  sanitizeState();
  const initialState = Object.assign({}, state);

  function ensureToast() {
    let toast = document.getElementById('appToast');
    if (!toast) {
      toast = document.createElement('div');
      toast.id = 'appToast';
      toast.className = 'toast';
      toast.setAttribute('role', 'status');
      toast.setAttribute('aria-live', 'polite');
      document.body.appendChild(toast);
    }
    return toast;
  }

  function showToast(message) {
    const toast = ensureToast();
    toast.textContent = message || 'Сохранено';
    toast.classList.add('show');
    clearTimeout(window.__toastTimer);
    window.__toastTimer = window.setTimeout(() => toast.classList.remove('show'), 2500);
  }

  const UI_PREF_KEYS = Array.isArray(window.__uiPrefKeys) ? window.__uiPrefKeys.slice() : [
    'theme',
    'customThemeColor',
    'fontScale',
    'bgIntensity',
    'accent',
    'customAccentColor',
    'fontFamily',
    'lineHeight',
    'density',
    'sidebarSize',
    'cardStyle',
    'backgroundStyle',
    'bodyWeight',
    'headingFont',
    'headingStyle',
    'headingColor',
    'textTone',
    'reduceMotion',
    'plainBackground',
    'focusStrong',
    'showHints',
    'topbarMode',
    'expandNews',
    'archiveView',
    'archiveSort',
    'archiveCardSize',
    'archiveEmptyFields',
    'archiveThumbnails',
  ];

  function buildUIPrefs() {
    const prefs = {};
    UI_PREF_KEYS.forEach((key) => {
      prefs[key] = state[key];
    });
    return prefs;
  }

  function persistState() {
    try {
      savePrefs(buildUIPrefs());
      localStorage.setItem('profile_privacy_v1', state.privacy);
    } catch (e) {
      /* ignore */
    }
  }

  function save(toastMessage) {
    persistState();
    if (toastMessage === false) return;
    showToast(typeof toastMessage === 'string' ? toastMessage : 'Сохранено');
  }

  async function savePrivacyToServer(){
    try {
      const response = await fetch('/api/profile/', {
        method: 'PATCH',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf() },
        body: JSON.stringify({ privacy_level: state.privacy }),
      });
      const data = await response.json().catch(() => null);
      if (!response.ok || !data || data.success === false){
        throw new Error('privacy save failed');
      }
    } catch (error){
      showToast('Не удалось сохранить конфиденциальность на сервере');
    }
  }

  function render() {
    const percent = Math.round(state.fontScale * 100);
    if (fontRange) {
      fontRange.value = String(percent);
    }
    if (fontLabel) {
      fontLabel.textContent = `${percent}%`;
    }
    const intensityPercent = Math.round(state.bgIntensity * 100);
    if (bgRange) {
      bgRange.value = String(intensityPercent);
    }
    if (bgLabel) {
      bgLabel.textContent = `${intensityPercent}%`;
    }
    if (customThemeInput) customThemeInput.value = state.customThemeColor;
    if (customAccentInput) customAccentInput.value = state.customAccentColor;
    if (themeColorPreview) themeColorPreview.style.setProperty('--custom-theme-preview', state.customThemeColor);
    if (accentColorPreview && state.accent === 'custom') accentColorPreview.style.background = state.customAccentColor;
    if (themeColorTrigger) themeColorTrigger.classList.toggle('is-selected', state.theme === 'custom');
    if (accentColorTrigger) accentColorTrigger.classList.toggle('is-selected', state.accent === 'custom');
    const overlayAlpha = state.bgIntensity >= 0.995 ? 1 : Number(state.bgIntensity.toFixed(2));
    document.documentElement.style.setProperty('--bg-intensity', state.bgIntensity.toFixed(3));
    document.documentElement.style.setProperty('--bg-overlay-alpha', overlayAlpha.toFixed(2));
    prefControls.forEach((ctrl) => {
      const key = ctrl.dataset.pref;
      if (!(key in state)) return;
      if (ctrl.tagName === 'SELECT') {
        ctrl.value = String(state[key]);
        return;
      }
      if (ctrl.type === 'checkbox') {
        ctrl.checked = !!state[key];
        return;
      }
      if (ctrl.type === 'radio') {
        ctrl.checked = String(state[key]) === String(ctrl.value);
        return;
      }
      ctrl.value = state[key];
    });
    if (privacyToggle) {
      const label = privacyMap[state.privacy] || privacyMap.public;
      privacyToggle.dataset.value = state.privacy;
      privacyToggle.textContent = label;
      privacyToggle.setAttribute('aria-expanded', privacyControl && privacyControl.dataset.open === 'true' ? 'true' : 'false');
    }
    privacyOptions.forEach((btn) => {
      const active = btn.dataset.value === state.privacy;
      btn.setAttribute('aria-selected', active ? 'true' : 'false');
    });
    dropdownControls.forEach((dropdown) => {
      const { key, control, toggle, menu, options } = dropdown;
      if (!toggle || !options.length) return;
      const current = state[key];
      const activeOption = options.find((opt) => (opt.dataset.value || '') === String(current)) || options[0];
      if (activeOption) {
        toggle.textContent = activeOption.textContent.trim();
        toggle.dataset.value = activeOption.dataset.value || '';
      }
      options.forEach((opt) => {
        const isActive = opt === activeOption;
        opt.setAttribute('aria-selected', isActive ? 'true' : 'false');
      });
      if (menu) {
        menu.setAttribute('aria-activedescendant', activeOption ? activeOption.id || '' : '');
        if (control.dataset.open === 'true') {
          menu.hidden = false;
        } else {
          menu.hidden = true;
        }
      }
      if (toggle) {
        toggle.setAttribute('aria-expanded', control.dataset.open === 'true' ? 'true' : 'false');
      }
    });
    apply(state);
  }

  function setPref(key, value, toastMessage) {
    let changed = false;
    if (key === 'fontScale') {
      const normalized = clampFont(value);
      if (Math.abs(normalized - state.fontScale) > 0.001) {
        state.fontScale = normalized;
        changed = true;
      }
    } else if (key === 'bgIntensity') {
      const normalized = clampIntensity(value);
      if (Math.abs(normalized - state.bgIntensity) > 0.001) {
        state.bgIntensity = normalized;
        changed = true;
      }
    } else if (booleanPrefs.has(key)) {
      const boolVal = !!value;
      if (state[key] !== boolVal) {
        state[key] = boolVal;
        changed = true;
      }
    } else if (typeof value === 'string') {
      if (state[key] !== value) {
        state[key] = value;
        changed = true;
      }
    } else if (state[key] !== value) {
      state[key] = value;
      changed = true;
    }
    sanitizeState();
    if (!changed) {
      return;
    }
    render();
    save(toastMessage);
  }

  function setPrivacy(value) {
    const next = allowedPrivacy.includes(value) ? value : 'public';
    if (state.privacy === next) {
      return;
    }
    state.privacy = next;
    render();
    save(`Конфиденциальность: ${privacyMap[state.privacy] || privacyMap.public}`);
    savePrivacyToServer();
  }

  function resetAppearance() {
    const confirmed = window.confirm('Сбросить настройки внешнего вида по умолчанию?');
    if (!confirmed) {
      return;
    }
    const privacy = state.privacy;
    UI_PREF_KEYS.forEach((key) => {
      state[key] = defaults[key];
    });
    state.privacy = privacy;
    sanitizeState();
    render();
    savePrefs(buildUIPrefs());
    try {
      localStorage.setItem('profile_privacy_v1', state.privacy);
    } catch (e) {}
    showToast('Внешний вид сброшен');
  }

  function cancelSettings() {
    UI_PREF_KEYS.forEach((key) => {
      state[key] = initialState[key];
    });
    state.privacy = initialState.privacy;
    sanitizeState();
    render();
    savePrefs(buildUIPrefs());
    try {
      localStorage.setItem('profile_privacy_v1', state.privacy);
    } catch (e) {}
    savePrivacyToServer();
    showToast('Изменения отменены');
  }

  if (fontRange) {
    fontRange.addEventListener('input', () => {
      const normalized = clampFont(Number(fontRange.value) / 100);
      document.documentElement.style.setProperty('--fz-scale', String(normalized));
      if (fontLabel) {
        fontLabel.textContent = `${Math.round(normalized * 100)}%`;
      }
    });
    fontRange.addEventListener('change', () => {
      const normalized = clampFont(Number(fontRange.value) / 100);
      setPref('fontScale', normalized, `Размер сохранён: ${Math.round(normalized * 100)}%`);
    });
  }

  if (bgRange) {
    const applyPreview = (normalized) => {
      const overlayAlpha = normalized >= 0.995 ? 1 : Number(normalized.toFixed(2));
      document.documentElement.style.setProperty('--bg-intensity', normalized.toFixed(3));
      document.documentElement.style.setProperty('--bg-overlay-alpha', overlayAlpha.toFixed(2));
      if (bgLabel) {
        bgLabel.textContent = `${Math.round(normalized * 100)}%`;
      }
    };
    let previewTimer = null;
    bgRange.addEventListener('input', () => {
      const normalized = clampIntensity(Number(bgRange.value) / 100);
      if (previewTimer) {
        window.clearTimeout(previewTimer);
      }
      previewTimer = window.setTimeout(() => {
        applyPreview(normalized);
      }, 80);
      if (bgLabel) {
        bgLabel.textContent = `${Math.round(normalized * 100)}%`;
      }
    });
    bgRange.addEventListener('change', () => {
      const normalized = clampIntensity(Number(bgRange.value) / 100);
      if (previewTimer) {
        window.clearTimeout(previewTimer);
        previewTimer = null;
      }
      applyPreview(normalized);
      setPref('bgIntensity', normalized, `Интенсивность фона: ${Math.round(normalized * 100)}%`);
    });
  }

  function openColorPicker(input) {
    if (!canCustomizeColors) {
      showToast('Произвольные цвета доступны только на тарифе PRO');
      return;
    }
    if (input) input.click();
  }

  function setCustomColor(kind, value) {
    if (!canCustomizeColors) return;
    if (kind === 'theme') {
      state.customThemeColor = normalizeColor(value, defaults.customThemeColor);
      state.theme = 'custom';
    } else {
      state.customAccentColor = normalizeColor(value, defaults.customAccentColor);
      state.accent = 'custom';
    }
    sanitizeState();
    render();
    save(kind === 'theme' ? 'Цвет темы применён' : 'Акцентный цвет применён');
  }

  if (themeColorTrigger) themeColorTrigger.addEventListener('click', () => openColorPicker(customThemeInput));
  if (accentColorTrigger) accentColorTrigger.addEventListener('click', () => openColorPicker(customAccentInput));
  if (customThemeInput) customThemeInput.addEventListener('input', () => setCustomColor('theme', customThemeInput.value));
  if (customAccentInput) customAccentInput.addEventListener('input', () => setCustomColor('accent', customAccentInput.value));

  prefControls.forEach((ctrl) => {
    const key = ctrl.dataset.pref;
    const controlToast = ctrl.dataset.toast;
    if (ctrl.tagName === 'SELECT') {
      ctrl.addEventListener('change', () => setPref(key, ctrl.value, controlToast));
      return;
    }
    if (ctrl.type === 'checkbox') {
      ctrl.addEventListener('change', () => setPref(key, ctrl.checked, controlToast));
      return;
    }
    if (ctrl.type === 'radio') {
      ctrl.addEventListener('change', () => {
        if (ctrl.checked) {
          setPref(key, ctrl.value, ctrl.dataset.toast || controlToast);
        }
      });
    }
  });

  function focusDropdownOption(dropdown, option) {
    if (!option) return;
    option.focus({ preventScroll: true });
    if (dropdown && dropdown.menu) {
      dropdown.menu.setAttribute('aria-activedescendant', option.id || '');
    }
  }

  function focusActiveDropdownOption(dropdown) {
    if (!dropdown) return;
    const { options, key } = dropdown;
    if (!options || !options.length) return;
    const current = state[key];
    const active = options.find((opt) => (opt.dataset.value || '') === String(current)) || options[0];
    focusDropdownOption(dropdown, active);
  }

  function openDropdownMenu(dropdown) {
    if (!dropdown || !dropdown.control || !dropdown.toggle || !dropdown.menu) return;
    if (activeDropdown && activeDropdown !== dropdown) {
      closeDropdownMenu(activeDropdown);
    }
    closePrivacyMenu();
    dropdown.control.dataset.open = 'true';
    dropdown.toggle.setAttribute('aria-expanded', 'true');
    dropdown.menu.hidden = false;
    activeDropdown = dropdown;
    focusActiveDropdownOption(dropdown);
  }

  function closeDropdownMenu(dropdown, restoreFocus) {
    if (!dropdown || !dropdown.control) return;
    dropdown.control.dataset.open = 'false';
    if (dropdown.toggle) dropdown.toggle.setAttribute('aria-expanded', 'false');
    if (dropdown.menu) dropdown.menu.hidden = true;
    if (restoreFocus && dropdown.toggle) {
      dropdown.toggle.focus({ preventScroll: true });
    }
    if (activeDropdown === dropdown) {
      activeDropdown = null;
    }
  }

  function closeActiveDropdown() {
    if (activeDropdown) {
      closeDropdownMenu(activeDropdown);
    }
  }

  dropdownControls.forEach((dropdown) => {
    const { control, toggle, menu, options, key, toast } = dropdown;
    if (!control || !toggle || !menu || !options.length) return;
    toggle.addEventListener('click', () => {
      const isOpen = control.dataset.open === 'true';
      if (isOpen) closeDropdownMenu(dropdown);
      else openDropdownMenu(dropdown);
    });
    toggle.addEventListener('keydown', (ev) => {
      if (ev.key === 'ArrowDown' || ev.key === 'Enter' || ev.key === ' ') {
        ev.preventDefault();
        if (control.dataset.open === 'true') {
          focusActiveDropdownOption(dropdown);
        } else {
          openDropdownMenu(dropdown);
        }
      }
      if (ev.key === 'ArrowUp') {
        ev.preventDefault();
        if (control.dataset.open !== 'true') {
          openDropdownMenu(dropdown);
        }
        focusActiveDropdownOption(dropdown);
      }
    });
    options.forEach((option, index) => {
      option.addEventListener('click', () => {
        closeDropdownMenu(dropdown, true);
        const optionToast = option.dataset.toast || toast;
        setPref(key, option.dataset.value || '', optionToast);
      });
      option.addEventListener('keydown', (ev) => {
        if (ev.key === 'Escape') {
          ev.stopPropagation();
          closeDropdownMenu(dropdown, true);
          return;
        }
        if (ev.key === 'Tab') {
          closeDropdownMenu(dropdown);
          return;
        }
        if (ev.key === 'ArrowDown' || ev.key === 'ArrowUp') {
          ev.preventDefault();
          const delta = ev.key === 'ArrowDown' ? 1 : -1;
          const next = options[(index + delta + options.length) % options.length];
          focusDropdownOption(dropdown, next);
        }
        if (ev.key === 'Home') {
          ev.preventDefault();
          focusDropdownOption(dropdown, options[0]);
        }
        if (ev.key === 'End') {
          ev.preventDefault();
          focusDropdownOption(dropdown, options[options.length - 1]);
        }
      });
    });
  });

  function focusActivePrivacy() {
    const active = privacyOptions.find((btn) => btn.dataset.value === state.privacy) || privacyOptions[0];
    if (active) {
      active.focus({ preventScroll: true });
    }
  }

  function openPrivacyMenu() {
    if (!privacyControl) return;
    closeActiveDropdown();
    privacyControl.dataset.open = 'true';
    if (privacyToggle) privacyToggle.setAttribute('aria-expanded', 'true');
    if (privacyMenu) privacyMenu.hidden = false;
    focusActivePrivacy();
  }

  function closePrivacyMenu() {
    if (!privacyControl) return;
    privacyControl.dataset.open = 'false';
    if (privacyToggle) privacyToggle.setAttribute('aria-expanded', 'false');
    if (privacyMenu) privacyMenu.hidden = true;
  }

  if (privacyToggle) {
    privacyToggle.addEventListener('click', () => {
      const isOpen = privacyControl && privacyControl.dataset.open === 'true';
      if (isOpen) closePrivacyMenu();
      else openPrivacyMenu();
    });
    privacyToggle.addEventListener('keydown', (ev) => {
      if (ev.key === 'ArrowDown' || ev.key === 'Enter' || ev.key === ' ') {
        ev.preventDefault();
        openPrivacyMenu();
      }
    });
  }

  privacyOptions.forEach((btn) => {
    btn.addEventListener('click', () => {
      setPrivacy(btn.dataset.value || 'public');
      closePrivacyMenu();
      if (privacyToggle) privacyToggle.focus({ preventScroll: true });
    });
    btn.addEventListener('keydown', (ev) => {
      if (ev.key === 'Escape') {
        ev.stopPropagation();
        closePrivacyMenu();
        if (privacyToggle) privacyToggle.focus({ preventScroll: true });
        return;
      }
      if (ev.key === 'ArrowDown' || ev.key === 'ArrowUp') {
        ev.preventDefault();
        const index = privacyOptions.indexOf(btn);
        const delta = ev.key === 'ArrowDown' ? 1 : -1;
        const next = privacyOptions[(index + delta + privacyOptions.length) % privacyOptions.length];
        if (next) next.focus({ preventScroll: true });
      }
      if (ev.key === 'Tab') {
        closePrivacyMenu();
      }
    });
  });

  if (cancelSettingsBtn) {
    cancelSettingsBtn.addEventListener('click', cancelSettings);
  }
  if (settingsSaveBtn) {
    settingsSaveBtn.addEventListener('click', () => {
      persistState();
      savePrivacyToServer();
      showToast('Настройки сохранены');
    });
  }

  document.addEventListener('click', (ev) => {
    const target = ev.target instanceof Node ? ev.target : null;
    if (privacyControl && privacyMenu && !privacyMenu.hidden) {
      if (!target || !privacyControl.contains(target)) {
        closePrivacyMenu();
      }
    }
    if (activeDropdown && target) {
      const { control } = activeDropdown;
      if (!control || !control.contains(target)) {
        closeDropdownMenu(activeDropdown);
      }
    }
  });

  document.addEventListener('keydown', (ev) => {
    if (ev.key === 'Escape') {
      closePrivacyMenu();
      closeActiveDropdown();
    }
  });

  render();
})();

function __settingsIsAuthed(){
  return Boolean(window.__trezoAuthed);
}
function __settingsToggleProtectedNav(){
  const isAuthed = __settingsIsAuthed();
  const profileLink = document.querySelector('.side-nav a[href="/profile/"]');
  const archiveBtn = document.querySelector('.side-nav button[onclick*="/archive/"]');
  if(profileLink){ profileLink.style.display = isAuthed ? '' : 'none'; }
  if(archiveBtn){ archiveBtn.style.display = isAuthed ? '' : 'none'; }
}
function __settingsRefreshAuthUI(){
  __settingsToggleProtectedNav();
}
document.addEventListener('DOMContentLoaded', __settingsRefreshAuthUI);
document.addEventListener('visibilitychange', ()=>{ if(!document.hidden) __settingsRefreshAuthUI(); });

(async function(){
  try {
    const r = await fetch('/api/auth/status/', { credentials: 'include' });
    const d = await r.json();
    window.__trezoAuthed = Boolean(d && d.authenticated);
  } catch (e){
    window.__trezoAuthed = false;
  }
  __settingsRefreshAuthUI();
})();
