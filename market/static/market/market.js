(function(){
  function formatDuration(ms){
    if (ms <= 0){
      return '00:00:00';
    }
    const totalSeconds = Math.floor(ms / 1000);
    const hours = String(Math.floor(totalSeconds / 3600)).padStart(2, '0');
    const minutes = String(Math.floor((totalSeconds % 3600) / 60)).padStart(2, '0');
    const seconds = String(totalSeconds % 60).padStart(2, '0');
    return `${hours}:${minutes}:${seconds}`;
  }

  function initAuctionTimers(){
    const timerNodes = document.querySelectorAll('[data-auction-timer]');
    if (!timerNodes.length){
      return;
    }
    timerNodes.forEach((node) => {
      const container = node.closest('[data-auction-end]');
      if (!container){
        return;
      }
      const endValue = container.getAttribute('data-auction-end');
      const startValue = container.getAttribute('data-auction-start');
      const endDate = endValue ? new Date(endValue) : null;
      const startDate = startValue ? new Date(startValue) : null;
      if (!endDate || Number.isNaN(endDate.getTime())){
        node.textContent = '—';
        return;
      }

      const wrap = node.closest('[data-auction-timer-wrap]');
      const labelNode = wrap ? wrap.querySelector('[data-auction-timer-label]') : null;
      const mode = node.dataset.auctionTimerMode || 'default';

      function setState(state){
        node.dataset.auctionState = state;
        if (wrap){
          wrap.dataset.auctionState = state;
        }
      }

      function setLabel(text){
        if (labelNode){
          labelNode.textContent = text;
        }
      }

      function update(){
        const now = new Date();
        if (startDate && !Number.isNaN(startDate.getTime()) && now < startDate){
          const remaining = formatDuration(startDate.getTime() - now.getTime());
          setState('upcoming');
          setLabel('До старта');
          if (mode === 'card' || mode === 'detail'){
            node.textContent = remaining;
          } else {
            node.textContent = 'До старта: ' + remaining;
          }
          return;
        }
        if (now >= endDate){
          setState('ended');
          setLabel('Аукцион завершён');
          if (mode === 'card'){
            node.textContent = 'Завершён';
          } else if (mode === 'detail'){
            node.textContent = 'Лот завершён';
          } else {
            node.textContent = 'Аукцион завершён';
          }
          return;
        }
        const remaining = formatDuration(endDate.getTime() - now.getTime());
        setState('active');
        setLabel('до завершения');
        if (mode === 'card' || mode === 'detail'){
          node.textContent = remaining;
        } else {
          node.textContent = 'До окончания: ' + remaining;
        }
      }

      update();
      const interval = setInterval(update, 1000);
      node.addEventListener('DOMNodeRemoved', () => clearInterval(interval), { once: true });
    });
  }

  function initSwapCollapsible(){
    const buttons = document.querySelectorAll('[data-collapsible-toggle]');
    buttons.forEach((btn) => {
      const target = btn.previousElementSibling;
      if (!target){
        return;
      }
      btn.addEventListener('click', () => {
        const expanded = target.classList.toggle('is-expanded');
        if (expanded){
          target.style.maxHeight = '';
          target.style.overflow = 'visible';
          target.classList.add('market-card__swap--expanded');
          btn.textContent = 'Свернуть';
        } else {
          target.style.maxHeight = '3.6em';
          target.style.overflow = 'hidden';
          target.classList.remove('market-card__swap--expanded');
          btn.textContent = 'Показать ещё';
        }
      });
    });
  }

  function initFilterMenu(){
    document.querySelectorAll('[data-filter-menu]').forEach((menu) => {
      const btn = menu.querySelector('.filter-menu__toggle');
      const panel = menu.querySelector('.filter-menu__panel');
      if (!btn || !panel){
        return;
      }
      function onDoc(event){
        if (!menu.contains(event.target)){
          close();
        }
      }
      function onKey(event){
        if (event.key === 'Escape'){
          close();
          btn.focus();
        }
      }
      function open(){
        panel.hidden = false;
        menu.classList.add('is-open');
        btn.setAttribute('aria-expanded', 'true');
        document.addEventListener('mousedown', onDoc, true);
        document.addEventListener('keydown', onKey, true);
      }
      function close(){
        panel.hidden = true;
        menu.classList.remove('is-open');
        btn.setAttribute('aria-expanded', 'false');
        document.removeEventListener('mousedown', onDoc, true);
        document.removeEventListener('keydown', onKey, true);
      }
      btn.addEventListener('click', () => {
        panel.hidden ? open() : close();
      });
    });
  }

  document.addEventListener('DOMContentLoaded', () => {
    initAuctionTimers();
    initSwapCollapsible();
    initFilterMenu();
  });
})();
