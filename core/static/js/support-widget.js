(function(){
  if (window.__supportWidgetInitialized) return;
  window.__supportWidgetInitialized = true;

  const widget = document.querySelector('[data-support-widget]');
  if (!widget) return;

  const VISIBLE_MS = 60 * 1000;
  const HIDDEN_MS = 10 * 60 * 1000;
  const CYCLE_MS = HIDDEN_MS + VISIBLE_MS;
  const STORAGE_KEY = 'support_widget_cycle_start_v1';

  let timerId = null;

  function getCycleStart(now){
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      const parsed = raw ? Number(raw) : NaN;
      if (Number.isFinite(parsed) && parsed > 0) {
        return parsed;
      }
    } catch (err) {}
    try {
      localStorage.setItem(STORAGE_KEY, String(now));
    } catch (err) {}
    return now;
  }

  function setVisible(visible){
    widget.classList.toggle('support-floating-widget--visible', Boolean(visible));
  }

  function clearTimer(){
    if (timerId !== null){
      clearTimeout(timerId);
      timerId = null;
    }
  }

  function scheduleNext(){
    clearTimer();
    const now = Date.now();
    const cycleStart = getCycleStart(now);
    const elapsed = ((now - cycleStart) % CYCLE_MS + CYCLE_MS) % CYCLE_MS;
    const visible = elapsed < VISIBLE_MS;
    setVisible(visible);

    const delay = visible ? (VISIBLE_MS - elapsed) : (CYCLE_MS - elapsed);
    timerId = window.setTimeout(scheduleNext, Math.max(250, delay));
  }

  scheduleNext();

  window.addEventListener('pagehide', clearTimer, { once: true });
})();
