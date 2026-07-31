(function(){
  function reachGoal(goal){
    if (typeof window.savetoryReachGoal === 'function'){
      window.savetoryReachGoal(goal);
    }
  }

  const ARCHIVE_STATE_API = '/api/archive/state/';
  const MAX_IMAGE_COUNT = 5;
  const MAX_IMAGE_DIMENSION = 1280;
  const MIN_IMAGE_DIMENSION = 480;
  const IMAGE_SCALE_STEP = 0.88;
  const MAX_INLINE_IMAGE_BYTES = 160 * 1024;
  const JPEG_EXPORT_QUALITY = 0.78;
  const JPEG_MIN_QUALITY = 0.55;
  const JPEG_QUALITY_STEP = 0.07;
  const CANVAS_BACKGROUND_FILL = '#ffffff';
  const MARKET_CATEGORIES = [
    { value: 'collecting', label: 'Коллекционирование' },
    { value: 'auto', label: 'Авто' },
    { value: 'realty', label: 'Недвижимость' },
    { value: 'jobs', label: 'Работа' },
    { value: 'electronics', label: 'Электроника' },
    { value: 'home', label: 'Для дома и дачи' },
    { value: 'fashion', label: 'Одежда, обувь, аксессуары' },
    { value: 'hobby', label: 'Хобби и отдых' },
    { value: 'services', label: 'Услуги' },
  ];

  let textMeasureContext = null;

  function getTextMeasureContext(){
    if (!textMeasureContext){
      const canvas = document.createElement('canvas');
      textMeasureContext = canvas.getContext('2d');
    }
    return textMeasureContext;
  }

  function buildFontShorthand(styles){
    if (!styles) return '16px sans-serif';
    const fontShorthand = styles.font || '';
    if (fontShorthand && fontShorthand !== 'inherit'){ return fontShorthand; }
    const fontStyle = styles.fontStyle || 'normal';
    const fontVariant = styles.fontVariant || 'normal';
    const fontWeight = styles.fontWeight || '400';
    const fontSize = styles.fontSize || '16px';
    const fontFamily = styles.fontFamily || 'sans-serif';
    return `${fontStyle} ${fontVariant} ${fontWeight} ${fontSize} ${fontFamily}`;
  }

  function computeMaxLengthForInput(input){
    if (!input || !input.parentElement){
      return null;
    }
    const styles = window.getComputedStyle(input);
    const paddingLeft = parseFloat(styles.paddingLeft) || 0;
    const paddingRight = parseFloat(styles.paddingRight) || 0;
    const availableWidth = Math.max(0, input.clientWidth - paddingLeft - paddingRight);
    if (availableWidth <= 0){
      return null;
    }
    let charWidth = null;
    const ctx = getTextMeasureContext();
    if (ctx){
      try {
        ctx.font = buildFontShorthand(styles);
        charWidth = ctx.measureText('0').width || ctx.measureText('a').width;
      } catch (err) {
        charWidth = null;
      }
    }
    if (!charWidth || !Number.isFinite(charWidth) || charWidth <= 0){
      const fontSize = parseFloat(styles.fontSize) || 16;
      charWidth = fontSize * 0.6;
    }
    if (!charWidth || !Number.isFinite(charWidth) || charWidth <= 0){
      return null;
    }
    const maxChars = Math.floor(availableWidth / charWidth);
    return maxChars > 0 ? maxChars : 1;
  }

  function setupNonScalableInputLimit(input, cleanupFns){
    if (!input) return;
    let rafId = null;
    let fallbackTimer = null;

    function applyLimit(){
      rafId = null;
      const maxChars = computeMaxLengthForInput(input);
      if (!maxChars || !Number.isFinite(maxChars) || maxChars <= 0){
        return;
      }
      if (input.maxLength !== maxChars){
        input.maxLength = maxChars;
        if (input.value && input.value.length > maxChars){
          input.value = input.value.slice(0, maxChars);
        }
      }
    }

    function schedule(){
      if (rafId){
        cancelAnimationFrame(rafId);
      }
      rafId = requestAnimationFrame(applyLimit);
    }

    const onInput = () => {
      const limit = input.maxLength;
      if (limit > 0 && input.value.length > limit){
        input.value = input.value.slice(0, limit);
      }
    };
    input.addEventListener('input', onInput);

    if (cleanupFns){
      cleanupFns.push(() => {
        input.removeEventListener('input', onInput);
        if (rafId){
          cancelAnimationFrame(rafId);
          rafId = null;
        }
        if (fallbackTimer){
          clearTimeout(fallbackTimer);
          fallbackTimer = null;
        }
      });
    }

    if (typeof ResizeObserver === 'function'){
      const ro = new ResizeObserver(schedule);
      ro.observe(input);
      if (cleanupFns){
        cleanupFns.push(() => ro.disconnect());
      }
    } else {
      const onResize = () => schedule();
      window.addEventListener('resize', onResize);
      if (cleanupFns){
        cleanupFns.push(() => window.removeEventListener('resize', onResize));
      }
    }

    schedule();
    fallbackTimer = setTimeout(schedule, 150);
  }

  function readFileAsDataURL(file){
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = () => reject(reader.error || new Error('read error'));
      reader.readAsDataURL(file);
    });
  }

  function estimateDataUrlBytes(dataUrl){
    if (typeof dataUrl !== 'string') return 0;
    const commaIndex = dataUrl.indexOf(',');
    const base64 = commaIndex >= 0 ? dataUrl.slice(commaIndex + 1) : dataUrl;
    const length = base64.length;
    return Math.floor(length * 0.75);
  }

  function getCsrfToken(){
    // Prefer the token embedded in the page: on prod the csrftoken cookie can be
    // marked Secure / unreadable behind a proxy, which would otherwise send an
    // empty token and trigger a spurious CSRF 403 ("session expired").
    if (typeof window !== 'undefined' && window.__csrfToken){
      return window.__csrfToken;
    }
    if (typeof document === 'undefined' || !document.cookie){
      return '';
    }
    const match = document.cookie.match(/csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : '';
  }

  function isSafeExternalUrl(value){
    if (typeof value !== 'string') return false;
    try {
      const parsed = new URL(value);
      return parsed.protocol === 'http:' || parsed.protocol === 'https:';
    } catch (error){
      return false;
    }
  }

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
      const fullMatch = match[0];
      const label = match[1];
      const href = match[2];

      if (match.index > lastIndex){
        target.appendChild(document.createTextNode(text.slice(lastIndex, match.index)));
      }

      if (label && isSafeExternalUrl(href)){
        const anchor = document.createElement('a');
        anchor.className = 'inline-pattern-link';
        anchor.href = href;
        anchor.target = '_blank';
        anchor.rel = 'noopener noreferrer';
        anchor.textContent = label;
        target.appendChild(anchor);
        hasRenderedLink = true;
      } else {
        target.appendChild(document.createTextNode(fullMatch));
      }

      lastIndex = match.index + fullMatch.length;
    }

    if (lastIndex < text.length){
      target.appendChild(document.createTextNode(text.slice(lastIndex)));
    }

    if (!hasRenderedLink){
      target.textContent = text;
    }
  }

  async function createMarketListingRequest(payload){
    const response = await fetch('/market/api/create/', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCsrfToken(),
      },
      body: JSON.stringify(payload),
      credentials: 'include',
    });
    let data = null;
    try {
      data = await response.json();
    } catch (err) {}
    if (!data || !data.ok){
      const message = data && data.errors ? Object.values(data.errors).join('\n') : 'Не удалось создать объявление.';
      throw new Error(message);
    }
    return data;
  }

  function optimizeImageDataURL(dataUrl, fileType){
    return new Promise((resolve) => {
      if (typeof dataUrl !== 'string'){
        resolve({ dataUrl, width: null, height: null });
        return;
      }
      const img = new Image();
      img.onload = () => {
        const naturalWidth = img.naturalWidth || 0;
        const naturalHeight = img.naturalHeight || 0;
        let targetWidth = naturalWidth;
        let targetHeight = naturalHeight;
        let scale = 1;
        if (naturalWidth > MAX_IMAGE_DIMENSION || naturalHeight > MAX_IMAGE_DIMENSION){
          scale = Math.min(MAX_IMAGE_DIMENSION / naturalWidth, MAX_IMAGE_DIMENSION / naturalHeight);
        }
        const approxBytes = estimateDataUrlBytes(dataUrl);
        const normalizedType = (fileType || '').toLowerCase();
        let shouldRedraw = approxBytes > MAX_INLINE_IMAGE_BYTES || normalizedType === 'image/png';
        if (naturalWidth && naturalHeight && scale < 1){
          shouldRedraw = true;
        }

        if (shouldRedraw && naturalWidth && naturalHeight){
          targetWidth = Math.max(1, Math.round(naturalWidth * scale));
          targetHeight = Math.max(1, Math.round(naturalHeight * scale));

          let workingWidth = targetWidth;
          let workingHeight = targetHeight;
          let quality = JPEG_EXPORT_QUALITY;

          const encode = () => {
            const canvas = document.createElement('canvas');
            canvas.width = Math.max(1, Math.round(workingWidth));
            canvas.height = Math.max(1, Math.round(workingHeight));
            const ctx = canvas.getContext('2d');
            if (ctx){
              if (CANVAS_BACKGROUND_FILL){
                ctx.fillStyle = CANVAS_BACKGROUND_FILL;
                ctx.fillRect(0, 0, canvas.width, canvas.height);
              } else {
                ctx.clearRect(0, 0, canvas.width, canvas.height);
              }
              ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
            }
            return canvas.toDataURL('image/jpeg', quality);
          };

          let encodedUrl = encode();
          let encodedBytes = estimateDataUrlBytes(encodedUrl);

          while (encodedBytes > MAX_INLINE_IMAGE_BYTES){
            let changed = false;
            if (quality > JPEG_MIN_QUALITY + 0.001){
              const nextQuality = Math.max(JPEG_MIN_QUALITY, quality - JPEG_QUALITY_STEP);
              if (nextQuality !== quality){
                quality = nextQuality;
                changed = true;
              }
            }

            if (!changed && (workingWidth > MIN_IMAGE_DIMENSION || workingHeight > MIN_IMAGE_DIMENSION)){
              const nextWidth = Math.max(1, Math.round(workingWidth * IMAGE_SCALE_STEP));
              const nextHeight = Math.max(1, Math.round(workingHeight * IMAGE_SCALE_STEP));
              const clampedWidth = workingWidth > MIN_IMAGE_DIMENSION ? Math.max(nextWidth, MIN_IMAGE_DIMENSION) : nextWidth;
              const clampedHeight = workingHeight > MIN_IMAGE_DIMENSION ? Math.max(nextHeight, MIN_IMAGE_DIMENSION) : nextHeight;
              if (clampedWidth < workingWidth || clampedHeight < workingHeight){
                workingWidth = clampedWidth;
                workingHeight = clampedHeight;
                changed = true;
              }
            }

            if (!changed){
              break;
            }

            encodedUrl = encode();
            encodedBytes = estimateDataUrlBytes(encodedUrl);
          }

          if (approxBytes && approxBytes <= MAX_INLINE_IMAGE_BYTES && encodedBytes > approxBytes){
            resolve({
              dataUrl,
              width: naturalWidth || null,
              height: naturalHeight || null
            });
            return;
          }

          resolve({
            dataUrl: encodedUrl,
            width: Math.round(workingWidth),
            height: Math.round(workingHeight)
          });
          return;
        }

        resolve({
          dataUrl,
          width: naturalWidth || null,
          height: naturalHeight || null
        });
      };
      img.onerror = () => resolve({ dataUrl, width: null, height: null });
      img.src = dataUrl;
    });
  }

  async function fileToImageItem(fileObj){
    try {
      const dataUrl = await readFileAsDataURL(fileObj);
      const optimized = await optimizeImageDataURL(dataUrl, fileObj && fileObj.type);
      return {
        id: createId('photo'),
        src: optimized.dataUrl,
        name: fileObj && fileObj.name ? fileObj.name : '',
        naturalWidth: optimized.width,
        naturalHeight: optimized.height
      };
    } catch (error){
      return null;
    }
  }

  function normalizeImageItem(item){
    if (!item) return null;
    if (typeof item === 'string'){
      return {
        id: createId('photo'),
        src: item,
        name: '',
        naturalWidth: null,
        naturalHeight: null
      };
    }
    const src = item && item.src ? String(item.src) : '';
    if (!src) return null;
    return {
      id: item.id ? String(item.id) : createId('photo'),
      src,
      name: item && item.name ? String(item.name) : '',
      naturalWidth: Number.isFinite(item && item.naturalWidth) && item.naturalWidth > 0 ? Number(item.naturalWidth) : null,
      naturalHeight: Number.isFinite(item && item.naturalHeight) && item.naturalHeight > 0 ? Number(item.naturalHeight) : null
    };
  }

  function normalizeImageValue(value){
    if (!value) return null;
    let itemsSource = [];
    if (Array.isArray(value.items)){
      itemsSource = value.items;
    } else if (Array.isArray(value)){
      itemsSource = value;
    } else if (value.src || value.data){
      itemsSource = [value];
    }

    const items = itemsSource
      .map((item) => normalizeImageItem(item))
      .filter((item) => Boolean(item && item.src));

    if (!items.length){
      return null;
    }

    let pinnedId = null;
    if (value && value.pinnedId !== undefined && value.pinnedId !== null){
      pinnedId = String(value.pinnedId);
    } else if (value && Number.isInteger(value.pinnedIndex)){
      const idx = value.pinnedIndex;
      if (idx >= 0 && idx < items.length){
        pinnedId = items[idx].id;
      }
    }
    if (pinnedId && !items.some((item) => item.id === pinnedId)){
      pinnedId = null;
    }
    if (!pinnedId && items.length){
      pinnedId = items[0].id;
    }

    return {
      items,
      pinnedId: pinnedId || null,
      frameWidth: Number.isFinite(value.frameWidth) && value.frameWidth > 0 ? Math.round(Number(value.frameWidth)) : null,
      frameHeight: Number.isFinite(value.frameHeight) && value.frameHeight > 0 ? Math.round(Number(value.frameHeight)) : null,
      naturalWidth: Number.isFinite(value.naturalWidth) && value.naturalWidth > 0 ? Number(value.naturalWidth) : null,
      naturalHeight: Number.isFinite(value.naturalHeight) && value.naturalHeight > 0 ? Number(value.naturalHeight) : null
    };
  }

  function cloneImageValue(value){
    if (!value) return null;
    return {
      items: Array.isArray(value.items) ? value.items.map((item) => ({ ...item })) : [],
      pinnedId: value.pinnedId ? String(value.pinnedId) : null,
      frameWidth: value.frameWidth ? Number(value.frameWidth) : null,
      frameHeight: value.frameHeight ? Number(value.frameHeight) : null,
      naturalWidth: value.naturalWidth ? Number(value.naturalWidth) : null,
      naturalHeight: value.naturalHeight ? Number(value.naturalHeight) : null
    };
  }

  function computeLargestDimensions(items){
    if (!Array.isArray(items) || !items.length){
      return null;
    }
    let best = null;
    items.forEach((item) => {
      const width = Number(item && item.naturalWidth) || 0;
      const height = Number(item && item.naturalHeight) || 0;
      if (!width || !height){
        return;
      }
      const area = width * height;
      if (!best || area > best.area){
        best = { width, height, area };
      }
    });
    return best ? { width: best.width, height: best.height } : null;
  }

  function computeSplitGeometry(total, index){
    if (!total || total <= 1){
      return null;
    }

    const clampIndex = Math.min(Math.max(index, 0), total - 1);
    const startX = clampIndex / total;
    const endX = (clampIndex + 1) / total;
    const centroidX = (startX + endX) / 2;
    const centroidY = 0.5;
    const clip = `polygon(${(startX * 100).toFixed(4)}% 0%, ${(endX * 100).toFixed(4)}% 0%, ${(endX * 100).toFixed(4)}% 100%, ${(startX * 100).toFixed(4)}% 100%)`;

    return {
      clip,
      centroid: [centroidX, centroidY]
    };
  }

  function getPrimaryImage(value){
    if (!value || !Array.isArray(value.items) || !value.items.length){
      return null;
    }
    if (value.pinnedId){
      const pinned = value.items.find((item) => item && item.id === value.pinnedId);
      if (pinned){
        return pinned;
      }
    }
    return value.items[0];
  }

  function hasImageItems(value){
    return Boolean(value && Array.isArray(value.items) && value.items.length);
  }

  function enableSplitExpansion(container){
    if (!container || container.classList.contains('media-split--interactive')){
      return;
    }
    const items = Array.from(container.querySelectorAll('.media-split__item'));
    if (items.length < 2){
      return;
    }

    const EXPANDED_CLIP = 'polygon(-12% -12%, 112% -12%, 112% 112%, -12% 112%)';
    const TRANSLATE_MULTIPLIER = 34;
    const COLLAPSED_SCALE = 0.86;
    let active = null;
    let leaveTimer = null;
    let pointerInside = false;
    let safeTop = 0;

    function refreshSafeTop(){
      let next = 0;
      if (container.dataset && container.dataset.safeTop){
        const datasetValue = parseFloat(container.dataset.safeTop);
        if (Number.isFinite(datasetValue) && datasetValue > 0){
          next = datasetValue;
        }
      }
      if (!next){
        try {
          const style = getComputedStyle(container);
          const cssValue = parseFloat(style.getPropertyValue('--media-split-safe-top') || '0');
          if (Number.isFinite(cssValue) && cssValue > 0){
            next = cssValue;
          }
        } catch (measureErr) {
          /* ignore measurement issues */
        }
      }
      safeTop = next;
    }

    refreshSafeTop();

    function parseData(target, key, fallback){
      if (!target || !target.dataset) return fallback;
      const value = parseFloat(target.dataset[key]);
      return Number.isFinite(value) ? value : fallback;
    }

    function resolveVector(item, relativeTo){
      const baseX = parseData(relativeTo, 'centroidX', 0.5);
      const baseY = parseData(relativeTo, 'centroidY', 0.5);
      let dx = parseData(item, 'centroidX', 0.5) - baseX;
      let dy = parseData(item, 'centroidY', 0.5) - baseY;
      if (Math.abs(dx) < 1e-3 && Math.abs(dy) < 1e-3){
        dx = parseData(item, 'offsetX', 0);
        dy = parseData(item, 'offsetY', 0);
      }
      if (Math.abs(dx) < 1e-3 && Math.abs(dy) < 1e-3){
        dx = dx || (parseData(item, 'centroidX', 0.5) - 0.5);
        dy = 0;
      }
      if (Math.abs(dx) < 1e-3 && Math.abs(dy) < 1e-3){
        dx = 0.45;
        dy = 0;
      }
      const length = Math.hypot(dx, dy) || 1;
      return { x: dx / length, y: dy / length };
    }

    function applyClip(target, value){
      if (!target) return;
      if (value){
        target.style.clipPath = value;
      } else {
        target.style.removeProperty('clip-path');
      }
    }

    function clearTimer(){
      if (leaveTimer !== null){
        clearTimeout(leaveTimer);
        leaveTimer = null;
      }
    }

    function resetItem(item){
      if (!item) return;
      const original = item.dataset && item.dataset.clipPath ? item.dataset.clipPath : '';
      if (original){
        applyClip(item, original);
      } else {
        applyClip(item, null);
      }
      item.classList.remove('media-split__item--expanded');
      item.style.removeProperty('transform');
      item.style.removeProperty('opacity');
    }

    function collapseItem(item, activeItem){
      if (!item) return;
      item.classList.remove('media-split__item--expanded');
      const original = item.dataset && item.dataset.clipPath ? item.dataset.clipPath : '';
      if (original){
        applyClip(item, original);
      } else {
        applyClip(item, null);
      }

      const vector = resolveVector(item, activeItem);
      const translateX = (vector.x * TRANSLATE_MULTIPLIER).toFixed(4);
      const translateY = (vector.y * TRANSLATE_MULTIPLIER).toFixed(4);
      item.style.transform = `translate3d(${translateX}%, ${translateY}%, 0) scale(${COLLAPSED_SCALE})`;
      item.style.opacity = '0';
    }

    function expandItem(item){
      if (!item) return;
      const original = item.dataset && item.dataset.clipPath ? item.dataset.clipPath : '';
      if (original){
        applyClip(item, original);
      }
      item.classList.add('media-split__item--expanded');
      item.style.opacity = '1';
      item.style.transform = 'translate3d(0, 0, 0) scale(1)';
      requestAnimationFrame(() => {
        if (active === item){
          applyClip(item, EXPANDED_CLIP);
        }
      });
    }

    function setActive(next){
      if (active === next){
        return;
      }
      active = next || null;

      if (!active){
        container.classList.remove('media-split--expanded');
        items.forEach((item) => resetItem(item));
        return;
      }

      container.classList.add('media-split--expanded');
      items.forEach((item) => {
        if (item === active){
          expandItem(item);
        } else {
          collapseItem(item, active);
        }
      });
    }

    function scheduleClear(){
      clearTimer();
      leaveTimer = setTimeout(() => {
        leaveTimer = null;
        setActive(null);
      }, 60);
    }

    function resolveSliceByPointer(event){
      const rect = container.getBoundingClientRect();
      const width = rect.width;
      if (!width){
        return null;
      }
      refreshSafeTop();
      if (safeTop > 0){
        const relY = event.clientY - rect.top;
        if (Number.isFinite(relY) && relY < safeTop){
          return null;
        }
      }
      const relX = (event.clientX - rect.left) / width;
      if (!Number.isFinite(relX)){
        return null;
      }
      const index = Math.floor(relX * items.length);
      const clampedIndex = Math.min(Math.max(index, 0), items.length - 1);
      return items[clampedIndex];
    }

    container.addEventListener('pointerenter', (event) => {
      pointerInside = true;
      clearTimer();
      const slice = resolveSliceByPointer(event);
      if (slice){
        setActive(slice);
      }
    });

    container.addEventListener('pointermove', (event) => {
      if (!pointerInside){
        return;
      }
      const slice = resolveSliceByPointer(event);
      if (slice){
        clearTimer();
        setActive(slice);
      }
    });

    container.addEventListener('pointerleave', () => {
      pointerInside = false;
      scheduleClear();
    });

    container.addEventListener('focusin', (event) => {
      const target = event.target.closest('.media-split__item');
      if (!target || !container.contains(target)){
        return;
      }
      clearTimer();
      setActive(target);
    });

    container.addEventListener('focusout', (event) => {
      const related = event.relatedTarget;
      if (related && container.contains(related)){
        return;
      }
      setActive(null);
    });

    items.forEach((item) => {
      item.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' || event.key === ' '){
          event.preventDefault();
          setActive(item);
        }
      });
    });

    container.classList.add('media-split--interactive');
  }

  const currentLogin = 'server-session';

  async function ensureAuthenticated(){
    try {
      const { response, data } = await requestArchiveState('/api/auth/status/');
      if (response.ok && data && data.authenticated){
        return true;
      }
    } catch (e) {}
    try {
      window.location.assign('/');
    } catch (err) {
      location.href = '/';
    }
    return false;
  }
  const REMOVED_FIELD_IDS = new Set();
  const ALL_RUBRICS_ID = '__all__';
  const NON_REMOVABLE_FIELD_IDS = new Set(['photo', 'name', 'title']);

  function isNonRemovableFieldId(id){
    if (typeof id !== 'string') return false;
    return NON_REMOVABLE_FIELD_IDS.has(id.trim());
  }

  const DEFAULT_FIELDS = [
    {
      id: 'photo',
      label: 'Фото',
      type: 'image',
      description: 'Добавление изображения для файла',
      modes: ['file']
    },
    {
      id: 'title',
      label: 'Наименование',
      type: 'text',
      description: 'Название или основное обозначение файла'
    },
    {
      id: 'location',
      label: 'Расположение',
      type: 'text',
      description: 'Где находится объект или файл',
      modes: ['file']
    },
    {
      id: 'material',
      label: 'Материал',
      type: 'text',
      description: 'Из какого материала выполнен объект',
      modes: ['file']
    },
    {
      id: 'price',
      label: 'Стоимость',
      type: 'text',
      description: 'Текущая стоимость или оценка',
      modes: ['file']
    },
    {
      id: 'description',
      label: 'Описание',
      type: 'textarea',
      description: 'Подробности, история или примечания'
    }
  ];

  const FILE_STATUS_OPTIONS = [
    { value: 'keep', label: 'Храню' },
    { value: 'sell', label: 'Готов продать' },
    { value: 'exchange', label: 'Готов обменять' },
    { value: 'search', label: 'Ищу такой же' },
    { value: 'sold', label: 'Продано' }
  ];
  const FILE_STATUS_LABELS = FILE_STATUS_OPTIONS.reduce((acc, item) => {
    acc[item.value] = item.label;
    return acc;
  }, {});

  function normalizeFileStatus(value){
    const status = String(value || '').trim().toLowerCase();
    return Object.prototype.hasOwnProperty.call(FILE_STATUS_LABELS, status) ? status : 'keep';
  }

  function getFileStatusLabel(status){
    return FILE_STATUS_LABELS[normalizeFileStatus(status)] || FILE_STATUS_LABELS.keep;
  }

  function createStatusBadge(status, extraClass){
    const normalized = normalizeFileStatus(status);
    const badge = document.createElement('span');
    badge.className = `status-badge status-badge--${normalized}`;
    if (extraClass){
      badge.classList.add(extraClass);
    }
    badge.textContent = getFileStatusLabel(normalized);
    return badge;
  }

  function createExportMenu(rubric, extraClass){
    const details = document.createElement('details');
    details.className = 'export-menu';
    if (extraClass){
      details.classList.add(extraClass);
    }

    const summary = document.createElement('summary');
    summary.className = 'side-btn export-menu__summary';
    summary.textContent = 'Экспорт';
    details.appendChild(summary);

    const menu = document.createElement('div');
    menu.className = 'export-menu__list';

    [
      { format: 'xlsx', label: 'Excel' },
      { format: 'pdf', label: 'PDF' }
    ].forEach((item) => {
      const link = document.createElement('a');
      link.className = 'export-menu__item';
      link.href = `/api/archive/rubrics/${encodeURIComponent(rubric.id)}/export/${item.format}/`;
      link.textContent = item.label;
      link.addEventListener('click', () => {
        details.open = false;
      });
      menu.appendChild(link);
    });

    details.appendChild(menu);
    details.addEventListener('toggle', () => {
      if (!details.open) return;
      document.querySelectorAll('.export-menu[open]').forEach((node) => {
        if (node !== details){
          node.open = false;
        }
      });
    });
    return details;
  }

  function createStatusDropdown(currentValue, cleanupFns){
    let value = normalizeFileStatus(currentValue);
    const wrapper = document.createElement('div');
    wrapper.className = 'file-status-select';

    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'file-status-select__button';
    button.setAttribute('aria-haspopup', 'listbox');
    button.setAttribute('aria-expanded', 'false');

    const buttonText = document.createElement('span');
    buttonText.className = 'file-status-select__text';
    const chevron = document.createElement('span');
    chevron.className = 'file-status-select__chevron';
    chevron.setAttribute('aria-hidden', 'true');
    button.append(buttonText, chevron);

    const list = document.createElement('div');
    list.className = 'file-status-select__list';
    list.setAttribute('role', 'listbox');
    list.hidden = true;

    function setValue(nextValue){
      value = normalizeFileStatus(nextValue);
      buttonText.textContent = getFileStatusLabel(value);
      Array.from(list.children).forEach((option) => {
        const selected = option.dataset.value === value;
        option.classList.toggle('file-status-select__option--selected', selected);
        option.setAttribute('aria-selected', selected ? 'true' : 'false');
      });
    }

    function openList(){
      list.hidden = false;
      button.setAttribute('aria-expanded', 'true');
    }

    function closeList(){
      list.hidden = true;
      button.setAttribute('aria-expanded', 'false');
    }

    function toggleList(){
      if (list.hidden){
        openList();
      } else {
        closeList();
      }
    }

    FILE_STATUS_OPTIONS.forEach((item) => {
      const option = document.createElement('button');
      option.type = 'button';
      option.className = 'file-status-select__option';
      option.dataset.value = item.value;
      option.setAttribute('role', 'option');
      option.textContent = item.label;
      option.addEventListener('click', () => {
        setValue(item.value);
        closeList();
        button.focus();
      });
      list.appendChild(option);
    });

    button.addEventListener('click', toggleList);
    wrapper.addEventListener('keydown', (event) => {
      if (event.key === 'Escape'){
        closeList();
        button.focus();
      } else if (event.key === 'ArrowDown' || event.key === 'ArrowUp'){
        event.preventDefault();
        openList();
        const options = Array.from(list.querySelectorAll('.file-status-select__option'));
        const currentIndex = Math.max(0, options.findIndex((option) => option.dataset.value === value));
        const nextIndex = event.key === 'ArrowDown'
          ? Math.min(currentIndex + 1, options.length - 1)
          : Math.max(currentIndex - 1, 0);
        if (options[nextIndex]){
          setValue(options[nextIndex].dataset.value);
          options[nextIndex].focus();
        }
      } else if (event.key === 'Enter' || event.key === ' '){
        if (document.activeElement === button){
          event.preventDefault();
          toggleList();
        }
      }
    });

    const handleOutsideClick = (event) => {
      if (!wrapper.contains(event.target)){
        closeList();
      }
    };
    document.addEventListener('click', handleOutsideClick);
    if (cleanupFns){
      cleanupFns.push(() => document.removeEventListener('click', handleOutsideClick));
    }

    wrapper.append(button, list);
    setValue(value);
    return {
      element: wrapper,
      getValue(){
        return value;
      }
    };
  }

  function normalizeFieldDefinition(rawField, fallbackPrefix){
    if (!rawField || typeof rawField !== 'object'){
      return null;
    }
    const fallback = fallbackPrefix || 'field';
    const id = rawField.id ? String(rawField.id) : createId(fallback);
    if (!id || REMOVED_FIELD_IDS.has(id)){
      return null;
    }
    return {
      id,
      label: rawField.label ? String(rawField.label) : 'Поле',
      type: rawField.type ? String(rawField.type) : 'text',
      description: rawField.description ? String(rawField.description) : '',
      custom: Boolean(rawField.custom)
    };
  }

  function normalizeRemovedFieldIds(rawIds){
    const normalized = [];
    const seen = new Set();
    if (!Array.isArray(rawIds)){
      return normalized;
    }
    rawIds.forEach((item) => {
      if (typeof item !== 'string'){
        return;
      }
      const id = item.trim();
      if (!id || isNonRemovableFieldId(id) || REMOVED_FIELD_IDS.has(id) || seen.has(id)){
        return;
      }
      seen.add(id);
      normalized.push(id);
    });
    return normalized;
  }

  const createBtn = document.getElementById('createRubric');
  const createWrap = document.getElementById('rubricCreateWrap');
  const nameInput = document.getElementById('rubricNameInput');
  const nameSaveBtn = document.getElementById('rubricNameSave');
  const nameError = document.getElementById('rubricNameError');
  const emptySection = document.getElementById('archiveEmpty');
  const rubricsContainer = document.getElementById('rubricsContainer');
  const rubricButtons = document.getElementById('rubricButtons');
  const allRubricsBtn = document.getElementById('rubricAllButton');
  const modalHost = document.getElementById('archiveModalHost');
  const archiveStatusMessage = document.getElementById('archiveStatusMessage');
  const archiveSelectionToggle = document.getElementById('archiveSelectionToggle');
  const archiveBulkBar = document.getElementById('archiveBulkBar');
  const archiveBulkSummary = document.getElementById('archiveBulkSummary');
  const archiveBulkSelectAll = document.getElementById('archiveBulkSelectAll');
  const archiveBulkClear = document.getElementById('archiveBulkClear');
  const archiveBulkMove = document.getElementById('archiveBulkMove');
  const archiveBulkDelete = document.getElementById('archiveBulkDelete');
  const archiveBulkClose = document.getElementById('archiveBulkClose');
  const archiveAddFile = document.getElementById('archiveAddFile');
  const rubricCreateShortcut = document.getElementById('rubricCreateShortcut');
  const rubricScroll = document.querySelector('[data-rubric-scroll]');
  const allRubricCount = document.querySelector('[data-all-rubric-count]');
  const archiveViewButtons = Array.from(document.querySelectorAll('[data-archive-view]'));
  const archiveSortSelect = document.getElementById('archiveSortSelect');
  const topbarActions = document.querySelector('.archive-toolbar__secondary');
  const sidebarArchiveUsed = document.querySelector('[data-sidebar-archive-used]');
  const sidebarArchiveProgress = document.querySelector('[data-sidebar-archive-progress]');
  const sidebarArchiveProgressBar = document.querySelector('[data-sidebar-archive-progress-bar]');
  const OPEN_FILE_SESSION_KEY = 'trezo:open-file';

  if (!createBtn || !createWrap || !nameInput || !nameSaveBtn || !emptySection || !rubricsContainer || !modalHost || !rubricButtons) {
    return;
  }

  const sideNav = createBtn.closest('.side-nav');
  const sideNavScroll = sideNav ? sideNav.querySelector('.side-nav-scroll') : null;
  const sideNavDivider = sideNav ? sideNav.querySelector('.side-nav-divider') : null;

  if (allRubricsBtn){
    allRubricsBtn.addEventListener('click', () => {
      if (!state.rubrics.length){
        return;
      }
      if (activeRubricId === ALL_RUBRICS_ID) return;
      activeRubricId = ALL_RUBRICS_ID;
      renderRubrics();
    });
  }

  let sidebarMeasureFrame = null;
  function updateSidebarScrollMaxHeight(){
    if (!sideNav || !sideNavScroll || !sideNavDivider) return;
    const navStyles = getComputedStyle(sideNav);
    const gapValue = parseFloat(navStyles.rowGap || navStyles.gap || '0') || 0;
    const visibleChildren = Array.from(sideNav.children).filter((child) => {
      if (child === sideNavScroll) return true;
      return getComputedStyle(child).display !== 'none';
    });
    const totalGaps = Math.max(visibleChildren.length - 1, 0) * gapValue;
    let otherHeight = 0;
    visibleChildren.forEach((child) => {
      if (child === sideNavScroll) return;
      otherHeight += child.offsetHeight;
    });
    const available = sideNav.clientHeight - otherHeight - totalGaps;
    const clamped = Math.max(0, Math.floor(available));
    sideNavScroll.style.maxHeight = clamped > 0 ? `${clamped}px` : 'auto';
  }

  function scheduleSidebarMeasure(){
    if (!sideNav || !sideNavScroll) return;
    if (sidebarMeasureFrame){
      cancelAnimationFrame(sidebarMeasureFrame);
    }
    sidebarMeasureFrame = requestAnimationFrame(() => {
      sidebarMeasureFrame = null;
      updateSidebarScrollMaxHeight();
    });
  }

  const logo = document.querySelector('.logo');
  if (logo) {
    logo.style.cursor = 'pointer';
    logo.addEventListener('click', () => { window.location.href = '/'; });
  }

  let lastSavedJson = null;
  const storageAdapter = createStorageAdapter(`archive:${currentLogin}`);

  let state = { rubrics: [] };
  let activeRubricId = null;
  let suppressSearchRefresh = false;
  let stateReady = false;
  let hasStateMutation = false;
  let pendingOpenFileDetail = null;
  let indexedLoadComplete = false;
  let abandonIndexedRestore = false;
  let selectionMode = false;
  let selectedFileKeys = new Set();

  function requestSearchRefresh(){
    if (window.TrezoSearch && typeof window.TrezoSearch.refresh === 'function'){
      window.TrezoSearch.refresh();
    }
  }

  function requestSearchHide(){
    if (window.TrezoSearch && typeof window.TrezoSearch.hide === 'function'){
      window.TrezoSearch.hide();
    }
  }

  function setArchiveStatus(message){
    if (!archiveStatusMessage){
      return;
    }
    const text = message ? String(message).trim() : '';
    archiveStatusMessage.textContent = text;
    archiveStatusMessage.classList.toggle('hidden', !text);
  }

  function renderTopbarExport(rubric){
    if (!topbarActions){
      return;
    }
    const existing = topbarActions.querySelector('.export-menu--topbar');
    if (existing){
      existing.remove();
    }
    if (!rubric){
      return;
    }
    const anchor = topbarActions.querySelector('.archive-view-switch');
    topbarActions.insertBefore(createExportMenu(rubric, 'export-menu--topbar'), anchor || topbarActions.firstChild);
  }

  function renderTopbarMeta(text){
    const el = document.querySelector('[data-archive-meta]');
    if (!el){
      return;
    }
    el.textContent = text || '';
    el.classList.toggle('hidden', !text);
  }

  function flattenErrors(errors){
    if (!errors || typeof errors !== 'object'){
      return '';
    }
    return Object.values(errors)
      .flatMap((value) => Array.isArray(value) ? value : [value])
      .map((value) => String(value || '').trim())
      .filter(Boolean)
      .join('\n');
  }

  async function readJsonResponse(response){
    const contentType = response.headers.get('content-type') || '';
    if (!contentType.includes('application/json')){
      return null;
    }
    try {
      return await response.json();
    } catch (err) {
      return null;
    }
  }

  async function requestArchiveState(url, options){
    const response = await fetch(url, {
      credentials: 'include',
      cache: 'no-store',
      ...(options || {}),
    });
    const data = await readJsonResponse(response);
    return { response, data };
  }

  // Verify the real auth state before blaming the session for a failed request.
  // Returns true on any error so a transient network hiccup never shows a
  // spurious "session expired" prompt.
  async function isStillAuthenticated(){
    try {
      const resp = await fetch('/api/auth/status/', { credentials: 'include', cache: 'no-store' });
      if (!resp.ok){
        return true;
      }
      const data = await resp.json();
      return Boolean(data && data.authenticated);
    } catch (err) {
      return true;
    }
  }

  async function moveArchiveFileRequest(fileId, sourceRubricId, targetRubricId){
    const { response, data } = await requestArchiveState('/api/archive/files/move/', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCsrfToken(),
      },
      body: JSON.stringify({
        file_id: fileId,
        source_rubric_id: sourceRubricId,
        target_rubric_id: targetRubricId,
      }),
    });
    if (response.ok && data && data.success && data.state && typeof data.state === 'object'){
      return data;
    }
    throw new Error(
      flattenErrors(data && data.errors)
      || (response.status === 401 || response.status === 403 || (response.redirected && !data)
        ? 'Сессия истекла. Войдите снова.'
        : `Не удалось перенести файл (HTTP ${response.status}).`)
    );
  }

  async function bulkDeleteArchiveFilesRequest(items){
    const { response, data } = await requestArchiveState('/api/archive/files/bulk-delete/', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCsrfToken(),
      },
      body: JSON.stringify({ items }),
    });
    if (response.ok && data && data.success && data.state && typeof data.state === 'object'){
      return data;
    }
    throw new Error(
      flattenErrors(data && data.errors)
      || (response.status === 401 || response.status === 403 || (response.redirected && !data)
        ? 'Сессия истекла. Войдите снова.'
        : `Не удалось удалить файлы (HTTP ${response.status}).`)
    );
  }

  async function bulkMoveArchiveFilesRequest(items, targetRubricId){
    const { response, data } = await requestArchiveState('/api/archive/files/bulk-move/', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCsrfToken(),
      },
      body: JSON.stringify({
        items,
        target_rubric_id: targetRubricId,
      }),
    });
    if (response.ok && data && data.success && data.state && typeof data.state === 'object'){
      return data;
    }
    throw new Error(
      flattenErrors(data && data.errors)
      || (response.status === 401 || response.status === 403 || (response.redirected && !data)
        ? 'Сессия истекла. Войдите снова.'
        : `Не удалось перенести файлы (HTTP ${response.status}).`)
    );
  }

  function syncSearchState(snapshot, options){
    if (!window.TrezoSearch) return;
    if (!currentLogin) return;
    const safeSnapshot = snapshot && typeof snapshot === 'object' ? snapshot : { rubrics: [] };
    const opts = options || {};
    if (opts.reset && typeof window.TrezoSearch.resetCache === 'function'){
      try {
        window.TrezoSearch.resetCache();
      } catch (err) {}
    }
    if (typeof window.TrezoSearch.setActiveState === 'function'){
      try {
        window.TrezoSearch.setActiveState(currentLogin, safeSnapshot);
      } catch (err) {}
    } else if (!opts.reset && typeof window.TrezoSearch.refresh === 'function'){
      window.TrezoSearch.refresh();
    }
  }

  async function loadServerSnapshot(){
    try {
      const { response, data } = await requestArchiveState(ARCHIVE_STATE_API);
      if (response.ok && data && data.success){
        return {
          snapshot: normalizeState(data.state || { rubrics: [] }),
          error: '',
        };
      }
      if (response.status === 401 || response.status === 403 || (response.redirected && !data)){
        return { snapshot: null, error: 'Сессия истекла. Войдите снова.' };
      }
      return {
        snapshot: null,
        error: flattenErrors(data && data.errors) || `Не удалось загрузить архив (HTTP ${response.status}).`,
      };
    } catch (err) {
      console.warn('Не удалось получить архив с сервера', err);
      return { snapshot: null, error: 'Не удалось загрузить архив с сервера. Проверьте соединение и попробуйте еще раз.' };
    }
  }

  function normalizeState(data){
    const rubrics = Array.isArray(data && data.rubrics) ? data.rubrics : [];
    return {
      rubrics: rubrics.map((rubric) => {
        const mode = rubric && rubric.mode === 'text' ? 'text' : 'file';
        const removedFieldIds = normalizeRemovedFieldIds(rubric && rubric.removedFieldIds);
        const removedSet = new Set(removedFieldIds);

        let fields = Array.isArray(rubric && rubric.fields)
          ? rubric.fields.map((field) => normalizeFieldDefinition(field, 'field')).filter(Boolean)
          : [];
        fields = fields.filter((field) => !removedSet.has(field.id));
        if (mode === 'text'){
          fields = fields.filter((field) => field.id !== 'photo' && field.type !== 'image');
        }

        let fieldOptions = Array.isArray(rubric && rubric.fieldOptions)
          ? rubric.fieldOptions.map((field) => normalizeFieldDefinition(field, 'field')).filter(Boolean)
          : [];
        if (!fieldOptions.length && fields.length){
          fieldOptions = fields.map((field) => ({
            id: field.id,
            label: field.label,
            type: field.type,
            description: field.description,
            custom: Boolean(field.custom)
          }));
        }

        fieldOptions = fieldOptions.filter((field) => !removedSet.has(field.id));
        if (mode === 'text'){
          fieldOptions = fieldOptions.filter((field) => field.id !== 'photo' && field.type !== 'image');
        }

        const optionIds = new Set(fieldOptions.map((field) => field.id));
        fields.forEach((field) => {
          if (optionIds.has(field.id)){
            return;
          }
          optionIds.add(field.id);
          fieldOptions.push({
            id: field.id,
            label: field.label,
            type: field.type,
            description: field.description,
            custom: Boolean(field.custom)
          });
        });
        fields.forEach((field) => removedSet.delete(field.id));

        const files = Array.isArray(rubric && rubric.files) ? rubric.files.map((file) => {
          const values = file && typeof file.values === 'object' && file.values ? { ...file.values } : {};
          REMOVED_FIELD_IDS.forEach((fieldId) => {
            if (values && Object.prototype.hasOwnProperty.call(values, fieldId)){
              delete values[fieldId];
            }
          });
          removedSet.forEach((fieldId) => {
            if (values && Object.prototype.hasOwnProperty.call(values, fieldId)){
              delete values[fieldId];
            }
          });
          if (mode === 'text' && values && values.photo){
            delete values.photo;
          }
          fields.forEach((field) => {
            if (!values || !Object.prototype.hasOwnProperty.call(values, field.id)){
              return;
            }
            if (field.type === 'image'){
              const normalized = normalizeImageValue(values[field.id]);
              if (normalized){
                values[field.id] = normalized;
              } else {
                delete values[field.id];
              }
            } else if (typeof values[field.id] !== 'string'){
              const raw = values[field.id];
              values[field.id] = typeof raw === 'number' || typeof raw === 'boolean'
                ? String(raw)
                : (raw ? String(raw) : '');
            }
          });
          return {
            id: file && file.id ? String(file.id) : createId('file'),
            status: normalizeFileStatus(file && file.status),
            createdAt: file && file.createdAt ? Number(file.createdAt) : Date.now(),
            updatedAt: file && file.updatedAt ? Number(file.updatedAt) : null,
            values
          };
        }) : [];

        return {
          id: rubric && rubric.id ? String(rubric.id) : createId('rubric'),
          name: rubric && rubric.name ? String(rubric.name) : 'Новая рубрика',
          mode,
          publicEnabled: Boolean(rubric && rubric.publicEnabled),
          publicSlug: rubric && rubric.publicSlug ? String(rubric.publicSlug) : generatePublicSlug(rubric && rubric.name),
          fields,
          fieldOptions,
          removedFieldIds: Array.from(removedSet),
          files
        };
      })
    };
  }
  function applyNormalizedState(snapshot){
    const next = snapshot && Array.isArray(snapshot.rubrics) ? snapshot : { rubrics: [] };
    state = next;
    if (activeRubricId && activeRubricId !== ALL_RUBRICS_ID && !state.rubrics.some((item) => item.id === activeRubricId)){
      activeRubricId = state.rubrics.length ? ALL_RUBRICS_ID : null;
    }
    if (!activeRubricId && state.rubrics.length){
      activeRubricId = ALL_RUBRICS_ID;
    }
  }

  function getFileSelectionKey(rubricId, fileId){
    return `${String(rubricId)}::${String(fileId)}`;
  }

  function parseFileSelectionKey(key){
    const raw = String(key || '');
    const separatorIndex = raw.indexOf('::');
    if (separatorIndex < 0){
      return null;
    }
    return {
      rubricId: raw.slice(0, separatorIndex),
      fileId: raw.slice(separatorIndex + 2),
    };
  }

  function getVisibleRubrics(){
    if (activeRubricId === ALL_RUBRICS_ID){
      return state.rubrics;
    }
    return state.rubrics.filter((item) => item.id === activeRubricId);
  }

  function getArchivePrefs(){
    const defaults = {
      archiveView: 'cards',
      archiveSort: 'created',
      archiveCardSize: 'medium',
      archiveEmptyFields: 'dash',
      archiveThumbnails: 'always',
    };
    let prefs = {};
    try {
      prefs = typeof window.__loadUIPrefs === 'function' ? window.__loadUIPrefs() : {};
    } catch (error){
      prefs = {};
    }
    const result = Object.assign({}, defaults, prefs || {});
    if (!['cards', 'list'].includes(result.archiveView)) result.archiveView = defaults.archiveView;
    if (!['created', 'title', 'rubric', 'manual'].includes(result.archiveSort)) result.archiveSort = defaults.archiveSort;
    if (!['small', 'medium', 'large'].includes(result.archiveCardSize)) result.archiveCardSize = defaults.archiveCardSize;
    if (!['dash', 'hide'].includes(result.archiveEmptyFields)) result.archiveEmptyFields = defaults.archiveEmptyFields;
    if (!['always', 'hidden'].includes(result.archiveThumbnails)) result.archiveThumbnails = defaults.archiveThumbnails;
    return result;
  }

  function syncArchivePreferenceControls(prefs){
    const current = prefs || getArchivePrefs();
    archiveViewButtons.forEach((button) => {
      const isActive = button.dataset.archiveView === current.archiveView;
      button.classList.toggle('active', isActive);
      button.setAttribute('aria-pressed', isActive ? 'true' : 'false');
    });
    if (archiveSortSelect && archiveSortSelect.value !== current.archiveSort){
      archiveSortSelect.value = current.archiveSort;
    }
  }

  function saveArchivePreference(key, value){
    let prefs = {};
    try {
      prefs = typeof window.__loadUIPrefs === 'function' ? window.__loadUIPrefs() : {};
    } catch (error){
      prefs = {};
    }
    const next = Object.assign({}, prefs, { [key]: value });
    if (typeof window.__saveUIPrefs === 'function'){
      window.__saveUIPrefs(next);
    }
    if (typeof window.__applyUIPrefs === 'function'){
      window.__applyUIPrefs(next);
    }
    renderRubrics();
  }

  function compareText(a, b){
    return String(a || '').localeCompare(String(b || ''), 'ru', { sensitivity: 'base', numeric: true });
  }

  function getSortedRubrics(rubrics, prefs){
    const items = Array.isArray(rubrics) ? rubrics.slice() : [];
    if (!prefs || prefs.archiveSort === 'manual' || prefs.archiveSort === 'created'){
      return items;
    }
    return items.sort((a, b) => compareText(a && a.name, b && b.name));
  }

  function getSortedFiles(rubric, prefs){
    const files = rubric && Array.isArray(rubric.files) ? rubric.files.slice() : [];
    const sortMode = prefs && prefs.archiveSort ? prefs.archiveSort : 'created';
    if (sortMode === 'manual'){
      return files;
    }
    if (sortMode === 'title' || sortMode === 'rubric'){
      return files.sort((a, b) => compareText(getDisplayName(rubric, a), getDisplayName(rubric, b)));
    }
    return files.sort((a, b) => {
      const left = Number(a && a.createdAt) || 0;
      const right = Number(b && b.createdAt) || 0;
      return right - left;
    });
  }

  function getVisibleFileRefs(){
    const refs = [];
    getVisibleRubrics().forEach((rubric) => {
      const files = Array.isArray(rubric && rubric.files) ? rubric.files : [];
      files.forEach((file) => {
        if (!file || !file.id){
          return;
        }
        refs.push({
          rubricId: String(rubric.id),
          fileId: String(file.id),
        });
      });
    });
    return refs;
  }

  function reconcileSelectedFiles(){
    const validKeys = new Set();
    state.rubrics.forEach((rubric) => {
      const files = Array.isArray(rubric && rubric.files) ? rubric.files : [];
      files.forEach((file) => {
        if (file && file.id){
          validKeys.add(getFileSelectionKey(rubric.id, file.id));
        }
      });
    });
    selectedFileKeys = new Set(Array.from(selectedFileKeys).filter((key) => validKeys.has(key)));
  }

  function clearSelectedFiles(){
    selectedFileKeys.clear();
  }

  function setSelectionMode(enabled){
    selectionMode = Boolean(enabled);
    if (!selectionMode){
      clearSelectedFiles();
    }
    updateBulkSelectionUi();
    renderRubrics();
  }

  function toggleFileSelection(rubricId, fileId){
    const key = getFileSelectionKey(rubricId, fileId);
    if (selectedFileKeys.has(key)){
      selectedFileKeys.delete(key);
    } else {
      selectedFileKeys.add(key);
    }
    updateBulkSelectionUi();
    renderRubrics();
  }

  function getSelectedFileRefs(){
    const refs = [];
    selectedFileKeys.forEach((key) => {
      const parsed = parseFileSelectionKey(key);
      if (parsed){
        refs.push(parsed);
      }
    });
    return refs;
  }

  function getSelectedFileCount(){
    return selectedFileKeys.size;
  }

  function updateBulkSelectionUi(){
    const count = getSelectedFileCount();
    const visibleCount = getVisibleFileRefs().length;
    if (archiveSelectionToggle){
      const label = archiveSelectionToggle.querySelector('span');
      if (label){
        label.textContent = selectionMode ? 'Отмена' : 'Выбрать';
      } else {
        archiveSelectionToggle.textContent = selectionMode ? 'Отмена' : 'Выбрать';
      }
      archiveSelectionToggle.classList.toggle('active', selectionMode);
    }
    if (archiveBulkBar){
      archiveBulkBar.classList.toggle('hidden', !selectionMode);
    }
    if (archiveBulkSummary){
      archiveBulkSummary.textContent = `Выбрано: ${count}`;
    }
    if (archiveBulkSelectAll){
      archiveBulkSelectAll.disabled = visibleCount === 0;
    }
    if (archiveBulkClear){
      archiveBulkClear.disabled = count === 0;
    }
    if (archiveBulkMove){
      archiveBulkMove.disabled = count === 0;
    }
    if (archiveBulkDelete){
      archiveBulkDelete.disabled = count === 0;
    }
  }

  function createStorageAdapter(storageKey){
    const DB_NAME = 'trezo-archive-db';
    const STORE_NAME = 'states';
    let dbPromise = null;

    function openDb(){
      if (!('indexedDB' in window)){
        return Promise.resolve(null);
      }
      if (dbPromise){
        return dbPromise;
      }
      dbPromise = new Promise((resolve) => {
        let resolved = false;
        function finish(result){
          if (!resolved){
            resolved = true;
            resolve(result || null);
          }
        }
        try {
          const request = indexedDB.open(DB_NAME, 1);
          request.onupgradeneeded = (event) => {
            const db = event.target.result;
            if (!db.objectStoreNames.contains(STORE_NAME)){
              db.createObjectStore(STORE_NAME);
            }
          };
          request.onsuccess = () => finish(request.result);
          request.onerror = () => finish(null);
          request.onblocked = () => finish(request.result || null);
        } catch (err) {
          console.warn('IndexedDB недоступна для архива', err);
          finish(null);
        }
      });
      return dbPromise;
    }

    async function load(){
      const db = await openDb();
      if (!db){
        return null;
      }
      return new Promise((resolve) => {
        let finished = false;
        function done(result){
          if (!finished){
            finished = true;
            resolve(result || null);
          }
        }
        try {
          const tx = db.transaction(STORE_NAME, 'readonly');
          const store = tx.objectStore(STORE_NAME);
          const request = store.get(storageKey);
          request.onsuccess = () => done(request.result || null);
          request.onerror = () => done(null);
          tx.onabort = () => done(null);
        } catch (err) {
          console.warn('Не удалось прочитать архив из IndexedDB', err);
          done(null);
        }
      });
    }

    async function store(value){
      const db = await openDb();
      if (!db){
        return false;
      }
      return new Promise((resolve) => {
        let finished = false;
        function done(result){
          if (!finished){
            finished = true;
            resolve(Boolean(result));
          }
        }
        try {
          const tx = db.transaction(STORE_NAME, 'readwrite');
          tx.oncomplete = () => done(true);
          tx.onabort = () => done(false);
          tx.onerror = () => done(false);
          tx.objectStore(STORE_NAME).put(value, storageKey);
        } catch (err) {
          console.warn('Не удалось сохранить архив в IndexedDB', err);
          done(false);
        }
      });
    }

    return {
      load,
      store
    };
  }

  function setUiInteractivity(enabled){
    if (!createBtn) return;
    createBtn.disabled = !enabled;
    createBtn.classList.toggle('side-btn--disabled', !enabled);
    if (!enabled){
      toggleCreateForm(false);
    }
  }

  async function saveState(){
    const snapshot = normalizeState(state);
    applyNormalizedState(snapshot);
    const serializedSnapshot = JSON.stringify(snapshot);
    if (serializedSnapshot !== lastSavedJson){
      const stored = await storageAdapter.store(snapshot);
      if (stored){
        lastSavedJson = serializedSnapshot;
      }
    }

    let success = false;
    try {
      const { response, data } = await requestArchiveState(ARCHIVE_STATE_API, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': getCsrfToken(),
        },
        body: JSON.stringify({ state: snapshot }),
      });
      success = Boolean(response.ok && data && data.success);
      if (!success){
        const serverError = flattenErrors(data && data.errors);
        if (serverError){
          // Real, actionable server message (e.g. terms acceptance, limits).
          setArchiveStatus(`Сохранение не выполнено: ${serverError}`);
        } else if (response.status === 401 || response.status === 403 || (response.redirected && !data)){
          // 401/403/redirect can also come from a CSRF hiccup while the user is
          // still logged in — don't cry "session expired" unless they really are.
          const authed = await isStillAuthenticated();
          setArchiveStatus(authed
            ? 'Изменения сохранены в браузере, но не синхронизированы с сервером. Повторите попытку позже.'
            : 'Сохранение не выполнено: сессия истекла. Войдите снова.');
        } else {
          setArchiveStatus(`Сохранение не выполнено (HTTP ${response.status}).`);
        }
      } else {
        setArchiveStatus('');
      }
    } catch (e) {
      console.warn('Не удалось сохранить архив на сервере', e);
      setArchiveStatus('Не удалось сохранить изменения на сервере. Локальная версия сохранена в браузере.');
    }

    if (success){
      hasStateMutation = false;
    }
    syncSearchState(snapshot, { reset: true });
    return success;
  }

  async function initializeState(){
    indexedLoadComplete = true;
    abandonIndexedRestore = true;
    setArchiveStatus('');

    const authed = await ensureAuthenticated();
    if (!authed){
      return;
    }

    const cachedSnapshot = await storageAdapter.load();
    if (cachedSnapshot && typeof cachedSnapshot === 'object'){
      const normalizedCachedSnapshot = normalizeState(cachedSnapshot);
      lastSavedJson = JSON.stringify(normalizedCachedSnapshot);
      applyNormalizedState(normalizedCachedSnapshot);
      syncSearchState(normalizedCachedSnapshot);
    }

    const { snapshot: serverSnapshot, error: loadError } = await loadServerSnapshot();
    if (serverSnapshot){
      lastSavedJson = JSON.stringify(serverSnapshot);
      applyNormalizedState(serverSnapshot);
      syncSearchState(serverSnapshot);
      await storageAdapter.store(serverSnapshot);
      setArchiveStatus('');
    } else if (cachedSnapshot && typeof cachedSnapshot === 'object'){
      setArchiveStatus(loadError || 'Не удалось получить свежие данные. Показана последняя сохраненная версия архива.');
    } else {
      state = { rubrics: [] };
      activeRubricId = null;
      syncSearchState(state);
      if (loadError){
        setArchiveStatus(loadError);
      }
    }

    stateReady = true;
    setUiInteractivity(true);
    renderRubrics();
    scheduleSidebarMeasure();
    requestSearchRefresh();

    if (pendingOpenFileDetail){
      const payload = pendingOpenFileDetail;
      pendingOpenFileDetail = null;
      openFileFromSearch(payload.rubricId, payload.fileId);
    }
    consumePendingOpenFile();
  }

  function createId(prefix){
    return `${prefix}-${Math.random().toString(16).slice(2,8)}-${Date.now().toString(36)}`;
  }

  function generatePublicSlug(value){
    const source = String(value || '').trim().toLowerCase();
    if (!source) return 'collection';
    const normalized = source
      .normalize('NFKD')
      .replace(/[^\p{Letter}\p{Number}_-]+/gu, '-')
      .replace(/[-_]{2,}/g, '-')
      .replace(/^[-_]+|[-_]+$/g, '');
    return normalized || 'collection';
  }

  function ensureUniquePublicSlug(slug, rubricId){
    const base = generatePublicSlug(slug);
    const used = new Set(
      state.rubrics
        .filter((item) => item && item.id !== rubricId)
        .map((item) => generatePublicSlug(item.publicSlug || item.name))
    );
    let candidate = base;
    let index = 2;
    while (used.has(candidate)){
      candidate = `${base}-${index}`;
      index += 1;
    }
    return candidate;
  }

  function getPublicCollectionUrl(rubric){
    if (!rubric) return '';
    const slug = ensureUniquePublicSlug(rubric.publicSlug || rubric.name, rubric.id);
    const owner = encodeURIComponent((window.TrezoUser && window.TrezoUser.username) || 'server-session');
    return `${window.location.origin}/u/${owner}/${encodeURIComponent(slug)}/`;
  }

  async function copyTextToClipboard(text){
    if (navigator.clipboard && window.isSecureContext){
      await navigator.clipboard.writeText(text);
      return true;
    }
    const input = document.createElement('textarea');
    input.value = text;
    input.setAttribute('readonly', '');
    input.style.position = 'fixed';
    input.style.left = '-9999px';
    document.body.appendChild(input);
    input.select();
    const copied = document.execCommand('copy');
    input.remove();
    return copied;
  }

  function getRubric(id){
    return state.rubrics.find((item) => item.id === id) || null;
  }

  function persistAndRender(){
    if (!stateReady){
      return Promise.resolve(false);
    }
    hasStateMutation = true;
    if (!indexedLoadComplete){
      abandonIndexedRestore = true;
    }
    const savePromise = saveState().catch((err) => {
      console.warn('Сохранение архива завершилось с ошибкой', err);
      return false;
    });
    renderRubrics();
    return savePromise;
  }

  function toggleCreateForm(forceShow){
    const shouldShow = typeof forceShow === 'boolean' ? forceShow : createWrap.classList.contains('hidden');
    if (shouldShow){
      createWrap.classList.remove('hidden');
      createWrap.setAttribute('aria-hidden', 'false');
      nameInput.focus();
    } else {
      createWrap.classList.add('hidden');
      createWrap.setAttribute('aria-hidden', 'true');
      nameError.textContent = '';
      nameInput.value = '';
    }
    scheduleSidebarMeasure();
  }

  async function handleCreateRubric(){
    if (!stateReady){
      nameError.textContent = 'Архив еще загружается. Подождите несколько секунд и попробуйте снова.';
      return;
    }
    const name = nameInput.value.trim();
    if (!name){
      nameError.textContent = 'Введите название рубрики';
      nameInput.focus();
      return;
    }

    const normalizedName = name.toLocaleLowerCase ? name.toLocaleLowerCase() : name.toLowerCase();
    const duplicate = state.rubrics.some((item) => {
      if (!item || !item.name){
        return false;
      }
      const candidate = item.name.trim();
      if (!candidate){
        return false;
      }
      const candidateNormalized = candidate.toLocaleLowerCase ? candidate.toLocaleLowerCase() : candidate.toLowerCase();
      return candidateNormalized === normalizedName;
    });

    if (duplicate){
      nameError.textContent = 'рубрика с таким наименованием уже существует';
      nameInput.focus();
      return;
    }

    const rubric = {
      id: createId('rubric'),
      name,
      mode: 'file',
      publicEnabled: false,
      publicSlug: ensureUniquePublicSlug(name, null),
      fields: [],
      fieldOptions: [],
      removedFieldIds: [],
      files: []
    };

    state.rubrics.push(rubric);
    activeRubricId = ALL_RUBRICS_ID;
    nameSaveBtn.disabled = true;
    const saved = await persistAndRender();
    nameSaveBtn.disabled = false;
    if (!saved){
      nameError.textContent = 'Не удалось сохранить рубрику. Проверьте соединение, авторизацию и попробуйте снова.';
      return;
    }
    toggleCreateForm(false);
    nameError.textContent = '';
    setArchiveStatus('');
    reachGoal('rubric_created');
    openFieldSelectionModal(rubric.id);
  }

  function renderRubrics(){
    const hasRubrics = state.rubrics.length > 0;
    const archivePrefs = getArchivePrefs();
    const totalFileCount = state.rubrics.reduce((total, rubric) => {
      return total + (Array.isArray(rubric && rubric.files) ? rubric.files.length : 0);
    }, 0);
    reconcileSelectedFiles();
    updateBulkSelectionUi();
    syncArchivePreferenceControls(archivePrefs);

    if (archiveAddFile){
      archiveAddFile.disabled = !stateReady || !hasRubrics;
    }
    if (allRubricCount){
      allRubricCount.textContent = formatArchiveCount(totalFileCount);
    }
    const displayedArchiveUsage = totalFileCount;
    if (sidebarArchiveUsed){
      sidebarArchiveUsed.textContent = String(displayedArchiveUsage);
    }
    if (sidebarArchiveProgress){
      const archiveLimit = Number(sidebarArchiveProgress.dataset.archiveLimit);
      const usagePercent = Number.isFinite(archiveLimit) && archiveLimit > 0
        ? Math.min(100, Math.round((displayedArchiveUsage / archiveLimit) * 100))
        : 0;
      sidebarArchiveProgress.setAttribute('aria-valuenow', String(usagePercent));
      if (sidebarArchiveProgressBar){
        sidebarArchiveProgressBar.style.setProperty('--tariff-progress', `${usagePercent}%`);
      }
    }

    if (allRubricsBtn){
      allRubricsBtn.classList.toggle('hidden', !hasRubrics);
      if (!hasRubrics){
        allRubricsBtn.classList.remove('active');
      }
    }

    if (!hasRubrics){
      emptySection.classList.remove('hidden');
      rubricsContainer.classList.add('hidden');
      rubricsContainer.classList.remove('rubrics--viewing-all');
      rubricsContainer.innerHTML = '';
      rubricButtons.innerHTML = '';
      rubricButtons.classList.add('hidden');
      activeRubricId = null;
      renderTopbarExport(null);
      renderTopbarMeta(null);
      requestSearchHide();
      scheduleSidebarMeasure();
      return;
    }

    let viewingAll = activeRubricId === ALL_RUBRICS_ID;
    if (!viewingAll && (!activeRubricId || !state.rubrics.some((item) => item.id === activeRubricId))){
      activeRubricId = state.rubrics.length ? ALL_RUBRICS_ID : null;
    }
    viewingAll = activeRubricId === ALL_RUBRICS_ID;
    rubricsContainer.classList.toggle('rubrics--viewing-all', viewingAll);

    if (allRubricsBtn){
      allRubricsBtn.classList.toggle('active', viewingAll);
    }
    const activeRubric = viewingAll ? null : state.rubrics.find((item) => item.id === activeRubricId);
    renderTopbarExport(activeRubric);
    renderTopbarMeta(activeRubric ? formatArchiveCount(activeRubric.files.length) : formatArchiveCount(totalFileCount));

    emptySection.classList.add('hidden');
    rubricsContainer.classList.remove('hidden');
    rubricsContainer.innerHTML = '';
    rubricButtons.innerHTML = '';
    rubricButtons.classList.remove('hidden');

    state.rubrics.forEach((rubric) => {
      const navItem = document.createElement('div');
      navItem.className = 'rubric-nav-item';

      const navBtn = document.createElement('button');
      navBtn.type = 'button';
      navBtn.className = 'rubric-filter-card rubric-nav-item__button';
      navBtn.innerHTML = '<svg class="rubric-filter-card__icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M3 6h6l2 2h10v11H3z" /></svg>';
      const navContent = document.createElement('span');
      navContent.className = 'rubric-filter-card__content';
      const navTitle = document.createElement('strong');
      navTitle.textContent = rubric.name;
      const navCount = document.createElement('small');
      navCount.textContent = formatArchiveCount(rubric.files.length);
      navContent.append(navTitle, navCount);
      navBtn.appendChild(navContent);
      if (rubric.id === activeRubricId){
        navBtn.classList.add('active');
        navItem.classList.add('rubric-nav-item--active');
      }
      navBtn.addEventListener('click', () => {
        if (activeRubricId === rubric.id) return;
        activeRubricId = rubric.id;
        renderRubrics();
      });

      const editBtn = document.createElement('button');
      editBtn.type = 'button';
      editBtn.className = 'rubric-nav-item__edit';
      editBtn.setAttribute('aria-label', `Редактировать рубрику «${rubric.name}»`);
      editBtn.title = 'Настроить рубрику';
      editBtn.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><circle cx="12" cy="5" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="12" cy="19" r="1"/></svg>';
      editBtn.addEventListener('click', (event) => {
        event.stopPropagation();
        event.preventDefault();
        openFieldSelectionModal(rubric.id);
      });

      navItem.append(navBtn, editBtn);
      rubricButtons.appendChild(navItem);
    });

    const fragment = document.createDocumentFragment();
    const targetRubrics = getSortedRubrics(
      viewingAll ? state.rubrics : state.rubrics.filter((item) => item.id === activeRubricId),
      archivePrefs
    );
    targetRubrics.forEach((rubric) => {
      const card = document.createElement('section');
      card.className = 'rubric-card rubric-card--all';
      card.dataset.rubricId = rubric.id;

      const metaText = formatArchiveCount(rubric.files.length);

      if (viewingAll){
        const header = document.createElement('div');
        header.className = 'rubric-card__heading';
        const heading = document.createElement('h3');
        heading.className = 'rubric-card__title';
        heading.textContent = rubric.name;
        const meta = document.createElement('span');
        meta.className = 'rubric-card__meta';
        meta.textContent = metaText;
        header.append(heading, meta, createExportMenu(rubric, 'export-menu--rubric'));
        card.appendChild(header);
      }

      const frame = document.createElement('div');
      frame.className = 'rubric-card__frame';

      const body = document.createElement('div');
      body.className = 'rubric-card__body';
      if (selectionMode && !rubric.fields.length){
        const hint = document.createElement('div');
        hint.className = 'rubric-empty-hint';
        hint.textContent = 'Настройте поля рубрики, чтобы начать добавлять файлы.';
        body.appendChild(hint);
      } else {
        const grid = document.createElement('div');
        grid.className = 'rubric-files-grid';
        getSortedFiles(rubric, archivePrefs).forEach((file) => {
          grid.appendChild(createFileCard(rubric, file));
        });
        if (!selectionMode){
          grid.appendChild(createAddTile(() => openFileFormForRubric(rubric)));
        }
        body.appendChild(grid);
      }
      frame.appendChild(body);

      card.appendChild(frame);
      fragment.appendChild(card);
    });

    rubricsContainer.appendChild(fragment);
    scheduleSidebarMeasure();
    if (!suppressSearchRefresh){
      requestSearchRefresh();
    }
  }

  function formatArchiveCount(count){
    const value = Math.max(0, Number(count) || 0);
    const mod10 = value % 10;
    const mod100 = value % 100;
    let noun = 'карточек';
    if (mod10 === 1 && mod100 !== 11){
      noun = 'карточка';
    } else if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)){
      noun = 'карточки';
    }
    return `${value} ${noun}`;
  }

  document.addEventListener('click', (event) => {
    document.querySelectorAll('.export-menu[open]').forEach((node) => {
      if (!node.contains(event.target)){
        node.open = false;
      }
    });
    document.querySelectorAll('.file-card-menu[open]').forEach((node) => {
      if (!node.contains(event.target)){
        node.open = false;
      }
    });

    if (!createWrap.classList.contains('hidden')){
      if (
        !createWrap.contains(event.target)
        && !createBtn.contains(event.target)
        && (!rubricCreateShortcut || !rubricCreateShortcut.contains(event.target))
      ){
        toggleCreateForm(false);
      }
    }

  });

  function createAddTile(handler){
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'file-add-tile';
    btn.innerHTML = '<span aria-hidden="true">+</span><span class="sr-only">Добавить файл</span>';
    btn.addEventListener('click', handler);
    return btn;
  }

  function openFileFormForRubric(rubric){
    if (!rubric){
      return;
    }
    if (!rubric.fields.length){
      openFieldSelectionModal(rubric.id);
      return;
    }
    openFileFormModal(rubric.id);
  }

  function openAddFileFlow(){
    if (!stateReady){
      setArchiveStatus('Архив еще загружается. Подождите несколько секунд и попробуйте снова.');
      return;
    }
    if (!state.rubrics.length){
      toggleCreateForm(true);
      return;
    }
    const activeRubric = activeRubricId && activeRubricId !== ALL_RUBRICS_ID
      ? getRubric(activeRubricId)
      : null;
    if (activeRubric){
      openFileFormForRubric(activeRubric);
      return;
    }

    const modal = openModal({ title: 'Выберите рубрику' });
    const list = document.createElement('div');
    list.className = 'archive-rubric-picker';
    state.rubrics.forEach((rubric) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'archive-rubric-picker__item';
      button.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M3 6h6l2 2h10v11H3z" /></svg>';
      const text = document.createElement('span');
      const title = document.createElement('strong');
      title.textContent = rubric.name;
      const count = document.createElement('small');
      count.textContent = formatArchiveCount(rubric.files.length);
      text.append(title, count);
      button.appendChild(text);
      button.addEventListener('click', () => {
        modal.close();
        openFileFormForRubric(rubric);
      });
      list.appendChild(button);
    });
    modal.body.replaceChildren(list);
    modal.footer.replaceChildren();
    const cancel = createActionButton('Отмена');
    cancel.addEventListener('click', () => modal.close());
    modal.footer.appendChild(cancel);
  }

  function getFieldValue(rubric, file, field){
    if (!file || !file.values) return field.type === 'image' ? null : '';
    const value = file.values[field.id];
    if (field.type === 'image'){
      if (value && value.items){
        return cloneImageValue(value);
      }
      const normalized = normalizeImageValue(value);
      return normalized ? cloneImageValue(normalized) : null;
    }
    if (typeof value === 'string'){
      return value;
    }
    if (typeof value === 'number' || typeof value === 'boolean'){
      return String(value);
    }
    return '';
  }

  function getFileTitle(rubric, file){
    if (!rubric || !file) return '';
    const titleField = rubric.fields.find((field) => field.id === 'title');
    if (!titleField) return '';
    const title = getFieldValue(rubric, file, titleField);
    return typeof title === 'string' ? title : '';
  }

  function getDisplayName(rubric, file){
    if (!file) return rubric.name;
    const title = getFileTitle(rubric, file);
    if (title) return title;
    return rubric.name || '';
  }

  function formatArchiveDate(timestamp){
    const value = Number(timestamp);
    if (!Number.isFinite(value) || value <= 0){
      return '';
    }
    try {
      return new Intl.DateTimeFormat('ru-RU', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
      }).format(new Date(value));
    } catch (error){
      return '';
    }
  }

  function createFileMenuAction(label, handler, options){
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'file-card-menu__item';
    if (options && options.danger){
      button.classList.add('file-card-menu__item--danger');
    }
    button.textContent = label;
    button.addEventListener('click', (event) => {
      event.preventDefault();
      event.stopPropagation();
      const details = button.closest('.file-card-menu');
      if (details){
        details.open = false;
      }
      handler();
    });
    return button;
  }

  function createFileCard(rubric, file){
    const archivePrefs = getArchivePrefs();
    const fileSelectionKey = getFileSelectionKey(rubric.id, file.id);
    const isSelected = selectedFileKeys.has(fileSelectionKey);
    const card = document.createElement('article');
    card.className = 'file-card';
    card.dataset.fileId = file.id;
    card.dataset.rubricId = rubric.id;

    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'file-card__open';
    btn.setAttribute('aria-label', `Открыть карточку «${getDisplayName(rubric, file)}»`);
    if (selectionMode){
      card.classList.add('file-card--selectable');
      btn.setAttribute('aria-pressed', isSelected ? 'true' : 'false');
    }
    if (isSelected){
      card.classList.add('file-card--selected');
    }

    const allowMedia = rubric.mode !== 'text' && archivePrefs.archiveThumbnails !== 'hidden';
    const photoField = allowMedia ? rubric.fields.find((field) => field.id === 'photo' && field.type === 'image') : null;
    if (photoField){
      const photoValue = getFieldValue(rubric, file, photoField);
      const thumb = document.createElement('div');
      thumb.className = 'file-card__thumb';
      if (photoValue && hasImageItems(photoValue)){
        const primary = getPrimaryImage(photoValue);
        if (primary){
          const image = document.createElement('img');
          image.src = primary.src;
          image.alt = '';
          image.loading = 'lazy';
          image.decoding = 'async';
          thumb.appendChild(image);
        }
      } else {
        thumb.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="2"/><path d="m21 15-5-5L5 20"/></svg>';
      }
      btn.appendChild(thumb);
    } else {
      card.classList.add('file-card--text-only');
      const placeholder = document.createElement('div');
      placeholder.className = 'file-card__thumb file-card__thumb--text';
      placeholder.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M6 2h9l5 5v15H6z"/><path d="M14 2v6h6M9 13h8M9 17h6"/></svg>';
      btn.appendChild(placeholder);
    }

    const title = document.createElement('div');
    title.className = 'file-card__title';
    title.textContent = getDisplayName(rubric, file);
    btn.appendChild(title);

    if (selectionMode){
      const selector = document.createElement('span');
      selector.className = 'file-card__selector';
      selector.setAttribute('aria-hidden', 'true');
      selector.textContent = isSelected ? '✓' : '';
      card.appendChild(selector);
    }

    btn.addEventListener('click', () => {
      if (selectionMode){
        toggleFileSelection(rubric.id, file.id);
        return;
      }
      openFileViewModal(rubric.id, file.id);
    });
    card.appendChild(btn);

    if (!selectionMode){
      const menu = document.createElement('details');
      menu.className = 'file-card-menu';
      const summary = document.createElement('summary');
      summary.className = 'file-card-menu__toggle';
      summary.setAttribute('aria-label', `Действия с карточкой «${getDisplayName(rubric, file)}»`);
      summary.title = 'Действия';
      summary.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><circle cx="12" cy="5" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="12" cy="19" r="1"/></svg>';
      const menuList = document.createElement('div');
      menuList.className = 'file-card-menu__list';
      menuList.append(
        createFileMenuAction('Открыть', () => openFileViewModal(rubric.id, file.id)),
        createFileMenuAction('Редактировать', () => openFileViewModal(rubric.id, file.id, { edit: true })),
        createFileMenuAction('В Маркет', () => openAuctionForCard(rubric, file)),
        createFileMenuAction('Скачать PDF', () => downloadFilePdf(rubric, file)),
        createFileMenuAction('Удалить', () => {
          openConfirmModal('Вы точно хотите удалить данный файл?', () => {
            rubric.files = rubric.files.filter((item) => item.id !== file.id);
            persistAndRender();
          });
        }, { danger: true })
      );
      menu.append(summary, menuList);
      card.appendChild(menu);
    }

    return card;
  }


  function openFieldSelectionModal(rubricId){
    if (!stateReady){
      return;
    }
    const rubric = getRubric(rubricId);
    if (!rubric) return;

    const optionMap = new Map();
    const optionOrder = [];
    const isTextRubric = rubric.mode === 'text';
    const rubricMode = rubric.mode;
    const removedFieldIds = new Set(normalizeRemovedFieldIds(rubric.removedFieldIds));

    function isFieldAllowedForRubric(field){
      if (!field) return false;
      if (field.modes && !field.modes.includes(rubricMode)){
        return false;
      }
      if (isTextRubric && (field.id === 'photo' || field.type === 'image')){
        return false;
      }
      return true;
    }

    function pushOption(field){
      const clone = normalizeFieldDefinition(field, 'field');
      if (!clone || REMOVED_FIELD_IDS.has(clone.id)){
        return;
      }
      if (!isFieldAllowedForRubric(field) || !isFieldAllowedForRubric(clone)){
        return;
      }
      if (removedFieldIds.has(clone.id)){
        return;
      }
      if (optionMap.has(clone.id)){
        return;
      }
      optionMap.set(clone.id, clone);
      optionOrder.push(clone.id);
      removedFieldIds.delete(clone.id);
    }

    const hasExplicitSelectionState = Array.isArray(rubric.fieldOptions) && rubric.fieldOptions.length > 0;
    const selected = new Set(Array.isArray(rubric.fields)
      ? rubric.fields.map((field) => String(field && field.id ? field.id : ''))
      : []);

    const initialOptions = Array.isArray(rubric.fieldOptions) && rubric.fieldOptions.length
      ? rubric.fieldOptions
      : (Array.isArray(rubric.fields) ? rubric.fields : []);

    initialOptions.forEach(pushOption);
    DEFAULT_FIELDS.forEach(pushOption);
    if (!selected.size && !hasExplicitSelectionState){
      optionOrder.forEach((id) => selected.add(id));
    }

    function ensurePhotoFirst(){
      if (isTextRubric) return;
      const index = optionOrder.indexOf('photo');
      if (index > 0){
        optionOrder.splice(index, 1);
        optionOrder.unshift('photo');
      }
    }

    function moveOption(id, step){
      const index = optionOrder.indexOf(id);
      if (index === -1) return;
      const nextIndex = index + step;
      if (nextIndex < 0 || nextIndex >= optionOrder.length) return;
      if (id !== 'photo' && nextIndex === 0){
        return;
      }
      optionOrder.splice(index, 1);
      optionOrder.splice(nextIndex, 0, id);
      renderOptions();
    }

    function removeOption(id){
      if (!id || isNonRemovableFieldId(id)){
        return;
      }
      if (!optionMap.has(id)){
        return;
      }
      optionMap.delete(id);
      const index = optionOrder.indexOf(id);
      if (index !== -1){
        optionOrder.splice(index, 1);
      }
      selected.delete(id);
      removedFieldIds.add(id);
      entryRefs.delete(id);
      errorEl.textContent = '';
      renderOptions();
    }

    ensurePhotoFirst();

    const modal = openModal({ title: 'Настройка полей рубрики' });

    const body = modal.body;
    const footer = modal.footer;
    body.innerHTML = '';
    footer.innerHTML = '';

    const nameRow = document.createElement('div');
    nameRow.className = 'rubric-name-edit';
    const nameLabel = document.createElement('label');
    nameLabel.setAttribute('for', `rubricNameEdit-${rubric.id}`);
    nameLabel.textContent = 'Название рубрики';
    const rubricNameInput = document.createElement('input');
    rubricNameInput.type = 'text';
    rubricNameInput.id = `rubricNameEdit-${rubric.id}`;
    rubricNameInput.value = rubric.name;
    nameRow.append(nameLabel, rubricNameInput);
    body.appendChild(nameRow);

    const publicRow = document.createElement('div');
    publicRow.className = 'rubric-public-settings';

    const publicToggleLabel = document.createElement('label');
    publicToggleLabel.className = 'rubric-public-settings__toggle';
    const publicToggle = document.createElement('input');
    publicToggle.type = 'checkbox';
    publicToggle.checked = Boolean(rubric.publicEnabled);
    const publicToggleText = document.createElement('span');
    publicToggleText.textContent = 'Публичная коллекция';
    publicToggleLabel.append(publicToggle, publicToggleText);

    const slugLabel = document.createElement('label');
    slugLabel.className = 'rubric-public-settings__slug';
    slugLabel.textContent = 'Публичная ссылка';
    const publicSlugInput = document.createElement('input');
    publicSlugInput.type = 'text';
    publicSlugInput.value = rubric.publicSlug || generatePublicSlug(rubric.name);
    publicSlugInput.placeholder = 'my-collection';
    slugLabel.appendChild(publicSlugInput);

    const publicLinkPreview = document.createElement('div');
    publicLinkPreview.className = 'rubric-public-settings__link';

    const copyPublicLinkBtn = document.createElement('button');
    copyPublicLinkBtn.type = 'button';
    copyPublicLinkBtn.className = 'side-btn';
    copyPublicLinkBtn.textContent = 'Скопировать ссылку';

    function updatePublicLinkPreview(){
      const nextSlug = ensureUniquePublicSlug(publicSlugInput.value || rubricNameInput.value || rubric.name, rubric.id);
      publicLinkPreview.textContent = `${window.location.origin}/u/${encodeURIComponent((window.TrezoUser && window.TrezoUser.username) || 'server-session')}/${encodeURIComponent(nextSlug)}/`;
      copyPublicLinkBtn.disabled = !publicToggle.checked;
    }

    publicSlugInput.addEventListener('input', () => {
      publicSlugInput.dataset.touched = '1';
      updatePublicLinkPreview();
    });
    rubricNameInput.addEventListener('input', () => {
      if (!publicSlugInput.dataset.touched){
        publicSlugInput.value = generatePublicSlug(rubricNameInput.value || rubric.name);
      }
      updatePublicLinkPreview();
    });
    publicSlugInput.addEventListener('change', () => {
      publicSlugInput.dataset.touched = '1';
      publicSlugInput.value = ensureUniquePublicSlug(publicSlugInput.value || rubricNameInput.value || rubric.name, rubric.id);
      updatePublicLinkPreview();
    });
    publicToggle.addEventListener('change', updatePublicLinkPreview);
    copyPublicLinkBtn.addEventListener('click', async () => {
      publicSlugInput.value = ensureUniquePublicSlug(publicSlugInput.value || rubricNameInput.value || rubric.name, rubric.id);
      updatePublicLinkPreview();
      try {
        await copyTextToClipboard(publicLinkPreview.textContent);
        copyPublicLinkBtn.textContent = 'Ссылка скопирована';
        setTimeout(() => { copyPublicLinkBtn.textContent = 'Скопировать ссылку'; }, 1600);
      } catch (err) {
        errorEl.textContent = 'Не удалось скопировать ссылку. Скопируйте её вручную из поля выше.';
      }
    });

    publicRow.append(publicToggleLabel, slugLabel, publicLinkPreview, copyPublicLinkBtn);
    body.appendChild(publicRow);
    updatePublicLinkPreview();

    const intro = document.createElement('p');
    intro.textContent = 'Отключайте поля через чекбокс, удаляйте поле отдельной кнопкой. Удалённые поля исчезают из настроек.';
    body.appendChild(intro);

    const list = document.createElement('div');
    list.className = 'field-selection-list';
    body.appendChild(list);

    const addRow = document.createElement('div');
    addRow.className = 'add-field-row';
    const addControls = document.createElement('div');
    addControls.className = 'add-field-row__controls';
    const addInput = document.createElement('input');
    addInput.type = 'text';
    addInput.placeholder = 'Название нового поля';
    const addBtn = document.createElement('button');
    addBtn.type = 'button';
    addBtn.className = 'side-btn';
    addBtn.textContent = 'Добавить поле';
    addControls.append(addInput, addBtn);

    const addResizableOption = document.createElement('label');
    addResizableOption.className = 'add-field-row__option';
    const addResizableCheckbox = document.createElement('input');
    addResizableCheckbox.type = 'checkbox';
    addResizableCheckbox.className = 'add-field-row__checkbox';
    const addResizableText = document.createElement('span');
    addResizableText.textContent = 'Масштабируемое поле';
    addResizableOption.append(addResizableCheckbox, addResizableText);

    addRow.append(addControls, addResizableOption);
    body.appendChild(addRow);

    const errorEl = document.createElement('div');
    errorEl.className = 'form-error';
    body.appendChild(errorEl);

    const entryRefs = new Map();

    function ensureEntry(field){
      if (entryRefs.has(field.id)){
        return entryRefs.get(field.id);
      }

      const wrapper = document.createElement('div');
      wrapper.className = 'field-selection-item';
      wrapper.dataset.fieldOption = field.id;

      const labelEl = document.createElement('label');
      labelEl.className = 'field-selection-item__label';
      const checkboxId = createId('field-check');
      labelEl.setAttribute('for', checkboxId);

      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox';
      checkbox.id = checkboxId;
      checkbox.value = field.id;
      checkbox.checked = selected.has(field.id);
      checkbox.addEventListener('change', () => {
        if (checkbox.checked){
          selected.add(field.id);
        } else {
          selected.delete(field.id);
        }
        errorEl.textContent = '';
      });

      const labelWrap = document.createElement('div');
      labelWrap.className = 'field-selection-label';
      const title = document.createElement('span');
      title.className = 'field-selection-label__title';
      title.textContent = field.label;
      labelWrap.appendChild(title);
      let desc = null;
      if (field.description){
        desc = document.createElement('span');
        desc.className = 'field-selection-label__description';
        desc.textContent = field.description;
        labelWrap.appendChild(desc);
      }

      labelEl.append(checkbox, labelWrap);

      let upBtn = null;
      let downBtn = null;
      let deleteBtn = null;
      let moveStack = null;

      if (!isNonRemovableFieldId(field.id)){
        const controls = document.createElement('div');
        controls.className = 'field-selection-item__controls';
        moveStack = document.createElement('div');
        moveStack.className = 'field-selection-item__move-stack';

        upBtn = document.createElement('button');
        upBtn.type = 'button';
        upBtn.className = 'field-selection-item__move';
        upBtn.innerHTML = '&#9650;';
        upBtn.setAttribute('aria-label', `Переместить поле «${field.label}» выше`);
        upBtn.addEventListener('click', () => moveOption(field.id, -1));

        downBtn = document.createElement('button');
        downBtn.type = 'button';
        downBtn.className = 'field-selection-item__move';
        downBtn.innerHTML = '&#9660;';
        downBtn.setAttribute('aria-label', `Переместить поле «${field.label}» ниже`);
        downBtn.addEventListener('click', () => moveOption(field.id, 1));

        deleteBtn = document.createElement('button');
        deleteBtn.type = 'button';
        deleteBtn.className = 'field-selection-item__delete';
        deleteBtn.innerHTML = '&times;';
        deleteBtn.setAttribute('aria-label', `Удалить поле «${field.label}»`);
        deleteBtn.addEventListener('click', () => {
          openConfirmModal(`Вы точно хотите удалить поле \"${field.label}\"?`, () => {
            removeOption(field.id);
          });
        });

        moveStack.append(upBtn, downBtn);
        controls.append(deleteBtn, moveStack);
        wrapper.append(labelEl, controls);
      } else {
        wrapper.append(labelEl);
      }

      const entry = { wrapper, checkbox, label: title, desc, upBtn, downBtn, deleteBtn, moveStack };
      entryRefs.set(field.id, entry);
      return entry;
    }

    function updateMoveButtons(){
      optionOrder.forEach((id, index) => {
        const entry = entryRefs.get(id);
        if (!entry) return;
        if (entry.upBtn){
          const prevId = optionOrder[index - 1];
          entry.upBtn.disabled = index === 0 || prevId === 'photo';
        }
        if (entry.downBtn){
          entry.downBtn.disabled = index === optionOrder.length - 1;
        }
      });
    }

    function renderOptions(){
      ensurePhotoFirst();
      list.innerHTML = '';
      optionOrder.forEach((id) => {
        const field = optionMap.get(id);
        if (!field) return;
        const entry = ensureEntry(field);
        entry.label.textContent = field.label;
        if (entry.desc){
          if (field.description){
            entry.desc.textContent = field.description;
            entry.desc.hidden = false;
          } else {
            entry.desc.hidden = true;
          }
        }
        if (entry.upBtn){
          entry.upBtn.setAttribute('aria-label', `Переместить поле «${field.label}» выше`);
        }
        if (entry.downBtn){
          entry.downBtn.setAttribute('aria-label', `Переместить поле «${field.label}» ниже`);
        }
        if (entry.deleteBtn){
          entry.deleteBtn.setAttribute('aria-label', `Удалить поле «${field.label}»`);
        }
        entry.checkbox.checked = selected.has(id);
        list.appendChild(entry.wrapper);
      });
      updateMoveButtons();
    }

    function applyCopiedFields(sourceRubric){
      if (!sourceRubric || sourceRubric.id === rubric.id){
        return;
      }
      const sourceRemoved = new Set(normalizeRemovedFieldIds(sourceRubric.removedFieldIds));
      const sourceOptions = Array.isArray(sourceRubric.fieldOptions) && sourceRubric.fieldOptions.length
        ? sourceRubric.fieldOptions
        : (Array.isArray(sourceRubric.fields) ? sourceRubric.fields : []);
      const sourceActive = Array.isArray(sourceRubric.fields) ? sourceRubric.fields : [];

      const nextMap = new Map();
      const nextOrder = [];

      function pushCopiedOption(field){
        const clone = normalizeFieldDefinition(field, 'field');
        if (!clone || (clone.id === 'photo' && isTextRubric)){
          return;
        }
        if (REMOVED_FIELD_IDS.has(clone.id)){
          return;
        }
        if (!isFieldAllowedForRubric(field) || !isFieldAllowedForRubric(clone)){
          return;
        }
        if (nextMap.has(clone.id)){
          return;
        }
        nextMap.set(clone.id, clone);
        nextOrder.push(clone.id);
      }

      sourceOptions.forEach(pushCopiedOption);
      sourceActive.forEach(pushCopiedOption);

      const nextSelected = new Set();
      sourceActive.forEach((field) => {
        const id = field && field.id ? String(field.id) : '';
        if (id && nextMap.has(id)){
          nextSelected.add(id);
        }
      });

      optionMap.clear();
      optionOrder.length = 0;
      selected.clear();
      removedFieldIds.clear();
      entryRefs.clear();

      nextOrder.forEach((id) => {
        optionOrder.push(id);
        optionMap.set(id, nextMap.get(id));
      });
      nextSelected.forEach((id) => {
        if (optionMap.has(id)){
          selected.add(id);
        }
      });

      sourceRemoved.forEach((id) => {
        if (isNonRemovableFieldId(id)){
          return;
        }
        if (!optionMap.has(id)){
          removedFieldIds.add(id);
        }
      });

      errorEl.textContent = '';
      renderOptions();
    }

    function openCopyFieldsModal(){
      const sources = state.rubrics.filter((item) => item && item.id !== rubric.id);
      if (!sources.length){
        errorEl.textContent = 'Нет других рубрик для копирования полей.';
        return;
      }

      const copyModal = openModal({ title: 'Копировать поля из рубрики' });
      copyModal.body.innerHTML = '';
      copyModal.footer.innerHTML = '';

      const label = document.createElement('label');
      label.setAttribute('for', 'copyFieldsSourceSelect');
      label.textContent = 'Выберите рубрику';

      const select = document.createElement('select');
      select.id = 'copyFieldsSourceSelect';
      select.className = 'rubric-create__input';
      sources.forEach((item) => {
        const option = document.createElement('option');
        option.value = item.id;
        option.textContent = item.name || 'Без названия';
        select.appendChild(option);
      });

      const note = document.createElement('p');
      note.className = 'form-error';
      note.textContent = '';

      copyModal.body.append(label, select, note);

      const applyBtn = document.createElement('button');
      applyBtn.type = 'button';
      applyBtn.className = 'side-btn';
      applyBtn.textContent = 'Копировать';
      applyBtn.addEventListener('click', () => {
        const sourceId = String(select.value || '');
        if (!sourceId || sourceId === rubric.id){
          note.textContent = 'Выберите другую рубрику.';
          return;
        }
        const sourceRubric = getRubric(sourceId);
        if (!sourceRubric){
          note.textContent = 'Исходная рубрика не найдена.';
          return;
        }
        applyCopiedFields(sourceRubric);
        copyModal.close();
      });

      const cancelBtn = createActionButton('Отмена');
      cancelBtn.addEventListener('click', () => copyModal.close());

      copyModal.footer.append(cancelBtn, applyBtn);
    }

    renderOptions();

    addBtn.addEventListener('click', () => {
      const value = addInput.value.trim();
      if (!value){
        errorEl.textContent = 'Введите название нового поля';
        addInput.focus();
        return;
      }
      const id = createId('field');
      const isResizable = addResizableCheckbox.checked;
      const field = {
        id,
        label: value,
        type: isResizable ? 'textarea' : 'text',
        description: isResizable ? 'Поле для подробного описания' : '',
        custom: true
      };
      optionMap.set(id, field);
      optionOrder.push(id);
      selected.add(id);
      addInput.value = '';
      addResizableCheckbox.checked = false;
      errorEl.textContent = '';
      renderOptions();
    });

    addInput.addEventListener('keydown', (event) => {
      if (event.key === 'Enter'){
        event.preventDefault();
        addBtn.click();
      }
    });

    rubricNameInput.addEventListener('input', () => {
      if (errorEl.textContent){
        errorEl.textContent = '';
      }
    });

    const copyBtn = document.createElement('button');
    copyBtn.type = 'button';
    copyBtn.className = 'side-btn';
    copyBtn.textContent = 'Копировать поля';
    copyBtn.addEventListener('click', openCopyFieldsModal);

    const saveBtn = document.createElement('button');
    saveBtn.type = 'button';
    saveBtn.className = 'side-btn';
    saveBtn.textContent = 'Сохранить';
    saveBtn.addEventListener('click', () => {
      const newName = rubricNameInput.value.trim();
      if (!newName){
        errorEl.textContent = 'Введите название рубрики.';
        rubricNameInput.focus();
        return;
      }

      const previousImageFieldIds = new Set();
      const prevFields = Array.isArray(rubric.fields) ? rubric.fields : [];
      const prevOptions = Array.isArray(rubric.fieldOptions) ? rubric.fieldOptions : [];
      prevFields.concat(prevOptions).forEach((field) => {
        if (!field || !field.id){
          return;
        }
        if (field.id === 'photo' || field.type === 'image'){
          previousImageFieldIds.add(String(field.id));
        }
      });

      const allOptions = [];
      optionOrder.forEach((id) => {
        const field = optionMap.get(id);
        if (!field){
          return;
        }
        allOptions.push({
          id: field.id,
          label: field.label,
          type: field.type || 'text',
          description: field.description || '',
          custom: Boolean(field.custom)
        });
      });

      const updatedFields = [];
      allOptions.forEach((field) => {
        if (!selected.has(field.id)){
          return;
        }
        updatedFields.push({
          id: field.id,
          label: field.label,
          type: field.type,
          description: field.description,
          custom: field.custom
        });
      });

      const photoIndex = updatedFields.findIndex((field) => field.id === 'photo');
      if (photoIndex > 0){
        const photoField = updatedFields.splice(photoIndex, 1)[0];
        updatedFields.unshift(photoField);
      }

      if (rubric.mode === 'text'){
        for (let i = updatedFields.length - 1; i >= 0; i -= 1){
          if (updatedFields[i].id === 'photo' || updatedFields[i].type === 'image'){
            updatedFields.splice(i, 1);
          }
        }
        for (let i = allOptions.length - 1; i >= 0; i -= 1){
          if (allOptions[i].id === 'photo' || allOptions[i].type === 'image'){
            allOptions.splice(i, 1);
          }
        }
      }

      const removedForSave = new Set();
      removedFieldIds.forEach((id) => {
        if (!id || isNonRemovableFieldId(id)){
          return;
        }
        if (!optionMap.has(id)){
          removedForSave.add(id);
        }
      });

      const nextPublicSlug = ensureUniquePublicSlug(publicSlugInput.value || newName, rubric.id);
      rubric.name = newName;
      rubric.publicEnabled = Boolean(publicToggle.checked);
      rubric.publicSlug = nextPublicSlug;
      rubric.fields = updatedFields;
      rubric.fieldOptions = allOptions;
      rubric.removedFieldIds = Array.from(removedForSave);

      const files = Array.isArray(rubric.files) ? rubric.files : [];
      files.forEach((file) => {
        if (!file || typeof file.values !== 'object' || !file.values){
          return;
        }
        removedForSave.forEach((id) => {
          if (Object.prototype.hasOwnProperty.call(file.values, id)){
            delete file.values[id];
          }
        });
        if (rubric.mode === 'text'){
          previousImageFieldIds.forEach((id) => {
            if (Object.prototype.hasOwnProperty.call(file.values, id)){
              delete file.values[id];
            }
          });
        }
      });

      const wasCreated = !isEdit;
      persistAndRender().then((saved) => {
        if (saved && wasCreated) reachGoal('card_created');
      });
      modal.close();
    });

    const deleteBtn = createActionButton('Удалить рубрику', { variant: 'danger' });
    deleteBtn.classList.add('rubric-delete-btn');
    deleteBtn.addEventListener('click', () => {
      openConfirmModal('Вы точно хотите удалить рубрику?', () => {
        state.rubrics = state.rubrics.filter((item) => item.id !== rubric.id);
        if (activeRubricId === rubric.id){
          activeRubricId = state.rubrics.length ? ALL_RUBRICS_ID : null;
        }
        persistAndRender();
        modal.close();
      });
    });

    footer.append(deleteBtn, copyBtn, saveBtn);
  }
  function buildFileForm(rubric, file){
    const container = document.createElement('div');
    container.className = 'archive-file-form';
    const form = document.createElement('form');
    form.className = 'file-form-grid';
    container.appendChild(form);

    const errorEl = document.createElement('div');
    errorEl.className = 'form-error';
    container.appendChild(errorEl);

    const inputs = new Map();
    const imageDraft = new Map();
    const imagePreviewRefs = new Map();
    const cleanupFns = [];

    const statusBlock = document.createElement('div');
    statusBlock.className = 'field-block file-status-field';
    const statusLabel = document.createElement('label');
    statusLabel.textContent = 'Статус';
    const statusControl = createStatusDropdown(file && file.status, cleanupFns);
    statusBlock.append(statusLabel, statusControl.element);
    form.appendChild(statusBlock);

    rubric.fields.forEach((field) => {
      const block = document.createElement('div');
      block.className = 'field-block';
      const label = document.createElement('label');
      label.textContent = field.label;
      block.appendChild(label);

      if (field.type === 'image'){
        const preview = document.createElement('div');
        preview.className = 'image-preview image-preview--interactive image-preview--resizable';
        preview.tabIndex = 0;
        preview.setAttribute('role', 'button');
        preview.setAttribute('aria-label', `Выбрать изображение для поля «${field.label}»`);

        const input = document.createElement('input');
        input.type = 'file';
        input.accept = 'image/*';
        input.multiple = true;
        input.dataset.field = field.id;
        input.className = 'sr-only';

        let pendingSizingRaf = null;
        let preferredActiveImageId = null;
        let preferredActiveImageIndex = 0;
        const limitMessage = 'Можно добавить не более 5 фотографий.';

        function markLimitError(active){
          if (active){
            errorEl.textContent = limitMessage;
            errorEl.dataset.source = 'image-limit';
          } else if (errorEl.dataset.source === 'image-limit'){
            errorEl.textContent = '';
            delete errorEl.dataset.source;
          }
        }

        function applySizing(draft, naturalWidth, naturalHeight){
          if (!draft) return;
          const ratio = naturalWidth / naturalHeight || 1;

          let width = Number.isFinite(draft.frameWidth) && draft.frameWidth > 0 ? Number(draft.frameWidth) : null;
          let height = Number.isFinite(draft.frameHeight) && draft.frameHeight > 0 ? Number(draft.frameHeight) : null;

          const resolveHostWidth = () => {
            let hostWidth = block.clientWidth;
            if (!hostWidth){
              const parent = block.parentElement;
              if (parent && parent.clientWidth){
                hostWidth = parent.clientWidth;
              }
            }
            return hostWidth;
          };

          const hostWidth = resolveHostWidth();
          const shouldDelay = !hostWidth || hostWidth <= 0;
          if ((!width || !height) && shouldDelay){
            if (pendingSizingRaf === null){
              pendingSizingRaf = requestAnimationFrame(() => {
                pendingSizingRaf = null;
                const current = imageDraft.get(field.id);
                if (current){
                  applySizing(current, naturalWidth, naturalHeight);
                }
              });
            }
            return;
          }

          if (!width || !height){
            let targetWidth = hostWidth || naturalWidth;
            if (!targetWidth || targetWidth <= 0){
              targetWidth = naturalWidth;
            }
            width = Math.min(targetWidth, naturalWidth);
            if (!width || width <= 0){
              width = naturalWidth;
            }
            height = width / ratio;
          } else if (hostWidth > 0 && width > hostWidth){
            const scale = hostWidth / width;
            width = hostWidth;
            height = height * scale;
          }

          preview.style.width = `${Math.round(width)}px`;
          preview.style.height = `${Math.round(height)}px`;
          preview.style.setProperty('--image-preview-aspect', ratio.toFixed(6));
          preview.classList.add('image-preview--sized');

          draft.frameWidth = Math.round(width);
          draft.frameHeight = Math.round(height);
          draft.naturalWidth = naturalWidth;
          draft.naturalHeight = naturalHeight;
          imageDraft.set(field.id, draft);
        }

        function setInitialDimensions(draft){
          if (!draft) return;
          const width = Number.isFinite(draft.frameWidth) && draft.frameWidth > 0 ? Math.round(draft.frameWidth) : null;
          const height = Number.isFinite(draft.frameHeight) && draft.frameHeight > 0 ? Math.round(draft.frameHeight) : null;
          preview.style.removeProperty('--image-preview-aspect');
          if (width){
            preview.style.width = `${width}px`;
          } else {
            preview.style.removeProperty('width');
          }
          if (height){
            preview.style.height = `${height}px`;
          } else {
            preview.style.removeProperty('height');
          }
          if (width && height){
            preview.style.setProperty('--image-preview-aspect', (width / height).toFixed(6));
            preview.classList.add('image-preview--sized');
          } else {
            preview.classList.remove('image-preview--sized');
          }
        }

        function ensureSizing(draft){
          if (!draft || !draft.items || !draft.items.length){
            return;
          }
          let naturalWidth = draft.naturalWidth || null;
          let naturalHeight = draft.naturalHeight || null;
          const best = computeLargestDimensions(draft.items);
          if (best){
            naturalWidth = best.width;
            naturalHeight = best.height;
            draft.naturalWidth = naturalWidth;
            draft.naturalHeight = naturalHeight;
          }
          if (!naturalWidth || !naturalHeight){
            return;
          }
          applySizing(draft, naturalWidth, naturalHeight);
        }

        function buildSplitView(draft, options){
          const opts = options || {};
          const hoverable = draft.items.length > 1;
          const supportsPin = typeof opts.onPin === 'function';
          const supportsReplace = Boolean(opts.enableReplace);
          const itemCount = draft.items.length;
          let activeIndex = 0;
          const strip = document.createElement('div');
          strip.className = 'media-split';
          strip.style.setProperty('--media-split-count', Math.max(itemCount, 1));
          if (hoverable){
            strip.classList.add('media-split--hoverable', 'media-split--multi', 'media-split--manual');
            strip.tabIndex = 0;
          }

          let pinnedId = opts.pinnedId || (draft && draft.pinnedId ? String(draft.pinnedId) : null);
          if (pinnedId && !draft.items.some((candidate) => candidate && candidate.id === pinnedId)){
            pinnedId = null;
          }
          if (!pinnedId && draft.items.length){
            pinnedId = draft.items[0].id;
          }
          draft.pinnedId = pinnedId || null;
          const preferredActiveId = opts.activeId ? String(opts.activeId) : null;
          const preferredActiveIndex = Number.isInteger(opts.activeIndex) ? Number(opts.activeIndex) : null;
          if (preferredActiveId){
            activeIndex = draft.items.findIndex((item) => item && String(item.id) === preferredActiveId);
          }
          if (activeIndex < 0 && preferredActiveIndex !== null){
            activeIndex = Math.min(Math.max(preferredActiveIndex, 0), Math.max(draft.items.length - 1, 0));
          }
          if (activeIndex < 0){
            activeIndex = draft.items.findIndex((item) => item && item.id === pinnedId);
          }
          if (activeIndex < 0){
            activeIndex = 0;
          }

          draft.items.forEach((item, index) => {
            const slice = document.createElement('div');
            slice.className = 'media-split__item';
            slice.dataset.index = String(index);
            slice.dataset.imageId = String(item.id);
            if (hoverable){
              slice.tabIndex = 0;
              slice.setAttribute('role', 'button');
              slice.setAttribute('aria-label', `${field.label} ${index + 1}`);
              const geometry = computeSplitGeometry(itemCount, index);
              if (geometry){
                slice.style.clipPath = geometry.clip;
                slice.dataset.clipPath = geometry.clip;
                slice.dataset.centroidX = geometry.centroid ? geometry.centroid[0].toFixed(6) : '0.5';
                slice.dataset.centroidY = geometry.centroid ? geometry.centroid[1].toFixed(6) : '0.5';
                if (geometry.centroid){
                  const offsetX = geometry.centroid[0] - 0.5;
                  slice.dataset.offsetX = offsetX.toFixed(6);
                }
              }
            }

            if (!slice.dataset.offsetX){
              const fallbackOffsetX = ((index + 0.5) / Math.max(itemCount, 1)) - 0.5;
              slice.dataset.offsetX = fallbackOffsetX.toFixed(6);
            }
            slice.dataset.offsetY = slice.dataset.offsetY || '0';

            const isPinned = Boolean(pinnedId && item.id === pinnedId);
            if (isPinned){
              slice.classList.add('media-split__item--primary');
            }

            const backdrop = document.createElement('div');
            backdrop.className = 'media-split__backdrop';
            backdrop.style.backgroundImage = `url(${item.src})`;
            slice.appendChild(backdrop);

            const img = document.createElement('img');
            img.src = item.src;
            img.alt = draft.items.length > 1 ? `${field.label} ${index + 1}` : field.label;
            img.decoding = 'async';
            img.draggable = false;
            img.addEventListener('load', () => {
              const current = imageDraft.get(field.id);
              if (!current || !current.items || !current.items[index]){
                return;
              }
              const naturalWidth = img.naturalWidth || null;
              const naturalHeight = img.naturalHeight || null;
              if (naturalWidth && naturalHeight){
                current.items[index].naturalWidth = naturalWidth;
                current.items[index].naturalHeight = naturalHeight;
                const best = computeLargestDimensions(current.items);
                if (best){
                  current.naturalWidth = best.width;
                  current.naturalHeight = best.height;
                }
                imageDraft.set(field.id, current);
                ensureSizing(current);
              }
            });
            slice.appendChild(img);

            if (supportsPin || supportsReplace){
              const actions = document.createElement('div');
              actions.className = 'media-split__actions';

              if (supportsPin){
                const pinButton = document.createElement('button');
                pinButton.type = 'button';
                pinButton.className = 'media-split__pin';
                pinButton.innerHTML = '<span aria-hidden="true">📌</span>';
                pinButton.title = isPinned ? 'Закреплено как основное фото' : 'Сделать основным';
                pinButton.setAttribute('aria-label', isPinned ? 'Фото закреплено как основное' : 'Закрепить фото как основное');
                pinButton.setAttribute('aria-pressed', isPinned ? 'true' : 'false');
                if (isPinned){
                  pinButton.classList.add('media-split__pin--active');
                }
                pinButton.addEventListener('click', (event) => {
                  event.preventDefault();
                  event.stopPropagation();
                  const activeItem = strip.querySelector('.media-split__item--active') || slice;
                  const activeId = activeItem && activeItem.dataset.imageId ? activeItem.dataset.imageId : item.id;
                  opts.onPin(activeId);
                });
                actions.appendChild(pinButton);
              }

              if (supportsReplace){
                const replaceInput = document.createElement('input');
                replaceInput.type = 'file';
                replaceInput.accept = 'image/*';
                replaceInput.hidden = true;
                replaceInput.addEventListener('click', (event) => {
                  event.stopPropagation();
                });

                const replaceButton = document.createElement('button');
                replaceButton.type = 'button';
                replaceButton.className = 'media-split__replace';
                replaceButton.textContent = 'Заменить';
                replaceButton.title = 'Заменить это фото';
                replaceButton.setAttribute('aria-label', 'Заменить это фото');
                replaceButton.addEventListener('click', (event) => {
                  event.preventDefault();
                  event.stopPropagation();
                  const activeItem = strip.querySelector('.media-split__item--active') || slice;
                  const targetId = activeItem && activeItem.dataset.imageId ? String(activeItem.dataset.imageId) : String(slice.dataset.imageId || item.id);
                  const targetIndex = activeItem && activeItem.dataset.index ? String(activeItem.dataset.index) : String(slice.dataset.index || '');
                  replaceInput.dataset.targetId = targetId;
                  replaceInput.dataset.targetIndex = targetIndex;
                  replaceInput.click();
                });

                replaceInput.addEventListener('change', async (event) => {
                  event.stopPropagation();
                  const selected = Array.from(replaceInput.files || []);
                  const nextFile = selected[0];
                  if (!nextFile){
                    delete replaceInput.dataset.targetId;
                    delete replaceInput.dataset.targetIndex;
                    return;
                  }

                  const nextItem = await fileToImageItem(nextFile);
                  replaceInput.value = '';
                  if (!nextItem){
                    delete replaceInput.dataset.targetId;
                    delete replaceInput.dataset.targetIndex;
                    return;
                  }

                  const current = imageDraft.get(field.id);
                  if (!current || !Array.isArray(current.items) || !current.items.length){
                    delete replaceInput.dataset.targetId;
                    delete replaceInput.dataset.targetIndex;
                    return;
                  }
                  const indexFromInput = Number.parseInt(replaceInput.dataset.targetIndex || '', 10);
                  const indexFromSlice = Number.parseInt(slice.dataset.index || '', 10);
                  let targetIndex = Number.isInteger(indexFromInput)
                    && indexFromInput >= 0
                    && indexFromInput < current.items.length
                    ? indexFromInput
                    : -1;
                  const targetId = String(replaceInput.dataset.targetId || slice.dataset.imageId || item.id);
                  if (targetIndex < 0){
                    targetIndex = current.items.findIndex((candidate) => candidate && String(candidate.id) === targetId);
                  }
                  if (targetIndex < 0 && Number.isInteger(indexFromSlice) && indexFromSlice >= 0 && indexFromSlice < current.items.length){
                    targetIndex = indexFromSlice;
                  }
                  if (targetIndex < 0){
                    delete replaceInput.dataset.targetId;
                    delete replaceInput.dataset.targetIndex;
                    return;
                  }
                  const existingItem = current.items[targetIndex];
                  const replacementId = existingItem && existingItem.id ? String(existingItem.id) : targetId;
                  const pinnedIndex = current.pinnedId
                    ? current.items.findIndex((candidate) => candidate && String(candidate.id) === String(current.pinnedId))
                    : -1;
                  const wasPinned = pinnedIndex >= 0
                    ? targetIndex === pinnedIndex
                    : Boolean(current.pinnedId && String(current.pinnedId) === targetId);
                  current.items[targetIndex] = {
                    ...nextItem,
                    id: replacementId
                  };
                  if (wasPinned){
                    current.pinnedId = replacementId;
                  } else if (current.pinnedId && !current.items.some((candidate) => candidate && String(candidate.id) === String(current.pinnedId))){
                    current.pinnedId = current.items[0] && current.items[0].id ? String(current.items[0].id) : null;
                  }
                  const best = computeLargestDimensions(current.items);
                  if (best){
                    current.naturalWidth = best.width;
                    current.naturalHeight = best.height;
                  }
                  delete replaceInput.dataset.targetId;
                  delete replaceInput.dataset.targetIndex;
                  imageDraft.set(field.id, current);
                  if (typeof opts.onActiveChange === 'function'){
                    opts.onActiveChange(replacementId, targetIndex);
                  }
                  renderPreview(current);
                });

                actions.appendChild(replaceButton);
                slice.appendChild(replaceInput);
              }

              slice.appendChild(actions);
            }

            strip.appendChild(slice);
          });
          strip.dataset.safeTop = '0';
          strip.style.setProperty('--media-split-safe-top', '0px');
          if (supportsPin || supportsReplace){
            requestAnimationFrame(() => {
              const firstActions = strip.querySelector('.media-split__actions');
              if (!firstActions){
                return;
              }
              const actionStyles = getComputedStyle(firstActions);
              const actionHeight = firstActions.offsetHeight || parseFloat(actionStyles.height) || 0;
              const offsetTop = parseFloat(actionStyles.top) || 0;
              const safe = Math.max(0, Math.ceil(actionHeight + offsetTop));
              strip.dataset.safeTop = String(safe);
              strip.style.setProperty('--media-split-safe-top', `${safe}px`);
            });
          }
          if (hoverable){
            const prevBtn = document.createElement('button');
            prevBtn.type = 'button';
            prevBtn.className = 'media-split__nav media-split__nav--prev';
            prevBtn.setAttribute('aria-label', 'Предыдущее фото');

            const nextBtn = document.createElement('button');
            nextBtn.type = 'button';
            nextBtn.className = 'media-split__nav media-split__nav--next';
            nextBtn.setAttribute('aria-label', 'Следующее фото');

            const items = Array.from(strip.querySelectorAll('.media-split__item'));

            const updateActive = (index) => {
              const clamped = Math.min(Math.max(index, 0), items.length - 1);
              activeIndex = clamped;
              items.forEach((item, idx) => {
                item.classList.toggle('media-split__item--active', idx === clamped);
              });
              if (typeof opts.onActiveChange === 'function'){
                const activeItem = items[clamped];
                const activeId = activeItem && activeItem.dataset.imageId ? String(activeItem.dataset.imageId) : null;
                opts.onActiveChange(activeId, clamped);
              }
              prevBtn.disabled = clamped === 0;
              nextBtn.disabled = clamped === items.length - 1;
            };

            const stepActive = (delta) => {
              updateActive(activeIndex + delta);
            };

            prevBtn.addEventListener('click', (event) => {
              event.stopPropagation();
              stepActive(-1);
            });
            nextBtn.addEventListener('click', (event) => {
              event.stopPropagation();
              stepActive(1);
            });

            strip.addEventListener('keydown', (event) => {
              if (event.key === 'ArrowLeft'){
                event.preventDefault();
                stepActive(-1);
              } else if (event.key === 'ArrowRight'){
                event.preventDefault();
                stepActive(1);
              }
            });

            strip.append(prevBtn, nextBtn);
            updateActive(activeIndex);
          }
          return strip;
        }

        function renderPreview(rawValue){
          if (pendingSizingRaf !== null){
            cancelAnimationFrame(pendingSizingRaf);
            pendingSizingRaf = null;
          }
          preview.innerHTML = '';
          preview.classList.remove('image-preview--has-image', 'image-preview--multi', 'image-preview--sized');
          preview.style.removeProperty('width');
          preview.style.removeProperty('height');
          preview.style.removeProperty('--image-preview-aspect');

          const normalized = normalizeImageValue(rawValue);
          if (!normalized){
            imageDraft.delete(field.id);
            const hint = document.createElement('span');
            hint.className = 'image-preview__hint';
            hint.textContent = 'Нажмите, чтобы выбрать фото';
            preview.appendChild(hint);
            return;
          }

          const draft = cloneImageValue(normalized);
          imageDraft.set(field.id, draft);

          setInitialDimensions(draft);

          const strip = buildSplitView(draft, {
            enableReplace: true,
            activeId: preferredActiveImageId,
            activeIndex: preferredActiveImageIndex,
            pinnedId: draft.pinnedId,
            onActiveChange(imageId, index){
              preferredActiveImageId = imageId ? String(imageId) : null;
              if (Number.isInteger(index)){
                preferredActiveImageIndex = Number(index);
              }
            },
            onPin(imageId){
              const current = imageDraft.get(field.id);
              if (!current || !Array.isArray(current.items)){
                return;
              }
              if (!current.items.some((item) => item && item.id === imageId)){
                return;
              }
              current.pinnedId = imageId;
              imageDraft.set(field.id, current);
              preferredActiveImageId = String(imageId);
              const nextIndex = current.items.findIndex((item) => item && String(item.id) === String(imageId));
              if (nextIndex >= 0){
                preferredActiveImageIndex = nextIndex;
              }
              renderPreview(current);
            }
          });
          preview.appendChild(strip);
          preview.classList.add('image-preview--has-image');
          if (draft.items.length > 1){
            preview.classList.add('image-preview--multi');
          }

          if (draft.naturalWidth && draft.naturalHeight){
            ensureSizing(draft);
          } else {
            pendingSizingRaf = requestAnimationFrame(() => {
              pendingSizingRaf = null;
              const current = imageDraft.get(field.id);
              if (current){
                ensureSizing(current);
              }
            });
          }
        }

        const existing = file ? getFieldValue(rubric, file, field) : null;
        const initialValue = existing ? cloneImageValue(existing) : null;
        if (initialValue && initialValue.pinnedId){
          preferredActiveImageId = String(initialValue.pinnedId);
          const startIndex = initialValue.items.findIndex((item) => item && String(item.id) === String(initialValue.pinnedId));
          preferredActiveImageIndex = startIndex >= 0 ? startIndex : 0;
        }
        if (initialValue){
          imageDraft.set(field.id, cloneImageValue(initialValue));
        }
        renderPreview(initialValue);

        function openPicker(event){
          if (event){
            const target = event.target;
            if (target && typeof target.closest === 'function'){
              if (
                target.closest('.media-split__actions')
                || target.closest('.media-split__nav')
                || target.closest('.media-split__pin')
                || target.closest('.media-split__replace')
              ){
                return;
              }
            }
          }
          input.click();
        }

        preview.addEventListener('click', openPicker);
        preview.addEventListener('keydown', (event) => {
          if (event.key === 'Enter' || event.key === ' '){
            event.preventDefault();
            openPicker();
          }
        });

        input.addEventListener('change', async () => {
          const files = Array.from(input.files || []);
          if (!files.length){
            const fallback = imageDraft.get(field.id)
              || (file && file.values && file.values[field.id] ? normalizeImageValue(file.values[field.id]) : null);
            renderPreview(fallback);
            markLimitError(false);
            return;
          }

          const limited = files.slice(0, MAX_IMAGE_COUNT);
          const overLimit = files.length > MAX_IMAGE_COUNT;
          markLimitError(overLimit);

          const processed = await Promise.all(limited.map((fileObj) => fileToImageItem(fileObj)));
          const pendingItems = processed.filter(Boolean);

          if (!pendingItems.length){
            const fallback = imageDraft.get(field.id)
              || (file && file.values && file.values[field.id] ? normalizeImageValue(file.values[field.id]) : null);
            renderPreview(fallback);
            if (!overLimit){
              markLimitError(false);
            }
            input.value = '';
            return;
          }

          const prevDraft = imageDraft.get(field.id);
          const nextValue = normalizeImageValue({
            items: pendingItems,
            frameWidth: prevDraft ? prevDraft.frameWidth : null,
            frameHeight: prevDraft ? prevDraft.frameHeight : null
          });
          renderPreview(nextValue);
          if (!overLimit){
            markLimitError(false);
          }

          input.value = '';
        });

        if (typeof ResizeObserver === 'function'){
          const resizeObserver = new ResizeObserver(() => {
            const draftValue = imageDraft.get(field.id);
            if (!draftValue || !hasImageItems(draftValue)){
              return;
            }
            const rect = preview.getBoundingClientRect();
            draftValue.frameWidth = Math.round(rect.width);
            draftValue.frameHeight = Math.round(rect.height);
            imageDraft.set(field.id, draftValue);
          });
          resizeObserver.observe(preview);
          cleanupFns.push(() => resizeObserver.disconnect());
        }

        block.append(preview, input);
        imagePreviewRefs.set(field.id, preview);
      } else {
        const existingValue = file ? getFieldValue(rubric, file, field) : '';
        let input;
        if (field.type === 'textarea'){
          input = document.createElement('textarea');
          input.value = existingValue;
        } else {
          input = document.createElement('input');
          input.type = 'text';
          input.value = existingValue;
          setupNonScalableInputLimit(input, cleanupFns);
        }
        input.dataset.field = field.id;
        inputs.set(field.id, input);
        block.appendChild(input);
      }

      form.appendChild(block);
    });

    form.addEventListener('submit', (event) => {
      event.preventDefault();
    });

    function collect(){
      const values = {};
      rubric.fields.forEach((field) => {
        if (field.type === 'image'){
          let stored = null;
          if (imageDraft.has(field.id)){
            const draftSource = imageDraft.get(field.id);
            if (draftSource && hasImageItems(draftSource)){
              const draft = cloneImageValue(draftSource);
              const previewEl = imagePreviewRefs.get(field.id);
              if (previewEl){
                const rect = previewEl.getBoundingClientRect();
                if (rect && rect.width > 0 && rect.height > 0){
                  draft.frameWidth = Math.round(rect.width);
                  draft.frameHeight = Math.round(rect.height);
                }
              }
              stored = normalizeImageValue(draft);
            }
          } else if (file && file.values && file.values[field.id]){
            stored = normalizeImageValue(file.values[field.id]);
          }
          if (stored){
            values[field.id] = stored;
          }
        } else {
          const input = inputs.get(field.id);
          if (input){
            const limit = input.maxLength;
            const trimmed = (input.value || '').trim();
            values[field.id] = limit > 0 && trimmed.length > limit ? trimmed.slice(0, limit) : trimmed;
          } else {
            values[field.id] = '';
          }
        }
      });
      return values;
    }

    function focusFirst(){
      const firstField = form.querySelector('input:not([type="file"]), textarea');
      if (firstField) firstField.focus({ preventScroll: true });
    }

    function setError(message){
      delete errorEl.dataset.source;
      errorEl.textContent = message || '';
    }

    function cleanup(){
      while (cleanupFns.length){
        const fn = cleanupFns.pop();
        try {
          fn();
        } catch (err) {}
      }
    }

    function getStatus(){
      return normalizeFileStatus(statusControl.getValue());
    }

    return { container, collect, getStatus, setError, focusFirst, cleanup };
  }

  function openFileFormModal(rubricId, fileId){
    if (!stateReady){
      return;
    }
    const rubric = getRubric(rubricId);
    if (!rubric || !rubric.fields.length){
      return;
    }
    const isEdit = Boolean(fileId);
    const file = isEdit ? rubric.files.find((item) => item.id === fileId) : null;
    const formContext = buildFileForm(rubric, file);
    const modal = openModal({
      title: isEdit ? 'Редактирование файла' : 'Добавление файла',
      onClose: () => {
        if (formContext && typeof formContext.cleanup === 'function'){
          formContext.cleanup();
        }
      }
    });
    const { container, collect, getStatus, setError, focusFirst } = formContext;
    modal.body.innerHTML = '';
    modal.body.appendChild(container);
    modal.footer.innerHTML = '';
    modal.footer.className = 'archive-modal__footer archive-modal__footer--pinned archive-modal__footer--single';

    const saveBtn = document.createElement('button');
    saveBtn.type = 'button';
    saveBtn.className = 'side-btn';
    saveBtn.textContent = 'Сохранить';
    saveBtn.addEventListener('click', () => {
      const values = collect();
      const mainField = rubric.fields.find((field) => field.id === 'title');
      if (mainField && !values[mainField.id]){
        setError(`Заполните поле «${mainField.label}».`);
        const target = modal.body.querySelector(`[data-field="${mainField.id}"]`);
        if (target) target.focus();
        return;
      }
      setError('');

      if (isEdit && file){
        file.values = values;
        file.status = getStatus();
        file.updatedAt = Date.now();
      } else {
        rubric.files.push({
          id: createId('file'),
          status: getStatus(),
          createdAt: Date.now(),
          updatedAt: null,
          values
        });
      }

      persistAndRender();
      modal.close();
    });

    modal.footer.appendChild(saveBtn);
    focusFirst();
    modal.body.scrollTop = 0;
  }

  function openMoveFileModal(options){
    const config = options || {};
    const currentRubricId = config.rubricId ? String(config.rubricId) : '';
    const fileId = config.fileId ? String(config.fileId) : '';
    const onMoved = typeof config.onMoved === 'function' ? config.onMoved : null;

    const modal = openModal({ title: 'Перенести файл' });
    modal.body.innerHTML = '';
    modal.footer.innerHTML = '';

    const bodyWrap = document.createElement('div');
    bodyWrap.className = 'move-file-picker';
    modal.body.appendChild(bodyWrap);

    const hint = document.createElement('p');
    hint.className = 'move-file-picker__hint';
    hint.textContent = 'Выберите рубрику, в которую нужно перенести файл.';
    bodyWrap.appendChild(hint);

    const errorEl = document.createElement('div');
    errorEl.className = 'form-error';
    bodyWrap.appendChild(errorEl);

    const rubrics = Array.isArray(state.rubrics) ? state.rubrics : [];
    if (!rubrics.length){
      const empty = document.createElement('div');
      empty.className = 'move-file-empty';
      empty.textContent = 'Рубрики пока не созданы.';
      bodyWrap.appendChild(empty);
    } else {
      const list = document.createElement('div');
      list.className = 'move-file-list';
      bodyWrap.appendChild(list);

      let hasAvailableTarget = false;

      rubrics.forEach((rubricItem) => {
        const rubricId = rubricItem && rubricItem.id ? String(rubricItem.id) : '';
        const isCurrent = rubricId === currentRubricId;
        if (!isCurrent){
          hasAvailableTarget = true;
        }

        const option = document.createElement('button');
        option.type = 'button';
        option.className = 'move-file-option';
        if (isCurrent){
          option.classList.add('move-file-option--current');
          option.disabled = true;
        }

        const title = document.createElement('span');
        title.className = 'move-file-option__title';
        title.textContent = rubricItem && rubricItem.name ? rubricItem.name : 'Рубрика';

        const meta = document.createElement('span');
        meta.className = 'move-file-option__meta';
        meta.textContent = isCurrent ? 'Текущая рубрика' : 'Нажмите для переноса';

        option.append(title, meta);

        if (!isCurrent){
          option.addEventListener('click', async () => {
            const preserveAllView = activeRubricId === ALL_RUBRICS_ID;
            const optionButtons = list.querySelectorAll('button');
            optionButtons.forEach((button) => { button.disabled = true; });
            errorEl.textContent = '';
            try {
              const responseData = await moveArchiveFileRequest(fileId, currentRubricId, rubricId);
              const nextState = normalizeState(responseData.state || { rubrics: [] });
              applyNormalizedState(nextState);
              syncSearchState(nextState, { reset: true });
              activeRubricId = preserveAllView ? ALL_RUBRICS_ID : rubricId;
              renderRubrics();
              requestSearchRefresh();
              modal.close();
              if (onMoved){
                onMoved(rubricId, fileId);
              }
            } catch (error){
              optionButtons.forEach((button) => {
                if (!button.classList.contains('move-file-option--current')){
                  button.disabled = false;
                }
              });
              errorEl.textContent = error && error.message ? error.message : 'Не удалось перенести файл.';
            }
          });
        }

        list.appendChild(option);
      });

      if (!hasAvailableTarget){
        const empty = document.createElement('div');
        empty.className = 'move-file-empty';
        empty.textContent = 'Другие рубрики пока не созданы.';
        bodyWrap.appendChild(empty);
      }
    }

    const closeBtn = createActionButton('Закрыть');
    closeBtn.addEventListener('click', () => modal.close());
    modal.footer.appendChild(closeBtn);
  }

  function applyArchiveStateResponse(statePayload){
    const nextState = normalizeState(statePayload || { rubrics: [] });
    applyNormalizedState(nextState);
    syncSearchState(nextState, { reset: true });
    reconcileSelectedFiles();
    updateBulkSelectionUi();
    renderRubrics();
    requestSearchRefresh();
  }

  function openBulkMoveModal(){
    const selectedItems = getSelectedFileRefs().map((item) => ({
      file_id: item.fileId,
      source_rubric_id: item.rubricId,
    }));
    if (!selectedItems.length){
      setArchiveStatus('Сначала выберите хотя бы одну карточку.');
      return;
    }

    const modal = openModal({ title: 'Перенести выбранные файлы' });
    modal.body.innerHTML = '';
    modal.footer.innerHTML = '';

    const bodyWrap = document.createElement('div');
    bodyWrap.className = 'move-file-picker';
    modal.body.appendChild(bodyWrap);

    const hint = document.createElement('p');
    hint.className = 'move-file-picker__hint';
    hint.textContent = `Выбрано файлов: ${selectedItems.length}. Выберите рубрику назначения.`;
    bodyWrap.appendChild(hint);

    const errorEl = document.createElement('div');
    errorEl.className = 'form-error';
    bodyWrap.appendChild(errorEl);

    const rubrics = Array.isArray(state.rubrics) ? state.rubrics : [];
    if (!rubrics.length){
      const empty = document.createElement('div');
      empty.className = 'move-file-empty';
      empty.textContent = 'Рубрики пока не созданы.';
      bodyWrap.appendChild(empty);
    } else {
      const hasAvailableTarget = rubrics.some((rubricItem) => {
        const rubricId = rubricItem && rubricItem.id ? String(rubricItem.id) : '';
        return selectedItems.some((item) => item.source_rubric_id !== rubricId);
      });

      if (!hasAvailableTarget){
        const empty = document.createElement('div');
        empty.className = 'move-file-empty';
        empty.textContent = 'Другие рубрики пока не созданы.';
        bodyWrap.appendChild(empty);
      }

      const list = document.createElement('div');
      list.className = 'move-file-list';
      bodyWrap.appendChild(list);

      rubrics.forEach((rubricItem) => {
        const rubricId = rubricItem && rubricItem.id ? String(rubricItem.id) : '';
        const allAlreadyInside = selectedItems.every((item) => item.source_rubric_id === rubricId);

        const option = document.createElement('button');
        option.type = 'button';
        option.className = 'move-file-option';
        if (allAlreadyInside){
          option.classList.add('move-file-option--current');
          option.disabled = true;
        }

        const title = document.createElement('span');
        title.className = 'move-file-option__title';
        title.textContent = rubricItem && rubricItem.name ? rubricItem.name : 'Рубрика';

        const meta = document.createElement('span');
        meta.className = 'move-file-option__meta';
        meta.textContent = allAlreadyInside ? 'Все выбранные файлы уже находятся в этой рубрике' : 'Нажмите для переноса выбранных файлов';

        option.append(title, meta);

        if (!allAlreadyInside){
          option.addEventListener('click', async () => {
            const optionButtons = list.querySelectorAll('button');
            optionButtons.forEach((button) => { button.disabled = true; });
            errorEl.textContent = '';
            try {
              const responseData = await bulkMoveArchiveFilesRequest(selectedItems, rubricId);
              const movedCount = Number(responseData.processed_count) || 0;
              const errorCount = responseData && responseData.errors ? Object.keys(responseData.errors).length : 0;
              applyArchiveStateResponse(responseData.state);
              setArchiveStatus(errorCount > 0
                ? `Перенесено файлов: ${movedCount}. Не обработано: ${errorCount}.`
                : `Перенесено файлов: ${movedCount}.`);
              modal.close();
              if (activeRubricId !== ALL_RUBRICS_ID){
                activeRubricId = rubricId;
                renderRubrics();
              }
            } catch (error){
              optionButtons.forEach((button) => {
                if (!button.classList.contains('move-file-option--current')){
                  button.disabled = false;
                }
              });
              errorEl.textContent = error && error.message ? error.message : 'Не удалось перенести выбранные файлы.';
            }
          });
        }

        list.appendChild(option);
      });
    }

    const closeBtn = createActionButton('Закрыть');
    closeBtn.addEventListener('click', () => modal.close());
    modal.footer.appendChild(closeBtn);
  }

  function runBulkDelete(){
    const selectedItems = getSelectedFileRefs().map((item) => ({
      file_id: item.fileId,
      source_rubric_id: item.rubricId,
    }));
    if (!selectedItems.length){
      setArchiveStatus('Сначала выберите хотя бы одну карточку.');
      return;
    }

    openConfirmModal(`Удалить выбранные карточки (${selectedItems.length})?`, async () => {
      try {
        const responseData = await bulkDeleteArchiveFilesRequest(selectedItems);
        const deletedCount = Number(responseData.processed_count) || 0;
        const errorCount = responseData && responseData.errors ? Object.keys(responseData.errors).length : 0;
        applyArchiveStateResponse(responseData.state);
        setArchiveStatus(errorCount > 0
          ? `Удалено файлов: ${deletedCount}. Не обработано: ${errorCount}.`
          : `Удалено файлов: ${deletedCount}.`);
      } catch (error){
        setArchiveStatus(error && error.message ? error.message : 'Не удалось удалить выбранные файлы.');
      }
    });
  }

  function openFileViewModal(rubricId, fileId, options){
    if (!stateReady){
      pendingOpenFileDetail = { rubricId, fileId };
      return;
    }
    const viewOptions = options || {};
    const rubric = getRubric(rubricId);
    if (!rubric) return;
    const file = rubric.files.find((item) => item.id === fileId);
    if (!file) return;

    let modalTitle = getDisplayName(rubric, file) || 'Файл';
    let releaseSellMenuListener = null;
    let currentFormCleanup = null;

    function createHeroTitleElements(text){
      const container = document.createElement('div');
      container.className = 'file-view__hero-title';

      const textEl = document.createElement('span');
      textEl.className = 'file-view__hero-title-text';
      textEl.textContent = text;
      container.appendChild(textEl);

      const toggleBtn = document.createElement('button');
      toggleBtn.type = 'button';
      toggleBtn.className = 'file-view__hero-title-toggle';
      toggleBtn.setAttribute('aria-expanded', 'false');
      toggleBtn.setAttribute('aria-label', 'Развернуть название файла');
      toggleBtn.disabled = true;
      toggleBtn.setAttribute('aria-hidden', 'true');
      const iconSpan = document.createElement('span');
      iconSpan.setAttribute('aria-hidden', 'true');
      iconSpan.className = 'file-view__hero-title-toggle-icon';
      iconSpan.textContent = '⌄';
      toggleBtn.appendChild(iconSpan);
      container.appendChild(toggleBtn);

      return { container, textEl, toggleBtn, toggleIcon: iconSpan };
    }

    function setupHeroTitleOverflow(container, textEl, toggleBtn, toggleIcon){
      if (!container || !textEl){
        return null;
      }

      let expanded = false;
      let rafId = null;
      let resizeObserver = null;
      let fallbackTimer = null;

      function setExpanded(next){
        if (expanded === next){
          return;
        }
        expanded = next;
        container.classList.toggle('file-view__hero-title--expanded', expanded);
        if (toggleBtn){
          toggleBtn.setAttribute('aria-expanded', expanded ? 'true' : 'false');
          toggleBtn.setAttribute('aria-label', expanded ? 'Свернуть название файла' : 'Развернуть название файла');
        }
        if (toggleIcon){
          toggleIcon.textContent = expanded ? '⌃' : '⌄';
        }
      }

      function applyOverflowState(){
        rafId = null;
        if (!container.isConnected){
          return;
        }
        const needsToggle = textEl.scrollWidth > textEl.clientWidth + 1;
        container.classList.toggle('file-view__hero-title--truncated', needsToggle);
        if (toggleBtn){
          toggleBtn.disabled = !needsToggle;
          toggleBtn.setAttribute('aria-hidden', needsToggle ? 'false' : 'true');
          if (!needsToggle && document.activeElement === toggleBtn){
            toggleBtn.blur();
          }
        }
        if (!needsToggle){
          setExpanded(false);
        }
      }

      function scheduleOverflowCheck(){
        if (rafId){
          return;
        }
        rafId = requestAnimationFrame(applyOverflowState);
      }

      const onResize = () => scheduleOverflowCheck();
      window.addEventListener('resize', onResize);

      if (typeof ResizeObserver === 'function'){
        resizeObserver = new ResizeObserver(scheduleOverflowCheck);
        resizeObserver.observe(container);
        resizeObserver.observe(textEl);
      }

      scheduleOverflowCheck();
      fallbackTimer = setTimeout(scheduleOverflowCheck, 250);

      let onToggleClick = null;
      let onToggleKeyDown = null;

      if (toggleBtn){
        onToggleClick = (event) => {
          event.stopPropagation();
          if (container.classList.contains('file-view__hero-title--truncated')){
            setExpanded(!expanded);
          }
        };
        onToggleKeyDown = (event) => {
          if (event.key === 'Enter' || event.key === ' '){
            if (!container.classList.contains('file-view__hero-title--truncated')){
              return;
            }
            event.preventDefault();
            setExpanded(!expanded);
          }
        };
        toggleBtn.addEventListener('click', onToggleClick);
        toggleBtn.addEventListener('keydown', onToggleKeyDown);
      }

      return () => {
        if (rafId){
          cancelAnimationFrame(rafId);
          rafId = null;
        }
        window.removeEventListener('resize', onResize);
        if (resizeObserver){
          resizeObserver.disconnect();
          resizeObserver = null;
        }
        if (fallbackTimer){
          clearTimeout(fallbackTimer);
          fallbackTimer = null;
        }
        if (toggleBtn){
          toggleBtn.removeEventListener('click', onToggleClick);
          toggleBtn.removeEventListener('keydown', onToggleKeyDown);
        }
      };
    }

    function clearFormCleanup(){
      if (currentFormCleanup){
        try {
          currentFormCleanup();
        } catch (err) {}
        currentFormCleanup = null;
      }
    }
    const modal = openModal({
      title: modalTitle,
      hideTitle: true,
      closePlacement: 'footer',
      onClose: () => {
        if (releaseSellMenuListener){
          releaseSellMenuListener();
        }
        clearFormCleanup();
      }
    });

    const titleEl = modal.header ? modal.header.querySelector('.archive-modal__title') : null;

    function renderView(){
      clearFormCleanup();
      modal.body.innerHTML = '';
      modal.footer.innerHTML = '';
      modal.footer.classList.add('file-view__actions', 'archive-modal__footer--pinned');
      modal.footer.classList.remove('archive-modal__footer--single');

      if (releaseSellMenuListener){
        releaseSellMenuListener();
        releaseSellMenuListener = null;
      }
      const view = document.createElement('div');
      view.className = 'file-view';

      const imageField = rubric.mode === 'text' ? null : rubric.fields.find((field) => field.type === 'image');
      const photoValue = imageField ? getFieldValue(rubric, file, imageField) : null;
      const hasMedia = hasImageItems(photoValue);
      const primaryImage = hasMedia ? getPrimaryImage(photoValue) : null;
      const computedDisplayName = getDisplayName(rubric, file);
      const displayName = computedDisplayName || modalTitle;
      if (titleEl){
        titleEl.textContent = displayName;
      }
      modalTitle = displayName;

      let heroTitleElements = null;
      if (imageField){
        const hero = document.createElement('div');
        hero.className = 'file-view__hero';

        if (hasMedia && primaryImage){
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
          content.appendChild(inner);

          const frame = document.createElement('div');
          frame.className = 'file-view__frame';

          if (photoValue){
            const widthCandidate = Number(photoValue.frameWidth);
            const heightCandidate = Number(photoValue.frameHeight);
            const storedWidth = Number.isFinite(widthCandidate) && widthCandidate > 0 ? Math.round(widthCandidate) : null;
            const storedHeight = Number.isFinite(heightCandidate) && heightCandidate > 0 ? Math.round(heightCandidate) : null;

            if (storedWidth){
              const widthPx = `${storedWidth}px`;
              frame.style.width = widthPx;
              frame.style.maxWidth = '100%';
              frame.style.setProperty('--file-frame-width', widthPx);
            } else {
              frame.style.removeProperty('width');
              frame.style.removeProperty('--file-frame-width');
            }

            if (storedHeight){
              const heightPx = `${storedHeight}px`;
              frame.style.height = heightPx;
              frame.style.setProperty('--file-frame-height', heightPx);
              frame.dataset.fixedHeight = 'true';
            } else {
              frame.style.removeProperty('height');
              frame.style.removeProperty('--file-frame-height');
              delete frame.dataset.fixedHeight;
            }

            if (storedWidth && storedHeight){
              const ratio = storedWidth / storedHeight;
              if (Number.isFinite(ratio) && ratio > 0){
                frame.style.setProperty('--file-frame-aspect', ratio.toFixed(4));
                frame.style.setProperty('--file-frame-ratio', ratio.toFixed(4));
              }
            } else {
              frame.style.removeProperty('--file-frame-aspect');
              frame.style.removeProperty('--file-frame-ratio');
            }
          }

            const strip = document.createElement('div');
            const itemCount = photoValue ? photoValue.items.length : 0;
            let activeIndex = 0;
            const photoCounter = document.createElement('div');
            photoCounter.className = 'file-view__photo-counter';
            photoCounter.setAttribute('aria-live', 'polite');
            const updatePhotoCounter = (index) => {
              photoCounter.textContent = `${index + 1}/${itemCount}`;
            };
            strip.className = 'media-split';
            strip.style.setProperty('--media-split-count', Math.max(itemCount, 1));
            strip.dataset.safeTop = '0';
            strip.style.setProperty('--media-split-safe-top', '0px');
            if (photoValue && itemCount > 1){
              strip.classList.add('media-split--hoverable', 'media-split--multi', 'media-split--manual');
              strip.tabIndex = 0;
            }

            if (photoValue){
              let pinnedId = photoValue && photoValue.pinnedId ? String(photoValue.pinnedId) : null;
              if (pinnedId && !photoValue.items.some((candidate) => candidate && candidate.id === pinnedId)){
                pinnedId = null;
              }
              if (!pinnedId && photoValue.items.length){
                pinnedId = photoValue.items[0].id;
              }
              activeIndex = photoValue.items.findIndex((item) => item && item.id === pinnedId);
              if (activeIndex < 0){
                activeIndex = 0;
              }
              updatePhotoCounter(activeIndex);
              photoValue.items.forEach((item, index) => {
                const slice = document.createElement('div');
                slice.className = 'media-split__item';
                slice.dataset.index = String(index);
                if (itemCount > 1){
                  slice.tabIndex = 0;
                  slice.setAttribute('role', 'button');
                  slice.setAttribute('aria-label', `${imageField.label} ${index + 1}`);
                  const geometry = computeSplitGeometry(itemCount, index);
                  if (geometry){
                    slice.style.clipPath = geometry.clip;
                    slice.dataset.clipPath = geometry.clip;
                    slice.dataset.centroidX = geometry.centroid ? geometry.centroid[0].toFixed(6) : '0.5';
                    slice.dataset.centroidY = geometry.centroid ? geometry.centroid[1].toFixed(6) : '0.5';
                    if (geometry.centroid){
                      const offsetX = geometry.centroid[0] - 0.5;
                      slice.dataset.offsetX = offsetX.toFixed(6);
                    }
                  }
                }

                if (!slice.dataset.offsetX){
                  const fallbackOffsetX = ((index + 0.5) / Math.max(itemCount, 1)) - 0.5;
                  slice.dataset.offsetX = fallbackOffsetX.toFixed(6);
                }
                slice.dataset.offsetY = slice.dataset.offsetY || '0';

                if (pinnedId && item.id === pinnedId){
                  slice.classList.add('media-split__item--primary');
                }

                const backdrop = document.createElement('div');
                backdrop.className = 'media-split__backdrop';
                backdrop.style.backgroundImage = `url(${item.src})`;
                slice.appendChild(backdrop);

                const img = document.createElement('img');
                img.src = item.src;
                img.alt = itemCount > 1 ? `${imageField.label} ${index + 1}` : imageField.label;
                img.decoding = 'async';
                img.draggable = false;
                img.addEventListener('load', () => {
                  if (img.naturalWidth > 0 && img.naturalHeight > 0){
                    const ratio = img.naturalWidth / img.naturalHeight;
                    if (Number.isFinite(ratio) && ratio > 0){
                      slice.dataset.aspect = ratio.toFixed(4);
                      slice.dataset.orientation = ratio >= 1 ? 'landscape' : 'portrait';
                      if (index === activeIndex || !frame.style.getPropertyValue('--file-frame-aspect')){
                        frame.style.setProperty('--file-frame-aspect', ratio.toFixed(4));
                        frame.style.setProperty('--file-frame-ratio', ratio.toFixed(4));
                        frame.dataset.orientation = ratio >= 1 ? 'landscape' : 'portrait';
                      }
                    }
                  }
                });
                slice.appendChild(img);
                strip.appendChild(slice);
              });
              if (itemCount > 1){
                const prevBtn = document.createElement('button');
                prevBtn.type = 'button';
                prevBtn.className = 'media-split__nav media-split__nav--prev';
                prevBtn.setAttribute('aria-label', 'Предыдущее фото');

                const nextBtn = document.createElement('button');
                nextBtn.type = 'button';
                nextBtn.className = 'media-split__nav media-split__nav--next';
                nextBtn.setAttribute('aria-label', 'Следующее фото');

                const items = Array.from(strip.querySelectorAll('.media-split__item'));

                const updateFrameFromIndex = (index) => {
                  const target = items[index];
                  if (!target){
                    return;
                  }
                  const ratioValue = parseFloat(target.dataset.aspect || '');
                  if (Number.isFinite(ratioValue) && ratioValue > 0){
                    frame.style.setProperty('--file-frame-aspect', ratioValue.toFixed(4));
                    frame.style.setProperty('--file-frame-ratio', ratioValue.toFixed(4));
                    frame.dataset.orientation = ratioValue >= 1 ? 'landscape' : 'portrait';
                  }
                };

                const updateActive = (index) => {
                  const clamped = Math.min(Math.max(index, 0), items.length - 1);
                  activeIndex = clamped;
                  items.forEach((item, idx) => {
                    item.classList.toggle('media-split__item--active', idx === clamped);
                  });
                  prevBtn.disabled = clamped === 0;
                  nextBtn.disabled = clamped === items.length - 1;
                  updateFrameFromIndex(clamped);
                  updatePhotoCounter(clamped);
                };

                const stepActive = (delta) => {
                  updateActive(activeIndex + delta);
                };

                prevBtn.addEventListener('click', (event) => {
                  event.stopPropagation();
                  stepActive(-1);
                });
                nextBtn.addEventListener('click', (event) => {
                  event.stopPropagation();
                  stepActive(1);
                });

                strip.addEventListener('keydown', (event) => {
                  if (event.key === 'ArrowLeft'){
                    event.preventDefault();
                    stepActive(-1);
                  } else if (event.key === 'ArrowRight'){
                    event.preventDefault();
                    stepActive(1);
                  }
                });

                strip.append(prevBtn, nextBtn);
                updateActive(activeIndex);
              }
            }

          frame.appendChild(strip);
          if (itemCount > 0){
            frame.appendChild(photoCounter);
          }
          inner.appendChild(frame);

          if (displayName){
            heroTitleElements = createHeroTitleElements(displayName);
            inner.appendChild(heroTitleElements.container);
          }

          hero.appendChild(content);
        } else {
          hero.classList.add('file-view__hero--empty');
          const placeholder = document.createElement('div');
          placeholder.className = 'file-view__placeholder';
          placeholder.textContent = 'Фото не добавлено';
          hero.appendChild(placeholder);
        }

        if (!hasMedia && displayName){
          const nameBadge = document.createElement('div');
          nameBadge.className = 'file-view__hero-title';
          nameBadge.textContent = displayName;
          hero.insertBefore(nameBadge, hero.firstChild);
        }

        view.appendChild(hero);

      } else {
        view.classList.add('file-view--no-media');
        if (displayName){
          const textTitle = document.createElement('div');
          textTitle.className = 'file-view__text-title';
          textTitle.textContent = displayName;
          view.appendChild(textTitle);
        }
      }

      const infoWrap = document.createElement('div');
      infoWrap.className = 'file-view__info';
      const primaryWrap = document.createElement('div');
      primaryWrap.className = 'file-view__primary';
      const body = document.createElement('div');
      body.className = 'file-view__body';

      const primaryFieldIds = new Set();

      let hasPrimary = false;
      let hasBodyContent = true;

      const statusRow = document.createElement('div');
      statusRow.className = 'file-view__detail file-view__status';
      const statusLabel = document.createElement('span');
      statusLabel.className = 'file-view__label';
      statusLabel.textContent = 'Статус';
      statusRow.append(statusLabel, createStatusBadge(file.status, 'file-view__status-badge'));
      body.appendChild(statusRow);

      rubric.fields.forEach((field) => {
        if (field.type === 'image'){
          return;
        }
        if (field.id === 'title'){
          return;
        }

        const isDescription = field.id === 'description' || field.type === 'textarea';
        const row = document.createElement('div');
        row.className = isDescription ? 'file-view__description' : 'file-view__detail';
        row.dataset.field = field.id;

        const labelEl = document.createElement('span');
        labelEl.className = 'file-view__label';
        labelEl.textContent = field.label;
        const valueEl = document.createElement('span');
        valueEl.className = 'file-view__value';
        const value = getFieldValue(rubric, file, field);
        if (!value && getArchivePrefs().archiveEmptyFields === 'hide'){
          return;
        }
        renderPatternLinks(valueEl, value ? value : '', '—');
        row.append(labelEl, valueEl);

        if (primaryFieldIds.has(field.id)){
          row.classList.add('file-view__primary-item');
          primaryWrap.appendChild(row);
          hasPrimary = true;
        } else {
          body.appendChild(row);
          hasBodyContent = true;
        }
      });

      if (hasPrimary){
        infoWrap.appendChild(primaryWrap);
      }

      if (hasBodyContent){
        infoWrap.appendChild(body);
      } else if (!hasPrimary && !hasMedia){
        body.classList.add('file-view__body--solo');
        const emptyRow = document.createElement('div');
        emptyRow.className = 'file-view__empty';
        emptyRow.textContent = 'Нет данных для отображения.';
        body.appendChild(emptyRow);
        infoWrap.appendChild(body);
      }

      if (infoWrap.childNodes.length){
        view.appendChild(infoWrap);
      }

      modal.body.appendChild(view);
      modal.body.scrollTop = 0;

      // Show the auction status (and a link to the lot) for cards that already
      // have a lot, so the seller sees the outcome right inside the card.
      renderCardAuctionStatus(view, file);

      const viewCleanups = [];
      if (heroTitleElements){
        const cleanup = setupHeroTitleOverflow(
          heroTitleElements.container,
          heroTitleElements.textEl,
          heroTitleElements.toggleBtn,
          heroTitleElements.toggleIcon
        );
        if (typeof cleanup === 'function'){
          viewCleanups.push(cleanup);
        }
        heroTitleElements = null;
      }

      currentFormCleanup = () => {
        while (viewCleanups.length){
          const fn = viewCleanups.pop();
          try {
            fn();
          } catch (error) {}
        }
        currentFormCleanup = null;
      };

      const editBtn = createActionButton('Редактировать');
      editBtn.addEventListener('click', () => renderEdit());
      editBtn.classList.add('file-view__action');

      const actionNodes = [editBtn];

      // «В Маркет» is available to the card owner. The archive only ever shows
      // the signed-in user's own cards, so simply enabling it here keeps the
      // action owner-only; the server also enforces ownership on publish.
      const marketBtn = createActionButton('В Маркет');
      marketBtn.classList.add('file-view__action', 'file-view__market-cta');
      marketBtn.setAttribute('aria-haspopup', 'dialog');
      marketBtn.addEventListener('click', () => openAuctionForCard(rubric, file));
      actionNodes.push(marketBtn);

      const deleteBtn = createActionButton('Удалить', { variant: 'danger' });
      deleteBtn.addEventListener('click', () => {
        openConfirmModal('Вы точно хотите удалить данный файл?', () => {
          rubric.files = rubric.files.filter((item) => item.id !== file.id);
          persistAndRender();
          modal.close();
        });
      });
      const pdfBtn = createActionButton('Скачать PDF');
      pdfBtn.addEventListener('click', () => downloadFilePdf(rubric, file));

      pdfBtn.classList.add('file-view__action');
      deleteBtn.classList.add('file-view__action');

      const closeBtn = createActionButton('Закрыть');
      closeBtn.classList.add('file-view__action', 'file-view__action--end');
      closeBtn.addEventListener('click', () => modal.close());

      actionNodes.push(pdfBtn, deleteBtn, closeBtn);
      modal.footer.append(...actionNodes);
    }

    function renderEdit(){
      if (releaseSellMenuListener){
        releaseSellMenuListener();
        releaseSellMenuListener = null;
      }
      clearFormCleanup();
      const formContext = buildFileForm(rubric, file);
      const { container, collect, getStatus, setError, focusFirst } = formContext;
      currentFormCleanup = formContext && typeof formContext.cleanup === 'function' ? formContext.cleanup : null;
      modal.body.innerHTML = '';
      modal.body.appendChild(container);
      modal.footer.innerHTML = '';
      modal.footer.classList.add('file-view__actions', 'archive-modal__footer--pinned', 'archive-modal__footer--single');

      const moveBtn = createActionButton('Перенести');
      moveBtn.classList.add('file-view__action');
      moveBtn.addEventListener('click', () => {
        openMoveFileModal({
          rubricId: rubric.id,
          fileId: file.id,
          onMoved(targetRubricId, movedFileId){
            modal.close();
            requestAnimationFrame(() => {
              openFileViewModal(targetRubricId, movedFileId);
            });
          }
        });
      });

      const saveBtn = createActionButton('Сохранить');
      saveBtn.classList.add('file-view__action', 'file-view__action--end');
      saveBtn.addEventListener('click', () => {
        const values = collect();
        const mainField = rubric.fields.find((field) => field.id === 'title');
        if (mainField && !values[mainField.id]){
          setError(`Заполните поле «${mainField.label}».`);
          const target = modal.body.querySelector(`[data-field="${mainField.id}"]`);
          if (target) target.focus();
          return;
        }
        setError('');
        file.values = values;
        file.status = getStatus();
        file.updatedAt = Date.now();
        persistAndRender();
        renderView();
      });

      modal.footer.append(moveBtn, saveBtn);
      focusFirst();
    }

    if (viewOptions.edit){
      renderEdit();
    } else {
      renderView();
    }
  }

  function createActionButton(text, options){
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'side-btn';
    if (options && options.variant === 'danger'){
      btn.classList.add('danger');
    }
    btn.textContent = text;
    return btn;
  }

  function openConfirmModal(message, onConfirm){
    const modal = openModal({ title: 'Подтверждение', showClose: false, overlayClass: 'archive-modal-overlay--confirm' });
    modal.body.innerHTML = '';
    const text = document.createElement('p');
    text.textContent = message;
    modal.body.appendChild(text);
    modal.footer.innerHTML = '';

    const cancelBtn = createActionButton('Нет');
    cancelBtn.addEventListener('click', () => modal.close());
    const confirmBtn = createActionButton('Да', { variant: 'danger' });
    confirmBtn.addEventListener('click', () => {
      if (typeof onConfirm === 'function') onConfirm();
      modal.close();
    });

    modal.footer.append(cancelBtn, confirmBtn);
  }

  function wrapPdfParagraph(text, maxLength){
    const cleaned = text.trim().replace(/\s+/g, ' ');
    if (!cleaned){
      return [];
    }
    const result = [];
    let remaining = cleaned;
    while (remaining.length > maxLength){
      let splitIndex = remaining.lastIndexOf(' ', maxLength);
      if (splitIndex <= 0){
        splitIndex = maxLength;
      }
      result.push(remaining.slice(0, splitIndex));
      remaining = remaining.slice(splitIndex).replace(/^\s+/, '');
    }
    if (remaining.length){
      result.push(remaining);
    }
    return result;
  }

  function appendFieldLines(lines, label, value){
    const fieldLabel = label || 'Поле';
    if (value == null){
      lines.push(`${fieldLabel}: —`);
      return;
    }
    const raw = typeof value === 'string' ? value : String(value);
    const normalized = raw.replace(/\r\n/g, '\n').replace(/\r/g, '\n');
    const paragraphs = normalized.split('\n');
    let hasContent = false;
    paragraphs.forEach((paragraph) => {
      const wrapped = wrapPdfParagraph(paragraph, 80);
      if (!wrapped.length){
        return;
      }
      wrapped.forEach((line, index) => {
        if (!hasContent && index === 0){
          lines.push(`${fieldLabel}: ${line}`);
        } else {
          lines.push(`  ${line}`);
        }
      });
      hasContent = true;
    });
    if (!hasContent){
      lines.push(`${fieldLabel}: —`);
    }
  }

  function sanitizeFileName(name){
    return (name || 'file')
      .replace(/[\\/:*?"<>|]+/g, ' ')
      .trim()
      .replace(/\s+/g, '_') || 'file';
  }

  function base64ToUint8Array(base64){
    const cleaned = base64.replace(/\s+/g, '');
    const binary = atob(cleaned);
    const length = binary.length;
    const bytes = new Uint8Array(length);
    for (let i = 0; i < length; i += 1){
      bytes[i] = binary.charCodeAt(i);
    }
    return bytes;
  }

  function buildPdfFromCanvas(canvas, jpegBase64){
    const encoder = new TextEncoder();
    const parts = [];
    let length = 0;

    function pushPart(part){
      parts.push(part);
      length += part.length;
    }

    const header = encoder.encode('%PDF-1.4\n');
    pushPart(header);

    const objectOffsets = [0];

    function addObject(partList){
      objectOffsets.push(length);
      partList.forEach((chunk) => {
        pushPart(chunk);
      });
    }

    const imageBytes = base64ToUint8Array(jpegBase64);
    const widthPx = Math.max(1, Math.round(canvas.width));
    const heightPx = Math.max(1, Math.round(canvas.height));
    const pxToPt = 72 / 96;
    const widthPt = Math.max(1, Math.round(widthPx * pxToPt));
    const heightPt = Math.max(1, Math.round(heightPx * pxToPt));

    addObject([encoder.encode('1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n')]);
    addObject([encoder.encode('2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n')]);

    const page = `3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${widthPt} ${heightPt}] /Resources << /ProcSet [/PDF /ImageC] /XObject << /Im0 5 0 R >> >> /Contents 4 0 R >>\nendobj\n`;
    addObject([encoder.encode(page)]);

    const contentStream = `q\n${widthPt} 0 0 ${heightPt} 0 0 cm\n/Im0 Do\nQ\n`;
    const contentHeader = `4 0 obj\n<< /Length ${contentStream.length} >>\nstream\n`;
    addObject([
      encoder.encode(contentHeader),
      encoder.encode(contentStream),
      encoder.encode('endstream\nendobj\n')
    ]);

    const imageHeader = `5 0 obj\n<< /Type /XObject /Subtype /Image /Width ${widthPx} /Height ${heightPx} /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length ${imageBytes.length} >>\nstream\n`;
    addObject([
      encoder.encode(imageHeader),
      imageBytes,
      encoder.encode('\nendstream\nendobj\n')
    ]);

    const xrefOffset = length;
    const totalObjects = objectOffsets.length;
    let xref = `xref\n0 ${totalObjects}\n0000000000 65535 f \n`;
    for (let i = 1; i < totalObjects; i += 1){
      xref += `${String(objectOffsets[i]).padStart(10, '0')} 00000 n \n`;
    }
    xref += 'trailer\n';
    xref += `<< /Size ${totalObjects} /Root 1 0 R >>\n`;
    xref += 'startxref\n';
    xref += `${xrefOffset}\n`;
    xref += '%%EOF';

    pushPart(encoder.encode(xref));
    return new Blob(parts, { type: 'application/pdf' });
  }

  function drawPdfBackground(ctx, width, height){
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, width, height);
  }

  function drawPdfTitle(ctx, text, x, y){
    ctx.fillStyle = '#111111';
    ctx.font = '600 54px "Segoe UI", "DejaVu Sans", sans-serif';
    ctx.textBaseline = 'top';
    ctx.fillText(text, x, y);
  }

  function drawPdfLine(ctx, text, x, y, isIndented){
    ctx.fillStyle = '#1c1c1c';
    ctx.font = isIndented ? '400 32px "Segoe UI", "DejaVu Sans", sans-serif' : '600 34px "Segoe UI", "DejaVu Sans", sans-serif';
    ctx.textBaseline = 'top';
    ctx.fillText(text, x + (isIndented ? 32 : 0), y);
  }

  function measureAndDrawPdfCanvas(title, lines, images){
    const marginX = 90;
    const marginTop = 110;
    const marginBottom = 90;
    const canvasWidth = 1400;
    const contentWidth = canvasWidth - marginX * 2;
    const titleLineHeight = 70;
    const labelLineHeight = 50;
    const valueLineHeight = 46;
    const blankLineHeight = 30;
    const imageGap = 36;
    const imageAfterGap = 48;
    const afterTitleGap = 36;

    let requiredHeight = marginTop + titleLineHeight + afterTitleGap;
    const imageDrawData = images.map((img) => {
      const ratio = img.naturalWidth > 0 ? img.naturalHeight / img.naturalWidth : (img.height || 1) / (img.width || 1);
      const drawWidth = contentWidth;
      const drawHeight = Math.max(1, Math.round(drawWidth * ratio));
      requiredHeight += drawHeight + imageGap;
      return { element: img, width: drawWidth, height: drawHeight };
    });

    if (imageDrawData.length){
      requiredHeight -= imageGap;
      requiredHeight += imageAfterGap;
    }

    lines.forEach((line) => {
      if (!line){
        requiredHeight += blankLineHeight;
        return;
      }
      const indented = /^\s/.test(line);
      requiredHeight += indented ? valueLineHeight : labelLineHeight;
    });

    requiredHeight += marginBottom;

    const canvas = document.createElement('canvas');
    canvas.width = canvasWidth;
    canvas.height = Math.max(Math.ceil(requiredHeight), Math.floor(canvasWidth / 2));
    const ctx = canvas.getContext('2d');
    drawPdfBackground(ctx, canvas.width, canvas.height);

    let cursorY = marginTop;
    drawPdfTitle(ctx, title, marginX, cursorY);
    cursorY += titleLineHeight + afterTitleGap;

    imageDrawData.forEach((item, index) => {
      ctx.drawImage(item.element, marginX, cursorY, item.width, item.height);
      cursorY += item.height;
      cursorY += index === imageDrawData.length - 1 ? imageAfterGap : imageGap;
    });

    lines.forEach((line) => {
      if (!line){
        cursorY += blankLineHeight;
        return;
      }
      const indented = /^\s/.test(line);
      const text = line.trimStart();
      const lineHeight = indented ? valueLineHeight : labelLineHeight;
      drawPdfLine(ctx, text, marginX, cursorY, indented);
      cursorY += lineHeight;
    });

    return canvas;
  }

  function loadPdfImagesFromValue(imageValue){
    if (!imageValue || !Array.isArray(imageValue.items) || !imageValue.items.length){
      return Promise.resolve([]);
    }
    const promises = imageValue.items.map((item) => {
      const src = item && item.src ? item.src : null;
      if (!src){
        return Promise.resolve(null);
      }
      return new Promise((resolve) => {
        const img = new Image();
        img.onload = () => resolve(img);
        img.onerror = () => resolve(null);
        img.src = src;
      });
    });
    return Promise.all(promises).then((loaded) => loaded.filter(Boolean));
  }

  async function downloadFilePdf(rubric, file){
    try {
      const title = getDisplayName(rubric, file) || 'Файл';
      const lines = [];
      const textFields = rubric.fields.filter((field) => field.type !== 'image');
      textFields.forEach((field, index) => {
        const value = getFieldValue(rubric, file, field);
        appendFieldLines(lines, field.label, value);
        if (index !== textFields.length - 1){
          lines.push('');
        }
      });

      const imageField = rubric.fields.find((field) => field.type === 'image');
      const imageValue = imageField ? getFieldValue(rubric, file, imageField) : null;
      const images = await loadPdfImagesFromValue(imageValue);
      const canvas = measureAndDrawPdfCanvas(title, lines, images);
      const dataUrl = canvas.toDataURL('image/jpeg', 0.92);
      const base64 = dataUrl.split(',')[1];
      const blob = buildPdfFromCanvas(canvas, base64);
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `${sanitizeFileName(title)}.pdf`;
      document.body.appendChild(link);
      link.click();
      setTimeout(() => {
        URL.revokeObjectURL(url);
        link.remove();
      }, 0);
    } catch (error){
      console.error('Не удалось сформировать PDF', error);
    }
  }

  function openModal(config){
    const options = config || {};
    const overlay = document.createElement('div');
    overlay.className = 'archive-modal-overlay';
    if (options.overlayClass){
      overlay.classList.add(options.overlayClass);
    }

    const modal = document.createElement('div');
    modal.className = 'archive-modal';
    overlay.appendChild(modal);

    const header = document.createElement('div');
    header.className = 'archive-modal__header';
    if (options.headerClass){
      header.classList.add(options.headerClass);
    }
    const title = document.createElement('h2');
    title.className = 'archive-modal__title';
    title.textContent = options.title ? options.title : '';
    if (options.hideTitle){
      header.classList.add('archive-modal__header--no-title');
      title.classList.add('sr-only');
    }
    header.appendChild(title);
    const placeCloseInFooter = Boolean(options.closePlacement === 'footer');
    const allowHeaderClose = options.showClose !== false;
    let closeBtn = null;
    if (!placeCloseInFooter && allowHeaderClose){
      closeBtn = document.createElement('button');
      closeBtn.type = 'button';
      closeBtn.className = 'archive-modal__dismiss';
      closeBtn.textContent = 'Закрыть';
      header.appendChild(closeBtn);
    }
    if (placeCloseInFooter && header.classList.contains('archive-modal__header--no-title')){
      header.classList.add('archive-modal__header--hidden');
    }
    modal.appendChild(header);

    const body = document.createElement('div');
    body.className = 'archive-modal__body';
    modal.appendChild(body);

    const footer = document.createElement('div');
    footer.className = 'archive-modal__footer';
    modal.appendChild(footer);

    function close(){
      overlay.remove();
      if (!modalHost.querySelector('.archive-modal-overlay')){
        document.body.classList.remove('archive-modal-open');
      }
      if (typeof options.onClose === 'function'){
        options.onClose();
      }
    }

    if (closeBtn){
      closeBtn.addEventListener('click', close);
    }

    let overlayPointerDown = false;

    const markPointerStart = (event) => {
      overlayPointerDown = event.target === overlay;
    };

    const handlePointerEnd = (event) => {
      if (overlayPointerDown && event.target === overlay){
        close();
      }
      overlayPointerDown = false;
    };

    const cancelPointerTracking = () => {
      overlayPointerDown = false;
    };

    if (typeof window !== 'undefined' && 'PointerEvent' in window){
      overlay.addEventListener('pointerdown', markPointerStart);
      overlay.addEventListener('pointerup', handlePointerEnd);
      overlay.addEventListener('pointercancel', cancelPointerTracking);
    } else {
      overlay.addEventListener('mousedown', markPointerStart);
      overlay.addEventListener('mouseup', handlePointerEnd);
      overlay.addEventListener('mouseleave', cancelPointerTracking);
      overlay.addEventListener('touchstart', markPointerStart, { passive: true });
      overlay.addEventListener('touchend', handlePointerEnd);
      overlay.addEventListener('touchcancel', cancelPointerTracking);
    }

    document.body.classList.add('archive-modal-open');
    modalHost.appendChild(overlay);

    if (typeof options.content === 'function'){
      options.content(body, close);
    }
    if (typeof options.footer === 'function'){
      options.footer(footer, close);
    }

    return { close, body, footer, header, overlay };
  }

  createBtn.addEventListener('click', () => toggleCreateForm());
  if (rubricCreateShortcut){
    rubricCreateShortcut.addEventListener('click', () => toggleCreateForm(true));
  }
  if (archiveAddFile){
    archiveAddFile.addEventListener('click', openAddFileFlow);
  }
  archiveViewButtons.forEach((button) => {
    button.addEventListener('click', () => {
      const view = button.dataset.archiveView;
      if (view === 'cards' || view === 'list'){
        saveArchivePreference('archiveView', view);
      }
    });
  });
  if (archiveSortSelect){
    archiveSortSelect.addEventListener('change', () => {
      const sort = archiveSortSelect.value;
      if (['created', 'title', 'rubric', 'manual'].includes(sort)){
        saveArchivePreference('archiveSort', sort);
      }
    });
  }
  if (rubricScroll){
    rubricScroll.addEventListener('wheel', (event) => {
      if (Math.abs(event.deltaY) <= Math.abs(event.deltaX) || rubricScroll.scrollWidth <= rubricScroll.clientWidth){
        return;
      }
      rubricScroll.scrollLeft += event.deltaY;
      event.preventDefault();
    }, { passive: false });
  }
  nameSaveBtn.addEventListener('click', handleCreateRubric);
  if (archiveSelectionToggle){
    archiveSelectionToggle.addEventListener('click', () => {
      setArchiveStatus('');
      setSelectionMode(!selectionMode);
    });
  }
  if (archiveBulkSelectAll){
    archiveBulkSelectAll.addEventListener('click', () => {
      getVisibleFileRefs().forEach((item) => {
        selectedFileKeys.add(getFileSelectionKey(item.rubricId, item.fileId));
      });
      updateBulkSelectionUi();
      renderRubrics();
    });
  }
  if (archiveBulkClear){
    archiveBulkClear.addEventListener('click', () => {
      clearSelectedFiles();
      updateBulkSelectionUi();
      renderRubrics();
    });
  }
  if (archiveBulkMove){
    archiveBulkMove.addEventListener('click', () => {
      openBulkMoveModal();
    });
  }
  if (archiveBulkDelete){
    archiveBulkDelete.addEventListener('click', () => {
      runBulkDelete();
    });
  }
  if (archiveBulkClose){
    archiveBulkClose.addEventListener('click', () => {
      setSelectionMode(false);
    });
  }
  nameInput.addEventListener('keydown', (event) => {
    if (event.key === 'Enter'){
      event.preventDefault();
      handleCreateRubric();
    }
  });
  nameInput.addEventListener('input', () => {
    if (nameError.textContent){
      nameError.textContent = '';
    }
  });

  window.addEventListener('resize', scheduleSidebarMeasure, { passive: true });

  function openFileFromSearch(rubricId, fileId){
    if (!rubricId || !fileId) return;
    if (!stateReady){
      pendingOpenFileDetail = { rubricId, fileId };
      return;
    }
    const rubric = getRubric(rubricId);
    if (!rubric) return;
    requestSearchHide();
    if (activeRubricId !== rubricId){
      suppressSearchRefresh = true;
      try {
        activeRubricId = rubricId;
        renderRubrics();
      } finally {
        suppressSearchRefresh = false;
      }
    }
    if (window.history && typeof window.history.replaceState === 'function'){
      try {
        const url = new URL(window.location.href);
        url.searchParams.set('rubric', rubricId);
        url.searchParams.set('file', fileId);
        window.history.replaceState({}, document.title, url.toString());
      } catch (err) {}
    }
    requestAnimationFrame(() => {
      openFileViewModal(rubricId, fileId);
    });
  }

  function readOpenDetailFromUrl(){
    try {
      const params = new URLSearchParams(window.location.search || '');
      const rubricId = params.get('rubric');
      const fileId = params.get('file');
      if (rubricId && fileId){
        return { rubricId, fileId };
      }
    } catch (err) {}
    return null;
  }

  function consumePendingOpenFile(){
    let payload = null;
    try {
      const raw = sessionStorage.getItem(OPEN_FILE_SESSION_KEY);
      if (raw){
        sessionStorage.removeItem(OPEN_FILE_SESSION_KEY);
        payload = JSON.parse(raw);
      }
    } catch (e) {
      try {
        sessionStorage.removeItem(OPEN_FILE_SESSION_KEY);
      } catch (clearErr) {}
    }
    if (!payload){
      payload = readOpenDetailFromUrl();
    }
    if (payload && payload.rubricId && payload.fileId){
      if (!stateReady){
        pendingOpenFileDetail = { rubricId: payload.rubricId, fileId: payload.fileId };
        return;
      }
      openFileFromSearch(payload.rubricId, payload.fileId);
    }
  }

  const AUCTION_CONDITION_OPTIONS = [
    { value: '', label: 'Не указано' },
    { value: 'Новый', label: 'Новый' },
    { value: 'Отличное', label: 'Отличное' },
    { value: 'Хорошее', label: 'Хорошее' },
    { value: 'Удовлетворительное', label: 'Удовлетворительное' },
    { value: 'Требует восстановления', label: 'Требует восстановления' },
  ];
  const AUCTION_HANDOVER_OPTIONS = [
    { value: '', label: 'Не указано' },
    { value: 'Доставка', label: 'Доставка' },
    { value: 'Самовывоз', label: 'Самовывоз' },
    { value: 'По договорённости', label: 'По договорённости' },
  ];
  const AUCTION_START_OPTIONS = [
    { value: 'now', label: 'Сразу после публикации' },
    { value: 'scheduled', label: 'Запланировать' },
  ];
  const AUCTION_DURATION_OPTIONS = [
    { value: '1', label: '1 день' },
    { value: '3', label: '3 дня' },
    { value: '5', label: '5 дней' },
    { value: '7', label: '7 дней' },
    { value: '14', label: '14 дней' },
    { value: 'custom', label: 'Своя дата окончания' },
  ];

  // --- Market auction draft API (Task 2) -----------------------------------
  function marketRequest(url, method, payload){
    const options = { method: method, headers: { 'X-CSRFToken': getCsrfToken() }, credentials: 'include' };
    if (payload !== undefined){
      options.headers['Content-Type'] = 'application/json';
      options.body = JSON.stringify(payload);
    }
    return fetch(url, options).then((response) =>
      response.json().catch(() => null).then((data) => ({
        ok: response.ok && data && data.ok,
        status: response.status,
        data: data || {},
      })));
  }

  // Status is resolved by the archive SPA card id (no ArchiveFile.pk exists
  // until the card is materialised on the server).
  const cardStatusUrl = (id) => '/market/api/auction/card-status/?card_id=' + encodeURIComponent(id);
  const draftCreateUrl = '/market/api/auction/draft/';
  const draftUrl = (id) => '/market/api/auction/draft/' + encodeURIComponent(id) + '/';
  const draftPublishUrl = (id) => '/market/api/auction/draft/' + encodeURIComponent(id) + '/publish/';

  function buildLotAbsoluteUrl(path){
    try { return new URL(path, window.location.origin).href; }
    catch (e) { return path; }
  }

  function shareLot(path){
    const url = buildLotAbsoluteUrl(path);
    if (navigator.share){ navigator.share({ url }).catch(() => {}); return; }
    if (navigator.clipboard && navigator.clipboard.writeText){
      navigator.clipboard.writeText(url).then(() => setArchiveStatus('Ссылка на лот скопирована')).catch(() => window.prompt('Ссылка на лот:', url));
      return;
    }
    window.prompt('Ссылка на лот:', url);
  }

  // Read-only auction status banner inside the open card; also relabels the
  // «В Маркет» action to «На аукционе» and shows the lifecycle status.
  function renderCardAuctionStatus(view, file){
    if (!view || !file || !file.id) return;
    const existing = view.querySelector(':scope > .file-view__auction-status');
    if (existing) existing.remove();
    marketRequest(cardStatusUrl(file.id), 'GET').then(({ data }) => {
      if (!data || !data.has_lot) return;
      const cta = modalHost.querySelector('.file-view__market-cta');
      if (cta) cta.textContent = 'На аукционе';

      const banner = document.createElement('div');
      banner.className = 'file-view__auction-status auction-status--' + (data.status || '');
      const label = document.createElement('span');
      label.className = 'file-view__auction-status-label';
      label.textContent = 'Аукцион: ' + (data.status_label || '');
      banner.appendChild(label);
      if (data.listing_url && !data.is_draft){
        const link = document.createElement('a');
        link.className = 'file-view__auction-link';
        link.href = data.listing_url;
        link.textContent = 'Перейти к лоту';
        banner.appendChild(link);
      }
      view.insertBefore(banner, view.firstChild);
    });
  }

  function refreshOpenCardAuctionStatus(file){
    const view = modalHost.querySelector('.file-view');
    if (view) renderCardAuctionStatus(view, file);
  }

  // Build the card payload the server materialises into a real ArchiveFile.
  function buildAuctionCardPayload(rubric, file){
    const imageField = rubric && rubric.mode !== 'text' && Array.isArray(rubric.fields)
      ? rubric.fields.find((f) => f.type === 'image') : null;
    const photoValue = imageField ? getFieldValue(rubric, file, imageField) : null;
    const images = (photoValue && Array.isArray(photoValue.items))
      ? photoValue.items.filter((it) => it && it.src).map((it) => ({ src: it.src })) : [];
    return {
      card_id: String(file.id),
      title: getDisplayName(rubric, file) || cardValue(file, 'title') || 'Лот',
      description: cardValue(file, 'description'),
      rubric: rubric ? (rubric.name || '') : '',
      images: images,
    };
  }

  // Entry point for «В Маркет» / «На аукционе». Sends the card to the draft API
  // (which materialises a real ArchiveFile), then opens the wizard, the
  // existing draft, or the "already listed" notice. Errors stay in a modal —
  // never a page banner — and the archive card view stays open meanwhile.
  function openAuctionForCard(rubric, file){
    if (!file || !file.id) return;
    const card = buildAuctionCardPayload(rubric, file);
    marketRequest(draftCreateUrl, 'POST', { card: card }).then(({ ok, status, data }) => {
      if (!ok){
        if (window.console) console.error('Auction draft create failed', status, data);
        openAuctionErrorModal(firstApiError(data) || 'Не удалось открыть аукцион.');
        return;
      }
      // A live (scheduled/active/completed) lot already exists for this card.
      if (data.status && data.status !== 'draft' && data.status !== 'cancelled'){
        openAlreadyListedModal({ status_label: data.status_label || data.status, url: data.published_url || data.listing_url });
        return;
      }
      marketRequest(draftUrl(data.listing_id), 'GET').then(({ ok: ok2, data: detail }) => {
        if (!ok2){ openAuctionErrorModal('Не удалось загрузить настройку лота.'); return; }
        openAuctionWizard(file, detail);
      });
    }).catch(() => openAuctionErrorModal('Сетевая ошибка. Попробуйте ещё раз.'));
  }

  function openAuctionErrorModal(message){
    const modal = openModal({ title: 'Не удалось открыть аукцион', overlayClass: 'lot-status-overlay' });
    const text = document.createElement('p');
    text.className = 'lot-status__text';
    text.textContent = message;
    modal.body.appendChild(text);
    const close = createActionButton('Закрыть');
    close.addEventListener('click', () => modal.close());
    modal.footer.append(close);
  }

  function firstApiError(data){
    if (!data || !data.errors) return '';
    const value = Object.values(data.errors)[0];
    return Array.isArray(value) ? value.join(' ') : String(value || '');
  }

  // «Этот предмет уже размещён на аукционе» + «Перейти к лоту».
  function openAlreadyListedModal(info){
    const modal = openModal({ title: 'Предмет уже на аукционе', overlayClass: 'lot-status-overlay' });
    const wrap = document.createElement('div');
    wrap.className = 'lot-status';
    const text = document.createElement('p');
    text.className = 'lot-status__text';
    text.textContent = 'Этот предмет уже размещён на аукционе'
      + (info.status_label ? ' (' + info.status_label + ')' : '') + '.';
    wrap.appendChild(text);
    modal.body.appendChild(wrap);

    const open = createActionButton('Перейти к лоту');
    open.classList.add('lot-config__publish');
    open.addEventListener('click', () => { if (info.url) window.location.href = info.url; });
    const close = createActionButton('Закрыть');
    close.addEventListener('click', () => modal.close());
    modal.footer.append(open, close);
  }

  function openAuctionToast(message, success){
    setArchiveStatus(message);
    if (success && window.console) { /* noop hook */ }
  }

  // Clear post-publish confirmation. Replaces an abrupt page redirect: the
  // wizard is already closed, so this shows an understandable success notice
  // with an explicit link to the live lot (no surprise navigation).
  function openPublishSuccessModal(redirect){
    setArchiveStatus('Лот опубликован');
    const modal = openModal({ title: 'Аукцион опубликован', overlayClass: 'lot-status-overlay' });
    const wrap = document.createElement('div');
    wrap.className = 'lot-status';
    const text = document.createElement('p');
    text.className = 'lot-status__text';
    text.textContent = 'Лот опубликован и виден в Маркете.';
    wrap.appendChild(text);
    modal.body.appendChild(wrap);
    if (redirect){
      const go = createActionButton('Перейти к лоту');
      go.classList.add('lot-config__publish');
      go.addEventListener('click', () => { window.location.href = redirect; });
      modal.footer.append(go);
    }
    const close = createActionButton('Закрыть');
    close.addEventListener('click', () => modal.close());
    modal.footer.append(close);
  }

  function cardValue(file, id){
    if (!file || !file.values) return '';
    const value = file.values[id];
    return typeof value === 'string' ? value : '';
  }

  function toDatetimeLocal(date){
    const pad = (n) => String(n).padStart(2, '0');
    return date.getFullYear() + '-' + pad(date.getMonth() + 1) + '-' + pad(date.getDate())
      + 'T' + pad(date.getHours()) + ':' + pad(date.getMinutes());
  }

  function isoToDatetimeLocal(iso){
    if (!iso) return '';
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? '' : toDatetimeLocal(d);
  }

  function lotField(labelText, control){
    const label = document.createElement('label');
    label.className = 'lot-config__field';
    const span = document.createElement('span');
    span.textContent = labelText;
    label.append(span, control);
    return label;
  }

  function lotSelect(options, value){
    const select = document.createElement('select');
    select.setAttribute('data-theme-select', '');
    options.forEach((opt) => {
      const node = document.createElement('option');
      node.value = opt.value;
      node.textContent = opt.label;
      if (opt.value === value) node.selected = true;
      select.appendChild(node);
    });
    // NB: do NOT enhance here — the <select> is still detached. Enhancement is
    // applied with ThemeSelect.enhanceAll() once the modal body is in the DOM.
    return select;
  }

  function postLotRequest(url, payload){
    return fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
      credentials: 'include',
      body: JSON.stringify(payload),
    }).then((response) => response.json().catch(() => null).then((data) => ({ ok: response.ok && data && data.success, data: data || {} })));
  }

  function firstLotError(data){
    if (!data || !data.errors) return 'Не удалось сохранить лот.';
    return Object.keys(data.errors).map((key) => {
      const value = data.errors[key];
      return Array.isArray(value) ? value.join(' ') : String(value);
    }).join('\n') || 'Не удалось сохранить лот.';
  }

  const AUCTION_DAY_MS = 24 * 60 * 60 * 1000;

  // Build one labelled field with an inline error slot. Errors clear on edit.
  function lotConfigField(labelText, control, options){
    options = options || {};
    const wrap = document.createElement('div');
    wrap.className = 'lot-config__field';
    if (options.full) wrap.classList.add('lot-config__field--full');
    const label = document.createElement('label');
    label.className = 'lot-config__label';
    const span = document.createElement('span');
    span.textContent = labelText;
    label.appendChild(span);
    label.appendChild(control);
    wrap.appendChild(label);
    if (options.hint){
      const hint = document.createElement('small');
      hint.className = 'lot-config__hint';
      hint.textContent = options.hint;
      wrap.appendChild(hint);
    }
    const error = document.createElement('p');
    error.className = 'lot-config__error';
    error.setAttribute('role', 'alert');
    wrap.appendChild(error);
    control.lotErrorEl = error;
    const clear = () => { error.textContent = ''; };
    control.addEventListener('input', clear);
    control.addEventListener('change', clear);
    return wrap;
  }

  function numberInput(value){
    const input = document.createElement('input');
    input.type = 'number'; input.step = '0.01'; input.min = '0';
    if (value !== undefined && value !== null && value !== '') input.value = value;
    return input;
  }

  // ====================== Auction setup wizard ============================
  function awDebounce(fn, ms){
    let timer = null;
    return function(){
      const args = arguments, ctx = this;
      if (timer) clearTimeout(timer);
      timer = setTimeout(() => { timer = null; fn.apply(ctx, args); }, ms);
    };
  }

  const AW_DURATION_OPTIONS = [
    { value: '1', label: '1 день' }, { value: '3', label: '3 дня' }, { value: '5', label: '5 дней' },
    { value: '7', label: '7 дней' }, { value: '14', label: '14 дней' }, { value: 'custom', label: 'Выбрать дату' },
  ];
  const AW_DURATION_MINUTES = { '1': 1440, '3': 4320, '5': 7200, '7': 10080, '14': 20160 };
  const AW_MONTHS = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'];

  function awFormatDateTime(date){
    if (!date || Number.isNaN(date.getTime())) return '';
    const pad = (n) => String(n).padStart(2, '0');
    return date.getDate() + ' ' + AW_MONTHS[date.getMonth()] + ' в ' + pad(date.getHours()) + ':' + pad(date.getMinutes());
  }

  function awSuggestStep(price){
    const value = parseFloat(price);
    if (!(value > 0)) return null;
    if (value < 1000) return 50;
    if (value < 5000) return 100;
    if (value < 20000) return 500;
    return 1000;
  }

  function awDeriveDuration(detail){
    const map = { 1440: '1', 4320: '3', 7200: '5', 10080: '7', 20160: '14' };
    if (detail.auction_duration_minutes && map[detail.auction_duration_minutes]) return map[detail.auction_duration_minutes];
    if (detail.auction_end) return 'custom';
    return '7';
  }

  function awText(value){ const i = document.createElement('input'); i.type = 'text'; i.value = value || ''; return i; }
  function awNumber(value){ const i = document.createElement('input'); i.type = 'number'; i.step = '0.01'; i.min = '0'; if (value !== '' && value != null) i.value = value; return i; }
  function awTextarea(value){ const t = document.createElement('textarea'); t.rows = 3; t.value = value || ''; return t; }

  function awField(labelText, control, opts){
    opts = opts || {};
    const wrap = document.createElement('div');
    wrap.className = 'aw-field' + (opts.full ? ' aw-field--full' : '');
    if (labelText){
      const lab = document.createElement('label');
      lab.className = 'aw-field__label';
      const span = document.createElement('span');
      span.textContent = labelText;
      lab.append(span, control);
      wrap.appendChild(lab);
    } else {
      wrap.appendChild(control);
    }
    if (opts.hint){
      const hint = document.createElement('small');
      hint.className = 'aw-field__hint';
      hint.textContent = opts.hint;
      wrap.appendChild(hint);
    }
    const error = document.createElement('p');
    error.className = 'aw-field__error';
    error.setAttribute('role', 'alert');
    wrap.appendChild(error);
    control.awError = error;
    const clear = () => { error.textContent = ''; };
    control.addEventListener('input', clear);
    control.addEventListener('change', clear);
    return wrap;
  }

  // Main wizard: a single large modal with four steps, autosave and publish.
  function openAuctionWizard(file, detail){
    const labelOf = (list, value) => {
      const found = (list || []).find((o) => o.value === value);
      return found ? found.label : value;
    };
    const options = detail.options || {};

    const m = {
      listing_id: detail.listing_id,
      title: detail.title || '',
      description: detail.description || '',
      category: detail.category || '',
      condition: detail.condition || '',
      location: detail.location || '',
      delivery_methods: Array.isArray(detail.delivery_methods) ? detail.delivery_methods.slice() : [],
      delivery_cost: detail.delivery_cost || '',
      delivery_note: detail.delivery_note || '',
      start_mode: detail.auction_start_mode || 'now',
      start_at: isoToDatetimeLocal(detail.auction_start),
      duration: awDeriveDuration(detail),
      end_at: isoToDatetimeLocal(detail.auction_end),
      start_price: detail.auction_start_price || '',
      step: detail.auction_step || '',
      reserve: detail.auction_reserve_price || '',
      auto_extend: detail.auction_auto_extend !== false,
      images: Array.isArray(detail.images) ? detail.images.slice() : [],
      cover_image_id: detail.cover_image_id,
      stepEdited: false,
    };

    const STEPS = [
      { key: 'lot', label: 'Лот' },
      { key: 'price', label: 'Цена и срок' },
      { key: 'delivery', label: 'Получение' },
      { key: 'review', label: 'Проверка' },
    ];
    let currentStep = 0;
    let dirty = false;
    let publishing = false;
    const controls = {}; // field key -> { control, step }

    const modal = openModal({ title: 'Создание аукционного лота', overlayClass: 'auction-wizard-overlay', showClose: false });
    modal.overlay.classList.add('archive-modal-overlay--auction-wizard');

    // --- Header: subtitle, stepper, close -----------------------------------
    const subtitle = document.createElement('div');
    subtitle.className = 'aw-subtitle';
    subtitle.textContent = m.title || 'Аукционный лот';
    const stepper = document.createElement('div');
    stepper.className = 'aw-stepper';
    const stepDots = STEPS.map((s, i) => {
      const dot = document.createElement('button');
      dot.type = 'button';
      dot.className = 'aw-stepper__item';
      dot.innerHTML = '<span class="aw-stepper__num">' + (i + 1) + '</span><span class="aw-stepper__label">' + s.label + '</span>';
      dot.addEventListener('click', () => { if (i <= currentStep || m.stepEdited) goToStep(i); });
      stepper.appendChild(dot);
      return dot;
    });
    const closeBtn = document.createElement('button');
    closeBtn.type = 'button';
    closeBtn.className = 'archive-modal__dismiss aw-close';
    closeBtn.textContent = 'Закрыть';
    closeBtn.addEventListener('click', requestClose);
    modal.header.append(subtitle, stepper, closeBtn);

    // --- Body: form (left) + live preview (right) ---------------------------
    const layout = document.createElement('div');
    layout.className = 'aw';
    const main = document.createElement('div');
    main.className = 'aw__main';
    const stepHost = document.createElement('div');
    stepHost.className = 'aw__step';
    main.appendChild(stepHost);
    const previewWrap = document.createElement('aside');
    previewWrap.className = 'aw__preview';
    const preview = document.createElement('div');
    preview.className = 'aw-preview';
    previewWrap.appendChild(preview);
    layout.append(main, previewWrap);
    modal.body.appendChild(layout);

    // --- Footer: save status + navigation -----------------------------------
    const saveStatus = document.createElement('span');
    saveStatus.className = 'aw-savestatus';
    const previewToggle = createActionButton('Предпросмотр');
    previewToggle.classList.add('aw-preview-toggle');
    previewToggle.addEventListener('click', () => layout.classList.toggle('aw--preview-open'));
    const backBtn = createActionButton('Назад');
    backBtn.addEventListener('click', () => goToStep(currentStep - 1));
    const saveCloseBtn = createActionButton('Сохранить и закрыть');
    saveCloseBtn.addEventListener('click', () => saveScalars().then(() => modal.close()));
    const nextBtn = createActionButton('Продолжить');
    nextBtn.classList.add('lot-config__publish');
    nextBtn.addEventListener('click', onNext);
    modal.footer.append(saveStatus, previewToggle, backBtn, saveCloseBtn, nextBtn);

    function setSaveStatus(state){
      saveStatus.classList.remove('is-saving', 'is-saved', 'is-error');
      if (state === 'saving'){ saveStatus.textContent = 'Сохранение…'; saveStatus.classList.add('is-saving'); }
      else if (state === 'saved'){ saveStatus.textContent = 'Черновик сохранён'; saveStatus.classList.add('is-saved'); }
      else if (state === 'error'){ saveStatus.textContent = 'Не удалось сохранить'; saveStatus.classList.add('is-error'); }
      else { saveStatus.textContent = ''; }
    }

    // --- Saving --------------------------------------------------------------
    function scalarPayload(){
      const payload = {
        title: m.title, description: m.description, category: m.category, condition: m.condition,
        location: m.location, delivery_methods: m.delivery_methods, delivery_note: m.delivery_note,
        auction_start_mode: m.start_mode, auction_auto_extend: m.auto_extend,
        delivery_cost: m.delivery_cost === '' ? null : m.delivery_cost,
        auction_start_price: m.start_price === '' ? null : m.start_price,
        auction_step: m.step === '' ? null : m.step,
        auction_reserve_price: m.reserve === '' ? null : m.reserve,
        auction_start: (m.start_mode === 'scheduled' && m.start_at) ? m.start_at : null,
      };
      if (m.duration === 'custom'){
        payload.auction_duration_minutes = null;
        payload.auction_end = m.end_at || null;
      } else {
        payload.auction_duration_minutes = AW_DURATION_MINUTES[m.duration] || 10080;
        payload.auction_end = null;
      }
      return payload;
    }

    function distributeErrors(errors){
      let general = '';
      Object.keys(errors || {}).forEach((key) => {
        const message = Array.isArray(errors[key]) ? errors[key].join(' ') : String(errors[key]);
        const entry = controls[key];
        if (entry && entry.control.awError){ entry.control.awError.textContent = message; }
        else { general = general ? general + '\n' + message : message; }
      });
      return general;
    }

    function saveScalars(){
      setSaveStatus('saving');
      return marketRequest(draftUrl(m.listing_id), 'PATCH', scalarPayload()).then(({ ok, data }) => {
        if (ok){ dirty = false; setSaveStatus('saved'); }
        else { setSaveStatus('error'); distributeErrors(data && data.errors); }
        return ok;
      }).catch(() => { setSaveStatus('error'); return false; });
    }

    const scheduleSave = awDebounce(() => { saveScalars(); }, 700);
    function markDirty(){ dirty = true; updatePreview(); scheduleSave(); }

    function saveImages(extra){
      setSaveStatus('saving');
      return marketRequest(draftUrl(m.listing_id), 'PATCH', extra).then(({ ok, data }) => {
        if (ok){
          if (Array.isArray(data.images)) m.images = data.images;
          if ('cover_image_id' in data) m.cover_image_id = data.cover_image_id;
          setSaveStatus('saved');
          renderPhotos();
          updatePreview();
        } else { setSaveStatus('error'); }
        return ok;
      }).catch(() => { setSaveStatus('error'); return false; });
    }

    // --- Photos (thumbnails, cover, drag reorder, exclude) -------------------
    const photoHost = document.createElement('div');
    photoHost.className = 'aw-photos';
    let dragIndex = null;

    function renderPhotos(){
      photoHost.innerHTML = '';
      m.images.forEach((image, index) => {
        const thumb = document.createElement('div');
        thumb.className = 'aw-photo' + (image.is_cover ? ' aw-photo--cover' : '');
        thumb.draggable = true;
        const img = document.createElement('img');
        img.src = image.url; img.alt = '';
        thumb.appendChild(img);
        if (image.is_cover){
          const badge = document.createElement('span');
          badge.className = 'aw-photo__badge';
          badge.textContent = 'Обложка';
          thumb.appendChild(badge);
        }
        const tools = document.createElement('div');
        tools.className = 'aw-photo__tools';
        if (!image.is_cover){
          const cover = document.createElement('button');
          cover.type = 'button'; cover.className = 'aw-photo__btn'; cover.textContent = 'Обложка';
          cover.title = 'Сделать обложкой';
          cover.addEventListener('click', () => saveImages({ cover_image_id: image.id }));
          tools.appendChild(cover);
        }
        const remove = document.createElement('button');
        remove.type = 'button'; remove.className = 'aw-photo__btn aw-photo__btn--danger'; remove.textContent = '✕';
        remove.title = 'Убрать из аукциона';
        remove.disabled = m.images.length <= 1;
        remove.addEventListener('click', () => {
          if (m.images.length <= 1) return;
          saveImages({ excluded_image_ids: [image.id] });
        });
        tools.appendChild(remove);
        thumb.appendChild(tools);

        thumb.addEventListener('dragstart', () => { dragIndex = index; thumb.classList.add('is-dragging'); });
        thumb.addEventListener('dragend', () => { dragIndex = null; thumb.classList.remove('is-dragging'); });
        thumb.addEventListener('dragover', (e) => { e.preventDefault(); });
        thumb.addEventListener('drop', (e) => {
          e.preventDefault();
          if (dragIndex === null || dragIndex === index) return;
          const moved = m.images.splice(dragIndex, 1)[0];
          m.images.splice(index, 0, moved);
          renderPhotos();
          saveImages({ image_order: m.images.map((i) => i.id) });
        });
        photoHost.appendChild(thumb);
      });
      if (!m.images.length){
        const empty = document.createElement('p');
        empty.className = 'aw-photos__empty';
        empty.textContent = 'Нет фотографий. Добавьте фото в карточку архива.';
        photoHost.appendChild(empty);
      }
    }

    // --- Steps ---------------------------------------------------------------
    function register(key, control, stepIndex){ control.awStep = stepIndex; controls[key] = { control: control, step: stepIndex }; return control; }

    function buildStepLot(){
      const frag = document.createElement('div');
      frag.className = 'aw-grid';
      renderPhotos();
      const photosField = awField('Фотографии', photoHost, { full: true });
      const titleInput = awText(m.title);
      titleInput.addEventListener('input', () => { m.title = titleInput.value; markDirty(); });
      const descInput = awTextarea(m.description);
      descInput.addEventListener('input', () => { m.description = descInput.value; markDirty(); });
      const categorySelect = lotSelect([{ value: '', label: 'Выберите категорию' }].concat(options.category || []), m.category);
      categorySelect.addEventListener('change', () => { m.category = categorySelect.value; markDirty(); });
      const conditionSelect = lotSelect([{ value: '', label: 'Не указано' }].concat(options.condition || []), m.condition);
      conditionSelect.addEventListener('change', () => { m.condition = conditionSelect.value; markDirty(); });

      register('title', titleInput, 0);
      register('category', categorySelect, 0);
      register('condition', conditionSelect, 0);
      register('images', titleInput, 0); // image errors surface near the top
      register('cover_image_id', titleInput, 0);

      frag.append(
        photosField,
        awField('Название лота', titleInput, { full: true }),
        awField('Описание', descInput, { full: true }),
        awField('Категория', categorySelect),
        awField('Состояние предмета', conditionSelect),
      );
      return frag;
    }

    function buildStepPrice(){
      const frag = document.createElement('div');
      frag.className = 'aw-grid';

      // Start
      const startGroup = document.createElement('div');
      startGroup.className = 'aw-toggle';
      ['now', 'scheduled'].forEach((mode) => {
        const opt = labelOf(options.start_mode || [{ value: 'now', label: 'Начать сразу' }, { value: 'scheduled', label: 'Запланировать' }], mode);
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'aw-toggle__btn' + (m.start_mode === mode ? ' is-active' : '');
        btn.textContent = mode === 'now' ? 'Начать сразу' : 'Запланировать';
        btn.addEventListener('click', () => {
          m.start_mode = mode;
          startGroup.querySelectorAll('.aw-toggle__btn').forEach((b) => b.classList.remove('is-active'));
          btn.classList.add('is-active');
          startAtField.style.display = mode === 'scheduled' ? '' : 'none';
          markDirty(); updateEndText();
        });
        startGroup.appendChild(btn);
      });
      const startAtInput = document.createElement('input');
      startAtInput.type = 'datetime-local'; startAtInput.value = m.start_at;
      startAtInput.addEventListener('input', () => { m.start_at = startAtInput.value; markDirty(); updateEndText(); });
      const startAtField = awField('Дата и время начала', startAtInput);
      startAtField.style.display = m.start_mode === 'scheduled' ? '' : 'none';
      register('auction_start', startAtInput, 1);

      // Duration
      const durationGroup = document.createElement('div');
      durationGroup.className = 'aw-chips';
      AW_DURATION_OPTIONS.forEach((opt) => {
        const chip = document.createElement('button');
        chip.type = 'button';
        chip.className = 'aw-chip' + (m.duration === opt.value ? ' is-active' : '');
        chip.textContent = opt.label;
        chip.addEventListener('click', () => {
          m.duration = opt.value;
          durationGroup.querySelectorAll('.aw-chip').forEach((c) => c.classList.remove('is-active'));
          chip.classList.add('is-active');
          endAtField.style.display = opt.value === 'custom' ? '' : 'none';
          markDirty(); updateEndText();
        });
        durationGroup.appendChild(chip);
      });
      const endAtInput = document.createElement('input');
      endAtInput.type = 'datetime-local'; endAtInput.value = m.end_at;
      endAtInput.addEventListener('input', () => { m.end_at = endAtInput.value; markDirty(); updateEndText(); });
      const endAtField = awField('Дата и время завершения', endAtInput);
      endAtField.style.display = m.duration === 'custom' ? '' : 'none';
      register('auction_end', endAtInput, 1);

      const endText = document.createElement('p');
      endText.className = 'aw-endtext';
      function updateEndText(){
        const start = m.start_mode === 'scheduled' && m.start_at ? new Date(m.start_at) : new Date();
        let end = null;
        if (m.duration === 'custom'){ end = m.end_at ? new Date(m.end_at) : null; }
        else { end = new Date(start.getTime() + (AW_DURATION_MINUTES[m.duration] || 10080) * 60000); }
        endText.textContent = end && !Number.isNaN(end.getTime()) ? ('Аукцион завершится ' + awFormatDateTime(end)) : '';
      }
      updateEndText();

      // Price
      const priceInput = awNumber(m.start_price);
      let stepTouched = m.step !== '';
      priceInput.addEventListener('input', () => {
        m.start_price = priceInput.value;
        if (!stepTouched){
          const suggested = awSuggestStep(priceInput.value);
          if (suggested != null){ m.step = String(suggested); stepInput.value = m.step; }
        }
        markDirty();
      });
      const stepInput = awNumber(m.step);
      stepInput.addEventListener('input', () => { stepTouched = true; m.step = stepInput.value; markDirty(); });
      const quickSteps = document.createElement('div');
      quickSteps.className = 'aw-chips';
      [['50', '50 ₽'], ['100', '100 ₽'], ['500', '500 ₽'], ['', 'Другое']].forEach(([val, label]) => {
        const chip = document.createElement('button');
        chip.type = 'button'; chip.className = 'aw-chip'; chip.textContent = label;
        chip.addEventListener('click', () => {
          if (val){ stepTouched = true; m.step = val; stepInput.value = val; markDirty(); }
          else { stepInput.focus(); }
        });
        quickSteps.appendChild(chip);
      });
      register('auction_start_price', priceInput, 1);
      register('auction_step', stepInput, 1);

      // Advanced (collapsible): reserve + auto-extend
      const advanced = document.createElement('details');
      advanced.className = 'aw-advanced';
      const summary = document.createElement('summary');
      summary.textContent = 'Дополнительные настройки';
      advanced.appendChild(summary);
      const reserveInput = awNumber(m.reserve);
      reserveInput.placeholder = 'необязательно';
      reserveInput.addEventListener('input', () => { m.reserve = reserveInput.value; markDirty(); });
      register('auction_reserve_price', reserveInput, 1);
      const extendInput = document.createElement('input');
      extendInput.type = 'checkbox'; extendInput.checked = m.auto_extend;
      extendInput.addEventListener('change', () => { m.auto_extend = extendInput.checked; markDirty(); });
      const extendLabel = document.createElement('label');
      extendLabel.className = 'aw-check';
      extendLabel.append(extendInput, document.createTextNode(' Продлевать аукцион на 2 минуты, если ставка сделана перед завершением'));
      advanced.append(
        awField('Резервная цена, ₽', reserveInput, { hint: 'Если итоговая ставка будет ниже этой суммы, вы не обязаны продавать предмет. Участники не увидят точную сумму.' }),
        extendLabel,
      );

      frag.append(
        awField('Начало', startGroup, { full: true }),
        startAtField,
        awField('Продолжительность', durationGroup, { full: true }),
        endAtField,
        awField('', endText, { full: true }),
        awField('Стартовая цена, ₽', priceInput),
        awField('Шаг ставки, ₽', stepInput),
        awField('Быстрый шаг', quickSteps, { full: true }),
        awField('', advanced, { full: true }),
      );
      return frag;
    }

    function buildStepDelivery(){
      const frag = document.createElement('div');
      frag.className = 'aw-grid';
      const locationInput = awText(m.location);
      locationInput.addEventListener('input', () => { m.location = locationInput.value; markDirty(); });
      register('location', locationInput, 2);

      const methodsWrap = document.createElement('div');
      methodsWrap.className = 'aw-methods';
      (options.delivery_methods || []).forEach((opt) => {
        const label = document.createElement('label');
        label.className = 'aw-check';
        const cb = document.createElement('input');
        cb.type = 'checkbox';
        cb.checked = m.delivery_methods.indexOf(opt.value) !== -1;
        cb.addEventListener('change', () => {
          const i = m.delivery_methods.indexOf(opt.value);
          if (cb.checked && i === -1) m.delivery_methods.push(opt.value);
          else if (!cb.checked && i !== -1) m.delivery_methods.splice(i, 1);
          deliveryField.style.display = m.delivery_methods.indexOf('delivery') !== -1 ? '' : 'none';
          markDirty();
        });
        label.append(cb, document.createTextNode(' ' + opt.label));
        methodsWrap.appendChild(label);
      });
      const methodsField = awField('Способы получения', methodsWrap, { full: true });
      register('delivery_methods', methodsWrap, 2);

      const costInput = awNumber(m.delivery_cost);
      costInput.placeholder = 'можно оставить пустым';
      costInput.addEventListener('input', () => { m.delivery_cost = costInput.value; markDirty(); });
      const deliveryField = awField('Стоимость доставки, ₽', costInput, { hint: 'Можно оставить пустым, если условия обсуждаются отдельно.' });
      deliveryField.style.display = m.delivery_methods.indexOf('delivery') !== -1 ? '' : 'none';
      register('delivery_cost', costInput, 2);

      const noteInput = awTextarea(m.delivery_note);
      noteInput.addEventListener('input', () => { m.delivery_note = noteInput.value; markDirty(); });
      register('delivery_note', noteInput, 2);

      frag.append(
        awField('Город или местоположение', locationInput, { full: true }),
        methodsField,
        deliveryField,
        awField('Комментарий по передаче', noteInput, { full: true }),
      );
      return frag;
    }

    function buildStepReview(){
      const frag = document.createElement('div');
      const warnings = document.createElement('div');
      warnings.className = 'aw-warnings';
      const issues = collectWarnings();
      if (issues.length){
        const head = document.createElement('p');
        head.className = 'aw-warnings__head';
        head.textContent = 'Заполните обязательные поля:';
        warnings.appendChild(head);
        issues.forEach((issue) => {
          const btn = document.createElement('button');
          btn.type = 'button';
          btn.className = 'aw-warning';
          btn.textContent = issue.message;
          btn.addEventListener('click', () => {
            goToStep(issue.step);
            const entry = controls[issue.key];
            if (entry && entry.control && typeof entry.control.focus === 'function'){
              setTimeout(() => { try { entry.control.focus(); } catch (e) {} }, 30);
            }
          });
          warnings.appendChild(btn);
        });
      }

      const summary = document.createElement('div');
      summary.className = 'aw-summary';
      const cover = (m.images.find((i) => i.is_cover) || m.images[0]);
      const coverWrap = document.createElement('div');
      coverWrap.className = 'aw-summary__cover';
      if (cover){ const img = document.createElement('img'); img.src = cover.url; img.alt = ''; coverWrap.appendChild(img); }
      else { coverWrap.textContent = 'Без фото'; coverWrap.classList.add('aw-summary__cover--empty'); }
      const rows = document.createElement('dl');
      rows.className = 'aw-summary__rows';
      const startDate = m.start_mode === 'scheduled' && m.start_at ? new Date(m.start_at) : new Date();
      let endDate = null;
      if (m.duration === 'custom'){ endDate = m.end_at ? new Date(m.end_at) : null; }
      else { endDate = new Date(startDate.getTime() + (AW_DURATION_MINUTES[m.duration] || 10080) * 60000); }
      const add = (label, value) => {
        const row = document.createElement('div');
        const dt = document.createElement('dt'); dt.textContent = label;
        const dd = document.createElement('dd'); dd.textContent = value || '—';
        row.append(dt, dd); rows.appendChild(row);
      };
      add('Название', m.title);
      add('Категория', labelOf(options.category, m.category));
      add('Состояние', labelOf(options.condition, m.condition));
      add('Стартовая цена', m.start_price ? m.start_price + ' ₽' : '');
      add('Шаг ставки', m.step ? m.step + ' ₽' : '');
      add('Начало', m.start_mode === 'scheduled' ? awFormatDateTime(startDate) : 'Сразу после публикации');
      add('Завершение', endDate ? awFormatDateTime(endDate) : '');
      add('Резервная цена', m.reserve ? 'Указана' : 'Нет');
      add('Способы получения', m.delivery_methods.map((v) => labelOf(options.delivery_methods, v)).join(', '));
      add('Местоположение', m.location);
      summary.append(coverWrap, rows);

      frag.append(warnings, summary);
      return frag;
    }

    function collectWarnings(){
      const issues = [];
      const push = (key, step, message) => issues.push({ key: key, step: step, message: message });
      if (!m.images.length) push('images', 0, 'Добавьте хотя бы одну фотографию');
      else if (!m.images.some((i) => i.is_cover)) push('cover_image_id', 0, 'Выберите обложку');
      if (!m.title.trim()) push('title', 0, 'Укажите название');
      if (!m.category) push('category', 0, 'Выберите категорию');
      if (!m.condition) push('condition', 0, 'Укажите состояние предмета');
      if (!(parseFloat(m.start_price) > 0)) push('auction_start_price', 1, 'Укажите стартовую цену');
      if (!(parseFloat(m.step) > 0)) push('auction_step', 1, 'Укажите шаг ставки');
      if (!m.delivery_methods.length) push('delivery_methods', 2, 'Выберите способ получения');
      if (m.start_mode === 'scheduled' && !m.start_at) push('auction_start', 1, 'Укажите дату начала');
      if (m.duration === 'custom' && !m.end_at) push('auction_end', 1, 'Укажите дату завершения');
      return issues;
    }

    // --- Step navigation -----------------------------------------------------
    function renderStep(){
      stepHost.innerHTML = '';
      const builders = [buildStepLot, buildStepPrice, buildStepDelivery, buildStepReview];
      stepHost.appendChild(builders[currentStep]());
      if (window.ThemeSelect) window.ThemeSelect.enhanceAll(stepHost);
      stepDots.forEach((dot, i) => {
        dot.classList.toggle('is-active', i === currentStep);
        dot.classList.toggle('is-done', i < currentStep);
      });
      backBtn.style.visibility = currentStep === 0 ? 'hidden' : '';
      nextBtn.textContent = currentStep === STEPS.length - 1 ? 'Опубликовать аукцион' : 'Продолжить';
      updatePreview();
      modal.body.scrollTop = 0;
    }

    function goToStep(index){
      if (index < 0 || index >= STEPS.length) return;
      currentStep = index;
      m.stepEdited = true;
      renderStep();
    }

    function onNext(){
      if (currentStep < STEPS.length - 1){
        saveScalars();
        goToStep(currentStep + 1);
      } else {
        publish();
      }
    }

    // --- Live preview --------------------------------------------------------
    function updatePreview(){
      preview.innerHTML = '';
      const cover = (m.images.find((i) => i.is_cover) || m.images[0]);
      const media = document.createElement('div');
      media.className = 'aw-preview__media';
      if (cover){ const img = document.createElement('img'); img.src = cover.url; img.alt = ''; media.appendChild(img); }
      else { media.classList.add('aw-preview__media--empty'); media.textContent = 'Без фото'; }
      const title = document.createElement('div');
      title.className = 'aw-preview__title';
      title.textContent = m.title || 'Название лота';
      const price = document.createElement('div');
      price.className = 'aw-preview__price';
      price.textContent = (m.start_price ? m.start_price + ' ₽' : '— ₽') + (m.step ? ' · шаг ' + m.step + ' ₽' : '');
      const meta = document.createElement('div');
      meta.className = 'aw-preview__meta';
      meta.textContent = [labelOf(options.category, m.category), labelOf(options.condition, m.condition)].filter(Boolean).join(' · ');
      preview.append(media, title, price, meta);
    }

    // --- Publish -------------------------------------------------------------
    function publish(){
      if (publishing) return; // guard against a double-click / repeat publish
      const issues = collectWarnings();
      if (issues.length){
        goToStep(STEPS.length - 1);
        generalError.textContent = 'Заполните обязательные поля, отмеченные ниже.';
        return;
      }
      if (!m.listing_id){
        generalError.textContent = 'Черновик лота не найден. Закройте окно и попробуйте снова.';
        return;
      }
      generalError.textContent = '';
      publishing = true;
      nextBtn.disabled = true;
      nextBtn.classList.add('is-loading');
      const restore = nextBtn.textContent;
      nextBtn.textContent = 'Публикуем…';
      setSaveStatus('saving');
      // Persist latest scalars, then publish.
      saveScalars().then(() => marketRequest(draftPublishUrl(m.listing_id), 'POST', {}))
        .then(({ ok, data }) => {
          publishing = false;
          nextBtn.disabled = false;
          nextBtn.classList.remove('is-loading');
          nextBtn.textContent = restore;
          if (!ok){
            const general = distributeErrors(data && data.errors);
            const firstKey = Object.keys((data && data.errors) || {})[0];
            const entry = firstKey && controls[firstKey];
            if (entry) goToStep(entry.step);
            generalError.textContent = general || 'Не удалось опубликовать аукцион. Проверьте поля.';
            setSaveStatus('');
            return;
          }
          dirty = false;
          modal.close();
          refreshOpenCardAuctionStatus(file);
          openPublishSuccessModal(data.redirect);
        }).catch(() => {
          publishing = false;
          nextBtn.disabled = false;
          nextBtn.classList.remove('is-loading');
          nextBtn.textContent = restore;
          generalError.textContent = 'Сетевая ошибка при публикации.';
        });
    }

    const generalError = document.createElement('p');
    generalError.className = 'aw-general-error';
    generalError.setAttribute('role', 'alert');
    main.appendChild(generalError);

    function requestClose(){
      if (dirty){
        openConfirmModal('Закрыть без сохранения изменений?', () => { refreshOpenCardAuctionStatus(file); modal.close(); });
      } else {
        refreshOpenCardAuctionStatus(file);
        modal.close();
      }
    }

    renderStep();
  }

  // Deprecated inline modal (replaced by openAuctionWizard); no longer invoked.
  function openLotConfigModal(rubric, file, opts){
    opts = opts || {};
    const isEdit = opts.mode === 'edit';
    const draft = opts.draft || {};
    const attrs = (draft.attributes && typeof draft.attributes === 'object') ? draft.attributes : {};

    const modal = openModal({
      title: isEdit ? 'Редактирование лота' : 'Настройка аукционного лота',
      overlayClass: 'lot-config-overlay',
    });
    modal.overlay.classList.add('archive-modal-overlay--lot-config');

    // --- Card header: thumbnail, title, source rubric, photo count -----------
    const imageField = rubric && rubric.mode !== 'text' && Array.isArray(rubric.fields)
      ? rubric.fields.find((f) => f.type === 'image') : null;
    const photoValue = imageField ? getFieldValue(rubric, file, imageField) : null;
    const photoCount = (photoValue && Array.isArray(photoValue.items)) ? photoValue.items.length : 0;

    const header = document.createElement('div');
    header.className = 'lot-config__card';
    const media = document.createElement('div');
    media.className = 'lot-config__media';
    if (photoCount){
      const primary = getPrimaryImage(photoValue);
      const img = document.createElement('img');
      img.src = primary ? primary.src : '';
      img.alt = '';
      media.appendChild(img);
    } else {
      const ph = document.createElement('div');
      ph.className = 'lot-config__placeholder';
      ph.textContent = 'Без фото';
      media.appendChild(ph);
    }
    const meta = document.createElement('div');
    meta.className = 'lot-config__meta';
    const titleHead = document.createElement('div');
    titleHead.className = 'lot-config__title';
    titleHead.textContent = getDisplayName(rubric, file) || 'Без названия';
    const rubricEl = document.createElement('div');
    rubricEl.className = 'lot-config__rubric';
    rubricEl.textContent = rubric ? (rubric.name || '') : '';
    const countEl = document.createElement('div');
    countEl.className = 'lot-config__count';
    countEl.textContent = 'Фотографий: ' + photoCount;
    meta.append(titleHead, rubricEl, countEl);
    header.append(media, meta);

    // --- Form ----------------------------------------------------------------
    const form = document.createElement('form');
    form.className = 'lot-config__form';
    form.noValidate = true;

    const titleInput = document.createElement('input');
    titleInput.type = 'text';
    titleInput.value = isEdit ? (draft.title || getDisplayName(rubric, file) || '') : (getDisplayName(rubric, file) || '');

    const descriptionInput = document.createElement('textarea');
    descriptionInput.rows = 3;
    descriptionInput.value = isEdit ? (draft.description || '') : cardValue(file, 'description');

    const categorySelect = lotSelect(
      [{ value: '', label: 'Выберите категорию' }].concat(MARKET_CATEGORIES),
      isEdit ? (draft.category || '') : cardValue(file, 'category'));
    const conditionSelect = lotSelect(AUCTION_CONDITION_OPTIONS, isEdit ? (attrs.condition || '') : cardValue(file, 'condition'));

    const locationInput = document.createElement('input');
    locationInput.type = 'text';
    locationInput.value = isEdit ? (attrs.location || '') : cardValue(file, 'location');

    const handoverSelect = lotSelect(AUCTION_HANDOVER_OPTIONS, isEdit ? (attrs.handover || '') : cardValue(file, 'handover'));
    const shippingInput = numberInput(isEdit ? (attrs.shipping_cost || '') : '');

    const startModeSelect = lotSelect(AUCTION_START_OPTIONS, (isEdit && draft.start_at) ? 'scheduled' : 'now');
    const startAtInput = document.createElement('input');
    startAtInput.type = 'datetime-local';
    startAtInput.value = isEdit ? isoToDatetimeLocal(draft.start_at) : '';

    const durationSelect = lotSelect(AUCTION_DURATION_OPTIONS, isEdit ? 'custom' : '7');
    const endAtInput = document.createElement('input');
    endAtInput.type = 'datetime-local';
    endAtInput.value = isEdit ? isoToDatetimeLocal(draft.end_at) : '';

    const startPriceInput = numberInput(isEdit ? (draft.start_price || '') : '');
    startPriceInput.step = '0.01';
    const stepInput = numberInput(isEdit ? (draft.min_bid_step || '1') : '1');
    const reserveInput = numberInput(isEdit ? (draft.reserve_price || '') : '');
    reserveInput.placeholder = 'необязательно';

    const extendInput = document.createElement('input');
    extendInput.type = 'checkbox';
    extendInput.checked = isEdit ? Boolean(draft.auto_extend) : true;
    const extendLabel = document.createElement('label');
    extendLabel.className = 'lot-config__check';
    extendLabel.append(extendInput, document.createTextNode(' Продлевать аукцион при ставке в последние 2 минуты'));

    // Field wrappers (kept for conditional show/hide).
    const shippingField = lotConfigField('Стоимость доставки, ₽', shippingInput);
    const startAtField = lotConfigField('Дата и время начала', startAtInput);
    const endAtField = lotConfigField('Дата и время окончания', endAtInput);

    const grid = document.createElement('div');
    grid.className = 'lot-config__grid';
    grid.append(
      lotConfigField('Категория маркета', categorySelect),
      lotConfigField('Состояние предмета', conditionSelect),
      lotConfigField('Местоположение', locationInput),
      lotConfigField('Способ передачи', handoverSelect),
      shippingField,
      lotConfigField('Начало', startModeSelect),
      startAtField,
      lotConfigField('Продолжительность', durationSelect),
      endAtField,
      lotConfigField('Стартовая цена, ₽', startPriceInput),
      lotConfigField('Шаг ставки, ₽', stepInput),
      lotConfigField('Резервная цена, ₽', reserveInput, { hint: 'Не показывается участникам' }),
    );

    const extendRow = document.createElement('div');
    extendRow.className = 'lot-config__extend';
    extendRow.appendChild(extendLabel);

    const generalError = document.createElement('p');
    generalError.className = 'lot-config__feedback';
    generalError.setAttribute('role', 'alert');

    form.append(
      lotConfigField('Название лота', titleInput, { full: true }),
      lotConfigField('Описание лота', descriptionInput, { full: true }),
      grid,
      extendRow,
    );

    modal.body.append(header, form, generalError);
    // Selects are now in the DOM — enhance them into themed dropdowns.
    if (window.ThemeSelect) window.ThemeSelect.enhanceAll(modal.body);

    // --- Conditional visibility ----------------------------------------------
    function syncConditional(){
      shippingField.style.display = handoverSelect.value === 'Доставка' ? '' : 'none';
      startAtField.style.display = startModeSelect.value === 'scheduled' ? '' : 'none';
      endAtField.style.display = durationSelect.value === 'custom' ? '' : 'none';
    }
    handoverSelect.addEventListener('change', syncConditional);
    startModeSelect.addEventListener('change', syncConditional);
    durationSelect.addEventListener('change', syncConditional);
    syncConditional();

    // --- Validation (errors shown under each field) --------------------------
    function setError(control, msg){ if (control.lotErrorEl) control.lotErrorEl.textContent = msg; }
    function clearErrors(){
      form.querySelectorAll('.lot-config__error').forEach((el) => { el.textContent = ''; });
      generalError.textContent = '';
    }

    function computeTimes(){
      const startAt = startModeSelect.value === 'scheduled' ? startAtInput.value : toDatetimeLocal(new Date());
      let endAt;
      if (durationSelect.value === 'custom'){
        endAt = endAtInput.value;
      } else {
        const days = parseInt(durationSelect.value, 10) || 7;
        const base = startAt ? new Date(startAt) : new Date();
        endAt = toDatetimeLocal(new Date(base.getTime() + days * AUCTION_DAY_MS));
      }
      return { startAt: startAt, endAt: endAt };
    }

    function validate(){
      clearErrors();
      let ok = true; let firstBad = null;
      const fail = (control, msg) => { setError(control, msg); ok = false; if (!firstBad) firstBad = control; };

      if (!titleInput.value.trim()) fail(titleInput, 'Укажите название лота.');
      if (!categorySelect.value) fail(categorySelect, 'Выберите категорию маркета.');
      const sp = parseFloat(startPriceInput.value);
      if (!(sp > 0)) fail(startPriceInput, 'Введите стартовую цену больше нуля.');
      const step = parseFloat(stepInput.value);
      if (!(step > 0)) fail(stepInput, 'Введите шаг ставки больше нуля.');
      if (reserveInput.value && parseFloat(reserveInput.value) < sp) fail(reserveInput, 'Резервная цена не может быть ниже стартовой.');
      if (handoverSelect.value === 'Доставка' && shippingInput.value && parseFloat(shippingInput.value) < 0) fail(shippingInput, 'Некорректная стоимость доставки.');

      const times = computeTimes();
      if (startModeSelect.value === 'scheduled'){
        if (!startAtInput.value) fail(startAtInput, 'Укажите дату начала.');
        else if (new Date(startAtInput.value) <= new Date()) fail(startAtInput, 'Начало должно быть в будущем.');
      }
      if (durationSelect.value === 'custom' && !endAtInput.value) fail(endAtInput, 'Укажите дату окончания.');
      if (times.startAt && times.endAt && new Date(times.endAt) <= new Date(times.startAt)) fail(endAtInput, 'Окончание должно быть позже начала.');

      return { ok: ok, firstBad: firstBad, times: times };
    }

    function applyServerErrors(data){
      clearErrors();
      const errors = (data && data.errors) || {};
      const map = {
        category: categorySelect, start_price: startPriceInput, min_bid_step: stepInput,
        reserve_price: reserveInput, start_at: startAtInput, end_at: endAtInput,
        title: titleInput, file_id: titleInput,
      };
      let handled = false;
      Object.keys(errors).forEach((key) => {
        const msg = Array.isArray(errors[key]) ? errors[key].join(' ') : String(errors[key]);
        if (map[key]){ setError(map[key], msg); handled = true; }
        else { generalError.textContent = (generalError.textContent ? generalError.textContent + '\n' : '') + msg; handled = true; }
      });
      if (!handled) generalError.textContent = 'Не удалось разместить лот.';
    }

    // --- Footer: Отмена / Разместить лот -------------------------------------
    let busy = false;
    const cancelBtn = createActionButton('Отмена');
    cancelBtn.addEventListener('click', () => modal.close());
    const submitBtn = createActionButton('Разместить лот');
    submitBtn.classList.add('lot-config__publish');

    function submit(){
      if (busy) return;
      const result = validate();
      if (!result.ok){
        if (result.firstBad && typeof result.firstBad.focus === 'function') result.firstBad.focus();
        return;
      }
      const mode = startModeSelect.value === 'scheduled' ? 'schedule' : 'publish';
      const payload = {
        mode: mode,
        title: titleInput.value.trim(),
        description: descriptionInput.value.trim(),
        category: categorySelect.value,
        condition: conditionSelect.value,
        location: locationInput.value.trim(),
        handover: handoverSelect.value,
        start_at: result.times.startAt,
        end_at: result.times.endAt,
        start_price: startPriceInput.value,
        min_bid_step: stepInput.value,
        auto_extend: extendInput.checked,
        extend_seconds: extendInput.checked ? 120 : 0,
      };
      if (handoverSelect.value === 'Доставка' && shippingInput.value) payload.shipping_cost = shippingInput.value;
      if (reserveInput.value) payload.reserve_price = reserveInput.value;
      if (!isEdit) payload.file_id = file.id;

      busy = true;
      submitBtn.disabled = true;
      submitBtn.classList.add('is-loading');
      const restoreText = submitBtn.textContent;
      submitBtn.textContent = 'Размещаем…';

      const url = isEdit
        ? '/auction/api/lots/' + encodeURIComponent(opts.lotId) + '/edit/'
        : '/auction/api/lots/create-from-card/';
      postLotRequest(url, payload).then(({ ok, data }) => {
        busy = false;
        submitBtn.disabled = false;
        submitBtn.classList.remove('is-loading');
        submitBtn.textContent = restoreText;
        if (!ok){ applyServerErrors(data); return; } // keep modal open on error
        if (!isEdit) reachGoal('market_publish');
        modal.close();
        refreshOpenCardAuctionStatus(file);
        const lotUrl = data.lot_url || (data.lot && data.lot.lot_url);
        if (lotUrl) window.location.href = lotUrl;
      }).catch(() => {
        busy = false;
        submitBtn.disabled = false;
        submitBtn.classList.remove('is-loading');
        submitBtn.textContent = restoreText;
        generalError.textContent = 'Сетевая ошибка. Попробуйте ещё раз.';
      });
    }

    submitBtn.addEventListener('click', submit);
    modal.footer.append(cancelBtn, submitBtn);
  }

  function openMarketFlow(type, rubric, file){
    if (!file || !file.id){
      return;
    }
    switch (type){
      case 'shop':
        openMarketPriceModal(file, {
          type: 'shop',
          title: 'Размещение в магазине',
          label: 'Цена',
        });
        break;
      case 'wanted':
        openMarketPriceModal(file, {
          type: 'wanted',
          title: 'Спрос — готов купить',
          label: 'Цена, за которую готовы купить',
        });
        break;
      case 'swap':
        openMarketSwapModal(file);
        break;
      case 'auction':
        openMarketAuctionModal(file);
        break;
      case 'free':
        openMarketFreeModal(file);
        break;
      default:
        break;
    }
  }

  function submitMarketListing(payload, modal, errorTarget){
    const target = errorTarget || null;
    if (target){
      target.textContent = '';
    }
    createMarketListingRequest(payload)
      .then((data) => {
        reachGoal('market_publish');
        if (data && data.redirect){
          window.location.href = data.redirect;
        } else if (modal && typeof modal.close === 'function'){
          modal.close();
        }
      })
      .catch((error) => {
        if (target){
          target.textContent = error.message || 'Не удалось создать объявление.';
        } else {
          alert(error.message || 'Не удалось создать объявление.');
        }
      });
  }

  function createCategoryField(){
    const wrapper = document.createElement('label');
    wrapper.textContent = 'Рубрика';
    const select = document.createElement('select');
    select.required = true;
    select.name = 'category';
    const placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = 'Выберите рубрику';
    placeholder.disabled = true;
    placeholder.selected = true;
    select.appendChild(placeholder);
    MARKET_CATEGORIES.forEach((category) => {
      const option = document.createElement('option');
      option.value = category.value;
      option.textContent = category.label;
      select.appendChild(option);
    });
    wrapper.appendChild(select);
    return { wrapper, select };
  }

  function ensureCategorySelected(select, errorTarget){
    if (!select.value){
      if (errorTarget){
        errorTarget.textContent = 'Выберите рубрику.';
      }
      select.focus();
      return false;
    }
    return true;
  }

  function openMarketFreeModal(file){
    const modal = openModal({ title: 'Размещение — даром' });
    const form = document.createElement('form');
    form.className = 'market-form';
    const categoryField = createCategoryField();
    form.appendChild(categoryField.wrapper);
    const errorEl = document.createElement('div');
    errorEl.className = 'form-error';
    form.appendChild(errorEl);
    modal.body.appendChild(form);

    form.addEventListener('submit', (event) => {
      event.preventDefault();
      errorEl.textContent = '';
      if (!ensureCategorySelected(categoryField.select, errorEl)){
        return;
      }
      submitMarketListing({
        file_id: file.id,
        type: 'free',
        category: categoryField.select.value,
      }, modal, errorEl);
    });

    const submitBtn = createActionButton('Разместить');
    submitBtn.addEventListener('click', () => form.requestSubmit());
    const cancelBtn = createActionButton('Отмена');
    cancelBtn.addEventListener('click', () => modal.close());
    modal.footer.append(submitBtn, cancelBtn);
  }

  function openMarketPriceModal(file, config){
    const modal = openModal({ title: config && config.title ? config.title : 'Размещение' });
    const form = document.createElement('form');
    form.className = 'market-form';
    const listingType = config && config.type ? config.type : 'shop';
    const categoryField = createCategoryField();
    form.appendChild(categoryField.wrapper);
    const label = document.createElement('label');
    label.textContent = config && config.label ? config.label : 'Цена';
    const input = document.createElement('input');
    input.type = 'number';
    input.min = '0';
    input.step = '0.01';
    input.required = true;
    label.appendChild(input);
    form.appendChild(label);
    const errorEl = document.createElement('div');
    errorEl.className = 'form-error';
    form.appendChild(errorEl);
    modal.body.appendChild(form);

    form.addEventListener('submit', (event) => {
      event.preventDefault();
      errorEl.textContent = '';
      const value = input.value ? String(input.value).trim() : '';
      if (!value){
        errorEl.textContent = 'Укажите цену.';
        input.focus();
        return;
      }
      if (!ensureCategorySelected(categoryField.select, errorEl)){
        return;
      }
      submitMarketListing({
        file_id: file.id,
        type: listingType,
        price: value,
        category: categoryField.select.value,
      }, modal, errorEl);
    });

    const submitBtn = createActionButton('Разместить');
    submitBtn.addEventListener('click', () => {
      form.requestSubmit();
    });
    const cancelBtn = createActionButton('Отмена');
    cancelBtn.addEventListener('click', () => modal.close());
    modal.footer.append(submitBtn, cancelBtn);
  }

  function openMarketSwapModal(file){
    const modal = openModal({ title: 'Обмен — пожелания' });
    const form = document.createElement('form');
    form.className = 'market-form';
    const categoryField = createCategoryField();
    form.appendChild(categoryField.wrapper);
    const label = document.createElement('label');
    label.textContent = 'Пожелания / варианты обмена';
    const textarea = document.createElement('textarea');
    textarea.rows = 4;
    textarea.required = true;
    label.appendChild(textarea);
    form.appendChild(label);
    const errorEl = document.createElement('div');
    errorEl.className = 'form-error';
    form.appendChild(errorEl);
    modal.body.appendChild(form);

    form.addEventListener('submit', (event) => {
      event.preventDefault();
      errorEl.textContent = '';
      const value = textarea.value ? textarea.value.trim() : '';
      if (!value){
        errorEl.textContent = 'Опишите варианты обмена.';
        textarea.focus();
        return;
      }
      if (!ensureCategorySelected(categoryField.select, errorEl)){
        return;
      }
      submitMarketListing({
        file_id: file.id,
        type: 'swap',
        swap_wishlist: value,
        category: categoryField.select.value,
      }, modal, errorEl);
    });

    const submitBtn = createActionButton('Разместить');
    submitBtn.addEventListener('click', () => form.requestSubmit());
    const cancelBtn = createActionButton('Отмена');
    cancelBtn.addEventListener('click', () => modal.close());
    modal.footer.append(submitBtn, cancelBtn);
  }

  function openMarketAuctionModal(file){
    const modal = openModal({ title: 'Аукцион' });
    const form = document.createElement('form');
    form.className = 'market-form';
    const categoryField = createCategoryField();
    form.appendChild(categoryField.wrapper);

    const fields = [
      { id: 'auction_start', label: 'Дата и время начала', type: 'datetime-local' },
      { id: 'auction_end', label: 'Дата и время окончания', type: 'datetime-local' },
      { id: 'auction_start_price', label: 'Стартовая цена', type: 'number', step: '0.01' },
      { id: 'auction_min_price', label: 'Минимальная цена', type: 'number', step: '0.01' },
      { id: 'auction_step', label: 'Шаг ставки', type: 'number', step: '0.01' },
    ];

    const inputs = {};
    fields.forEach((field) => {
      const wrapper = document.createElement('label');
      wrapper.textContent = field.label;
      const input = document.createElement('input');
      input.name = field.id;
      input.required = true;
      if (field.type === 'datetime-local'){
        input.type = 'datetime-local';
      } else {
        input.type = 'number';
        input.min = '0';
        input.step = field.step || '0.01';
      }
      wrapper.appendChild(input);
      form.appendChild(wrapper);
      inputs[field.id] = input;
    });

    const errorEl = document.createElement('div');
    errorEl.className = 'form-error';
    form.appendChild(errorEl);
    modal.body.appendChild(form);

    form.addEventListener('submit', (event) => {
      event.preventDefault();
      errorEl.textContent = '';
      const payload = { file_id: file.id, type: 'auction' };
      let hasError = false;
      fields.forEach((field) => {
        const value = inputs[field.id].value ? String(inputs[field.id].value).trim() : '';
        if (!value){
          hasError = true;
          inputs[field.id].focus();
        }
        payload[field.id] = value;
      });
      if (!ensureCategorySelected(categoryField.select, errorEl)){
        hasError = true;
      }
      if (hasError){
        if (!errorEl.textContent){
          errorEl.textContent = 'Заполните все поля.';
        }
        return;
      }
      payload.category = categoryField.select.value;
      submitMarketListing(payload, modal, errorEl);
    });

    const submitBtn = createActionButton('Разместить');
    submitBtn.addEventListener('click', () => form.requestSubmit());
    const cancelBtn = createActionButton('Отмена');
    cancelBtn.addEventListener('click', () => modal.close());
    modal.footer.append(submitBtn, cancelBtn);
  }

  window.addEventListener('trezo-open-file', (event) => {
    const detail = event && event.detail ? event.detail : null;
    if (!detail) return;
    if (!stateReady){
      pendingOpenFileDetail = { rubricId: detail.rubricId, fileId: detail.fileId };
      return;
    }
    openFileFromSearch(detail.rubricId, detail.fileId);
  });

  window.addEventListener('storage', (event) => {
    if (event.key === 'ui_prefs_v1' && stateReady){
      renderRubrics();
    }
  });

  document.addEventListener('visibilitychange', () => {
    if (!document.hidden && stateReady){
      renderRubrics();
    }
  });

  initializeState();
})();
