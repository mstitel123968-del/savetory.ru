(function(){
  const dataNode = document.getElementById('publicCollectionData');
  const modalHost = document.getElementById('publicCollectionModalHost');
  if (!dataNode || !modalHost) return;

  let collection = { cards: [] };
  try {
    collection = JSON.parse(dataNode.textContent || '{}');
  } catch (err) {
    collection = { cards: [] };
  }

  const cards = Array.isArray(collection.cards) ? collection.cards : [];
  const cardMap = new Map(cards.map((card) => [String(card.id || ''), card]));

  function renderPatternLinks(target, rawValue, emptyPlaceholder){
    if (!target) return;
    const text = rawValue == null ? '' : String(rawValue);
    const placeholder = emptyPlaceholder == null ? '—' : String(emptyPlaceholder);
    if (!text){
      target.textContent = placeholder;
      return;
    }

    target.textContent = '';
    const pattern = /([^[\]]+?)\[(https?:\/\/[^\s\]]+)\]/g;
    let lastIndex = 0;
    let hasRenderedLink = false;
    let match;

    while ((match = pattern.exec(text)) !== null){
      const label = match[1];
      const href = match[2];
      if (match.index > lastIndex){
        target.appendChild(document.createTextNode(text.slice(lastIndex, match.index)));
      }

      try {
        const parsed = new URL(href);
        if ((parsed.protocol === 'http:' || parsed.protocol === 'https:') && label){
          const link = document.createElement('a');
          link.className = 'inline-pattern-link';
          link.href = href;
          link.target = '_blank';
          link.rel = 'noopener noreferrer';
          link.textContent = label;
          target.appendChild(link);
          hasRenderedLink = true;
        } else {
          target.appendChild(document.createTextNode(match[0]));
        }
      } catch (err) {
        target.appendChild(document.createTextNode(match[0]));
      }
      lastIndex = match.index + match[0].length;
    }

    if (lastIndex < text.length){
      target.appendChild(document.createTextNode(text.slice(lastIndex)));
    }
    if (!hasRenderedLink){
      target.textContent = text;
    }
  }

  function openModal(title){
    const overlay = document.createElement('div');
    overlay.className = 'archive-modal-overlay';

    const modal = document.createElement('div');
    modal.className = 'archive-modal';
    overlay.appendChild(modal);

    const header = document.createElement('div');
    header.className = 'archive-modal__header archive-modal__header--hidden';
    const heading = document.createElement('h2');
    heading.className = 'archive-modal__title sr-only';
    heading.textContent = title || '';
    header.appendChild(heading);
    modal.appendChild(header);

    const body = document.createElement('div');
    body.className = 'archive-modal__body';
    modal.appendChild(body);

    const footer = document.createElement('div');
    footer.className = 'archive-modal__footer file-view__actions archive-modal__footer--pinned archive-modal__footer--single';
    modal.appendChild(footer);

    const closeBtn = document.createElement('button');
    closeBtn.type = 'button';
    closeBtn.className = 'side-btn file-view__action file-view__action--end';
    closeBtn.textContent = 'Закрыть';
    footer.appendChild(closeBtn);

    function close(){
      overlay.remove();
      document.body.classList.remove('archive-modal-open');
      document.removeEventListener('keydown', onKeydown);
    }

    function onKeydown(event){
      if (event.key === 'Escape'){
        close();
      }
    }

    let overlayPointerDown = false;
    overlay.addEventListener('pointerdown', (event) => {
      overlayPointerDown = event.target === overlay;
    });
    overlay.addEventListener('pointerup', (event) => {
      if (overlayPointerDown && event.target === overlay){
        close();
      }
      overlayPointerDown = false;
    });
    closeBtn.addEventListener('click', close);
    document.addEventListener('keydown', onKeydown);

    document.body.classList.add('archive-modal-open');
    modalHost.appendChild(overlay);
    return { body, close };
  }

  function createTitleBadge(title){
    const badge = document.createElement('div');
    badge.className = 'file-view__hero-title';
    const text = document.createElement('span');
    text.className = 'file-view__hero-title-text';
    text.textContent = title || '';
    badge.appendChild(text);
    return badge;
  }

  function applyFrameSize(frame, imageFrame){
    if (!imageFrame || typeof imageFrame !== 'object') return;
    const width = Number(imageFrame.width);
    const height = Number(imageFrame.height);
    if (Number.isFinite(width) && width > 0){
      const value = `${Math.round(width)}px`;
      frame.style.width = value;
      frame.style.maxWidth = '100%';
      frame.style.setProperty('--file-frame-width', value);
    }
    if (Number.isFinite(height) && height > 0){
      const value = `${Math.round(height)}px`;
      frame.style.height = value;
      frame.style.setProperty('--file-frame-height', value);
      frame.dataset.fixedHeight = 'true';
    }
    if (Number.isFinite(width) && width > 0 && Number.isFinite(height) && height > 0){
      const ratio = width / height;
      frame.style.setProperty('--file-frame-aspect', ratio.toFixed(4));
      frame.style.setProperty('--file-frame-ratio', ratio.toFixed(4));
    }
  }

  function renderSingleImage(frame, image, title){
    const img = document.createElement('img');
    img.src = image.src;
    img.alt = title || '';
    img.decoding = 'async';
    img.draggable = false;
    frame.appendChild(img);
  }

  function renderImageCarousel(frame, images, title){
    const strip = document.createElement('div');
    strip.className = 'media-split media-split--hoverable media-split--multi media-split--manual';
    strip.style.setProperty('--media-split-count', String(images.length));
    strip.style.setProperty('--media-split-safe-top', '0px');
    strip.tabIndex = 0;

    let activeIndex = 0;
    const items = images.map((image, index) => {
      const item = document.createElement('div');
      item.className = 'media-split__item';
      item.dataset.index = String(index);
      item.setAttribute('role', 'button');
      item.setAttribute('aria-label', `${title || 'Фото'} ${index + 1}`);
      item.tabIndex = 0;

      const backdrop = document.createElement('div');
      backdrop.className = 'media-split__backdrop';
      backdrop.style.backgroundImage = `url(${image.src})`;
      item.appendChild(backdrop);

      const img = document.createElement('img');
      img.src = image.src;
      img.alt = `${title || 'Фото'} ${index + 1}`;
      img.decoding = 'async';
      img.draggable = false;
      item.appendChild(img);
      strip.appendChild(item);
      return item;
    });

    const prevBtn = document.createElement('button');
    prevBtn.type = 'button';
    prevBtn.className = 'media-split__nav media-split__nav--prev';
    prevBtn.setAttribute('aria-label', 'Предыдущее фото');

    const nextBtn = document.createElement('button');
    nextBtn.type = 'button';
    nextBtn.className = 'media-split__nav media-split__nav--next';
    nextBtn.setAttribute('aria-label', 'Следующее фото');

    function setActive(index){
      activeIndex = Math.min(Math.max(index, 0), items.length - 1);
      items.forEach((item, itemIndex) => {
        item.classList.toggle('media-split__item--active', itemIndex === activeIndex);
      });
      prevBtn.disabled = activeIndex === 0;
      nextBtn.disabled = activeIndex === items.length - 1;
    }

    prevBtn.addEventListener('click', (event) => {
      event.stopPropagation();
      setActive(activeIndex - 1);
    });
    nextBtn.addEventListener('click', (event) => {
      event.stopPropagation();
      setActive(activeIndex + 1);
    });
    strip.addEventListener('keydown', (event) => {
      if (event.key === 'ArrowLeft'){
        event.preventDefault();
        setActive(activeIndex - 1);
      } else if (event.key === 'ArrowRight'){
        event.preventDefault();
        setActive(activeIndex + 1);
      }
    });

    strip.append(prevBtn, nextBtn);
    frame.appendChild(strip);
    setActive(0);
  }

  function renderHero(card, view){
    const images = Array.isArray(card.images) ? card.images.filter((image) => image && image.src) : [];
    const hero = document.createElement('div');
    hero.className = 'file-view__hero';

    if (!images.length){
      hero.classList.add('file-view__hero--empty');
      hero.appendChild(createTitleBadge(card.title));
      const placeholder = document.createElement('div');
      placeholder.className = 'file-view__placeholder';
      placeholder.textContent = 'Фото не добавлено';
      hero.appendChild(placeholder);
      view.appendChild(hero);
      return;
    }

    const primaryImage = images[0];
    const backdrop = document.createElement('div');
    backdrop.className = 'file-view__hero-backdrop';
    backdrop.style.backgroundImage = `url(${primaryImage.src})`;
    hero.appendChild(backdrop);

    const overlay = document.createElement('div');
    overlay.className = 'file-view__hero-overlay';
    hero.appendChild(overlay);

    const content = document.createElement('div');
    content.className = 'file-view__hero-content';
    const inner = document.createElement('div');
    inner.className = 'file-view__hero-inner';
    const frame = document.createElement('div');
    frame.className = 'file-view__frame';
    applyFrameSize(frame, card.imageFrame);

    if (images.length > 1){
      renderImageCarousel(frame, images, card.title);
    } else {
      renderSingleImage(frame, primaryImage, card.title);
    }

    inner.appendChild(frame);
    inner.appendChild(createTitleBadge(card.title));
    content.appendChild(inner);
    hero.appendChild(content);
    view.appendChild(hero);
  }

  function renderDetails(card, view){
    const info = document.createElement('div');
    info.className = 'file-view__info';
    const body = document.createElement('div');
    body.className = 'file-view__body';

    const statusRow = document.createElement('div');
    statusRow.className = 'file-view__detail file-view__status';
    const statusLabel = document.createElement('span');
    statusLabel.className = 'file-view__label';
    statusLabel.textContent = 'Статус';
    const statusBadge = document.createElement('span');
    const status = String(card.status || 'keep');
    statusBadge.className = `status-badge status-badge--${status} file-view__status-badge`;
    statusBadge.textContent = card.statusLabel || 'Храню';
    statusRow.append(statusLabel, statusBadge);
    body.appendChild(statusRow);

    const details = Array.isArray(card.details) ? card.details : [];
    details.forEach((detail) => {
      const row = document.createElement('div');
      row.className = detail.type === 'textarea' ? 'file-view__description' : 'file-view__detail';

      const label = document.createElement('span');
      label.className = 'file-view__label';
      label.textContent = detail.label || 'Поле';

      const value = document.createElement('span');
      value.className = 'file-view__value';
      renderPatternLinks(value, detail.value || '', '—');

      row.append(label, value);
      body.appendChild(row);
    });

    info.appendChild(body);
    view.appendChild(info);
  }

  function openCard(card){
    if (!card) return;
    const modal = openModal(card.title || 'Карточка');
    const view = document.createElement('div');
    view.className = 'file-view';
    renderHero(card, view);
    renderDetails(card, view);
    modal.body.appendChild(view);
    modal.body.scrollTop = 0;
  }

  document.querySelectorAll('[data-public-card-id]').forEach((node) => {
    function open(){
      openCard(cardMap.get(String(node.dataset.publicCardId || '')));
    }
    node.addEventListener('click', open);
    node.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' '){
        event.preventDefault();
        open();
      }
    });
  });

  function openCardFromHash(){
    const match = String(window.location.hash || '').match(/^#card-(.+)$/);
    if (!match) return;
    const cardId = decodeURIComponent(match[1]);
    openCard(cardMap.get(cardId));
  }

  openCardFromHash();
  window.addEventListener('hashchange', openCardFromHash);

  const filterButtons = Array.from(document.querySelectorAll('[data-status-filter]'));
  const cardNodes = Array.from(document.querySelectorAll('[data-public-card-id]'));
  function applyStatusFilter(status){
    const activeStatus = status || 'all';
    filterButtons.forEach((button) => {
      button.classList.toggle('active', button.dataset.statusFilter === activeStatus);
    });
    cardNodes.forEach((node) => {
      const shouldShow = activeStatus === 'all' || node.dataset.status === activeStatus;
      node.hidden = !shouldShow;
    });
  }

  filterButtons.forEach((button) => {
    button.addEventListener('click', () => {
      applyStatusFilter(button.dataset.statusFilter || 'all');
    });
  });
})();
