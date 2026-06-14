(function(){
  function $(s, root=document){ return root.querySelector(s); }
  function $all(s, root=document){ return Array.from(root.querySelectorAll(s)); }
  function csrf(){ const m=document.cookie.match(/csrftoken=([^;]+)/); return m ? decodeURIComponent(m[1]) : ''; }

  const SCALE_MIN = 100;
  const SCALE_MAX = 180;
  const SCALE_STEP = 5;
  const MOVE_STEP = 4;
  const IMG_MAX_BYTES = 2 * 1024 * 1024;
  const IMG_MAX_DIM = 900;
  const JPEG_EXPORT_QUALITY = 0.86;
  const JPEG_MIN_QUALITY = 0.68;
  const JPEG_QUALITY_STEP = 0.06;
  const IMAGE_SCALE_STEP = 0.88;
  const CANVAS_BACKGROUND_FILL = '#fff';
  const EMPTY_PLACEHOLDER = '\u2014';

  async function api(url, options){
    const resp = await fetch(url, { credentials: 'include', ...(options || {}) });
    const data = await resp.json().catch(()=>({ success: false }));
    return { resp, data };
  }

  function clamp(v, min, max){ return Math.min(max, Math.max(min, Number(v) || 0)); }
  function normalizeAvatarPos(raw){
    const pos = raw && typeof raw === 'object' ? raw : {};
    return {
      x: clamp(pos.x == null ? 50 : pos.x, 0, 100),
      y: clamp(pos.y == null ? 50 : pos.y, 0, 100),
      scale: clamp(pos.scale == null ? 100 : pos.scale, SCALE_MIN, SCALE_MAX),
    };
  }

  const AVATAR_FIT_CLASSES = ['avatar-img--landscape', 'avatar-img--portrait', 'avatar-img--square'];

  function updateAvatarImageFit(img){
    if (!img) return;
    const width = img.naturalWidth || 0;
    const height = img.naturalHeight || 0;
    img.classList.remove(...AVATAR_FIT_CLASSES);
    if (!width || !height || Math.abs(width - height) <= 1){
      img.classList.add('avatar-img--square');
    } else if (height > width){
      img.classList.add('avatar-img--portrait');
    } else {
      img.classList.add('avatar-img--landscape');
    }
  }

  function prepareAvatarImage(img){
    if (!img) return;
    img.classList.add('avatar-img');
    if (!img.dataset.avatarFitBound){
      img.dataset.avatarFitBound = '1';
      img.addEventListener('load', ()=>{
        updateAvatarImageFit(img);
        if (img.__avatarRequestedPos){
          applyAvatarStyles(img, img.__avatarRequestedPos);
        }
        img.dispatchEvent(new CustomEvent('avatarfitchange'));
      });
    }
    updateAvatarImageFit(img);
  }

  function setAvatarImageSource(img, source){
    if (!img) return;
    prepareAvatarImage(img);
    img.classList.remove(...AVATAR_FIT_CLASSES);
    if (source){
      if (img.getAttribute('src') !== source){
        img.src = source;
      }
      updateAvatarImageFit(img);
    } else {
      img.removeAttribute('src');
    }
  }

  function getAvatarViewport(img){
    return img ? img.closest('.avatar-box, .avatar-wrap') : null;
  }

  function getAvatarMetrics(img){
    const viewport = getAvatarViewport(img);
    if (!img || !viewport) return null;
    const viewportWidth = viewport.clientWidth || 0;
    const viewportHeight = viewport.clientHeight || 0;
    if (!viewportWidth || !viewportHeight) return null;

    const naturalWidth = img.naturalWidth || 0;
    const naturalHeight = img.naturalHeight || 0;
    let imageWidth = img.offsetWidth || 0;
    let imageHeight = img.offsetHeight || 0;

    if ((!imageWidth || !imageHeight) && naturalWidth && naturalHeight){
      if (naturalHeight > naturalWidth){
        imageWidth = viewportWidth;
        imageHeight = viewportWidth * (naturalHeight / naturalWidth);
      } else if (naturalWidth > naturalHeight){
        imageHeight = viewportHeight;
        imageWidth = viewportHeight * (naturalWidth / naturalHeight);
      } else {
        imageWidth = viewportWidth;
        imageHeight = viewportHeight;
      }
    }

    if (!imageWidth || !imageHeight){
      imageWidth = viewportWidth;
      imageHeight = viewportHeight;
    }

    return { viewportWidth, viewportHeight, imageWidth, imageHeight };
  }

  function clampAvatarPosForImage(img, pos){
    const normalized = normalizeAvatarPos(pos);
    const metrics = getAvatarMetrics(img);
    if (!metrics) return normalized;

    const scale = normalized.scale / 100;
    const scaledWidth = metrics.imageWidth * scale;
    const scaledHeight = metrics.imageHeight * scale;
    const maxOffsetX = scaledWidth <= metrics.viewportWidth ? 0 : (scaledWidth - metrics.viewportWidth) / 2;
    const maxOffsetY = scaledHeight <= metrics.viewportHeight ? 0 : (scaledHeight - metrics.viewportHeight) / 2;
    const requestedOffsetX = ((normalized.x - 50) / 100) * metrics.imageWidth;
    const requestedOffsetY = ((normalized.y - 50) / 100) * metrics.imageHeight;
    const offsetX = clamp(requestedOffsetX, -maxOffsetX, maxOffsetX);
    const offsetY = clamp(requestedOffsetY, -maxOffsetY, maxOffsetY);

    return {
      x: metrics.imageWidth ? clamp(50 + (offsetX / metrics.imageWidth) * 100, 0, 100) : 50,
      y: metrics.imageHeight ? clamp(50 + (offsetY / metrics.imageHeight) * 100, 0, 100) : 50,
      scale: normalized.scale,
    };
  }

  function applyAvatarStyles(img, pos){
    if (!img || !pos) return normalizeAvatarPos(pos);
    img.__avatarRequestedPos = normalizeAvatarPos(pos);
    prepareAvatarImage(img);
    const normalized = clampAvatarPosForImage(img, pos);
    const metrics = getAvatarMetrics(img);
    const offsetX = metrics ? ((normalized.x - 50) / 100) * metrics.imageWidth : 0;
    const offsetY = metrics ? ((normalized.y - 50) / 100) * metrics.imageHeight : 0;
    img.style.setProperty('--avatar-translate-x', `${offsetX.toFixed(3)}px`);
    img.style.setProperty('--avatar-translate-y', `${offsetY.toFixed(3)}px`);
    img.style.setProperty('--avatar-scale', (normalized.scale / 100).toFixed(3));
    return normalized;
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

  function renderPatternLinks(target, rawValue){
    if (!target) return;
    const text = rawValue == null ? '' : String(rawValue);
    if (!text.trim()){
      target.textContent = EMPTY_PLACEHOLDER;
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

  function fillView(profile, username){
    const hero = $('.profile-hero');
    if (hero){
      const displayName = [profile.first || '', profile.last || ''].join(' ').trim() || profile.display_name || username || EMPTY_PLACEHOLDER;
      const title = $('.profile-hero__title-row h1', hero);
      const userNameEl = $('.profile-hero__username', hero);
      const bio = $('.profile-hero__bio', hero);
      const heroAvatar = $('.profile-hero__avatar', hero);
      let heroImg = heroAvatar ? $('img', heroAvatar) : null;
      const heroPlaceholder = heroAvatar ? $('span', heroAvatar) : null;
      if (title) title.textContent = displayName;
      if (userNameEl) userNameEl.textContent = `@${username || ''}`;
      if (bio && profile.interests && !profile.bio) bio.textContent = `Интересы: ${profile.interests}`;
      if (heroPlaceholder) heroPlaceholder.textContent = displayName.charAt(0) || '?';
      if (heroAvatar){
        if (profile.avatar_data){
          if (!heroImg){
            heroImg = document.createElement('img');
            heroImg.alt = '';
            heroImg.draggable = false;
            heroAvatar.appendChild(heroImg);
          }
          heroImg.src = profile.avatar_data;
          heroAvatar.classList.add('has-img');
        } else {
          if (heroImg) heroImg.remove();
          heroAvatar.classList.remove('has-img');
        }
      }
    }
    const view = $('#profileView');
    if (!view) return;
    const title = $('#profileLoginDisplay');
    if (title) title.textContent = String(username || '').trim() || EMPTY_PLACEHOLDER;
    const map = {
      first: profile.first || '',
      last: profile.last || '',
      city: profile.city || '',
      email: profile.email || '',
      link: profile.link || '',
      interests: profile.interests || '',
    };
    Object.entries(map).forEach(([k,v])=>{
      const el = $(`[data-f="${k}"]`, view);
      if (el) renderPatternLinks(el, v || '');
    });

    const avatar = $('#avatarImg');
    const avatarWrap = $('.avatar-wrap');
    const placeholder = $('.avatar-placeholder');
    const pos = normalizeAvatarPos(profile.avatar_pos);
    if (avatar){
      if (profile.avatar_data){
        setAvatarImageSource(avatar, profile.avatar_data);
        applyAvatarStyles(avatar, pos);
        avatar.style.display = 'block';
        if (placeholder) placeholder.style.display = 'none';
        if (avatarWrap) avatarWrap.classList.add('has-img');
      } else {
        setAvatarImageSource(avatar, '');
        avatar.style.display = 'none';
        if (placeholder) placeholder.style.display = '';
        if (avatarWrap) avatarWrap.classList.remove('has-img');
      }
    }
  }

  async function loadProfile(){
    const status = await api('/api/auth/status/');
    if (!status.data.authenticated){
      window.location.assign('/');
      return null;
    }
    const profileResp = await api('/api/profile/');
    if (!profileResp.resp.ok || !profileResp.data.success){
      return null;
    }
    fillView(profileResp.data.profile || {}, status.data.username || '');
    return profileResp.data.profile || {};
  }

  async function compressImage(file){
    const data = await fileToDataURL(file);
    if (!file.type.startsWith('image/')) return data;
    const shouldNormalizeWithCanvas = file.size > IMG_MAX_BYTES;
    if (!shouldNormalizeWithCanvas){
      return data;
    }

    const img = await new Promise((resolve, reject)=>{
      const el = new Image();
      el.onload = ()=>resolve(el);
      el.onerror = ()=>reject(new Error('img load error'));
      el.src = data;
    });

    const naturalWidth = img.naturalWidth || img.width || 1;
    const naturalHeight = img.naturalHeight || img.height || 1;
    const initialRatio = Math.min(1, IMG_MAX_DIM / Math.max(naturalWidth, naturalHeight));
    let w = Math.max(1, Math.round(naturalWidth * initialRatio));
    let h = Math.max(1, Math.round(naturalHeight * initialRatio));
    let quality = JPEG_EXPORT_QUALITY;

    const encode = () => {
      const canvas = document.createElement('canvas');
      canvas.width = w;
      canvas.height = h;
      const ctx = canvas.getContext('2d');
      if (!ctx){
        return data;
      }
      ctx.fillStyle = CANVAS_BACKGROUND_FILL;
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
      return canvas.toDataURL('image/jpeg', quality);
    };

    let encoded = encode();
    while (estimateDataUrlBytes(encoded) > IMG_MAX_BYTES){
      if (quality > JPEG_MIN_QUALITY){
        quality = Math.max(JPEG_MIN_QUALITY, quality - JPEG_QUALITY_STEP);
      } else {
        const nextW = Math.max(1, Math.round(w * IMAGE_SCALE_STEP));
        const nextH = Math.max(1, Math.round(h * IMAGE_SCALE_STEP));
        if (nextW === w && nextH === h){
          break;
        }
        w = nextW;
        h = nextH;
      }
      encoded = encode();
    }

    return encoded;
  }

  async function fileToDataURL(file){
    return new Promise((resolve, reject)=>{
      const reader = new FileReader();
      reader.onload = ()=>resolve(String(reader.result || ''));
      reader.onerror = ()=>reject(reader.error || new Error('read error'));
      reader.readAsDataURL(file);
    });
  }

  function estimateDataUrlBytes(dataUrl){
    if (!dataUrl || typeof dataUrl !== 'string') return 0;
    const commaIndex = dataUrl.indexOf(',');
    const payload = commaIndex >= 0 ? dataUrl.slice(commaIndex + 1) : dataUrl;
    const padding = payload.endsWith('==') ? 2 : (payload.endsWith('=') ? 1 : 0);
    return Math.max(0, Math.floor((payload.length * 3) / 4) - padding);
  }

  function bindEditor(initialProfile){
    const modal = $('#profileEditModal');
    const editBtn = $('#profileEditBtn');
    const closeBtn = $('[data-close]', modal);
    const saveBtn = $('#pe_save');
    const logoutBtn = $('#profileLogoutBtn');
    const avatarBox = $('#pe_avatarBox');
    const fileInput = $('#pe_file');
    const prev = $('#pe_prev');
    const errorEl = $('#pe_error');
    const zoomValueEl = $('[data-zoom-value]', modal);
    const controls = $all('.avatar-ctrl', modal);

    let profileState = { ...(initialProfile || {}) };
    let draftAvatarData = profileState.avatar_data || '';
    let avatarPos = normalizeAvatarPos(profileState.avatar_pos);

    function syncAvatarPreview(){
      if (!avatarBox || !prev) return;
      if (draftAvatarData){
        setAvatarImageSource(prev, draftAvatarData);
        avatarBox.classList.add('has-photo');
        avatarPos = applyAvatarStyles(prev, avatarPos);
      } else {
        setAvatarImageSource(prev, '');
        avatarBox.classList.remove('has-photo');
        avatarPos = normalizeAvatarPos(avatarPos);
      }
      if (zoomValueEl) zoomValueEl.textContent = `${Math.round(avatarPos.scale)}%`;
      controls.forEach((btn)=>{ btn.disabled = !draftAvatarData; });
    }

    if (prev){
      prev.addEventListener('avatarfitchange', ()=>{
        if (!draftAvatarData) return;
        avatarPos = applyAvatarStyles(prev, avatarPos);
      });
    }

    function open(){
      if (!modal) return;
      ['first','last','city','email','link','interests'].forEach((k)=>{
        const el = $(`#pe_${k}`);
        if (el) el.value = profileState[k] || '';
      });
      draftAvatarData = profileState.avatar_data || '';
      avatarPos = normalizeAvatarPos(profileState.avatar_pos);
      syncAvatarPreview();
      modal.classList.add('is-open');
      modal.style.display = 'flex';
      document.body.classList.add('profile-modal-open');
      if (errorEl) errorEl.textContent = '';
    }

    function close(){
      if (!modal) return;
      modal.classList.remove('is-open');
      modal.style.display = 'none';
      document.body.classList.remove('profile-modal-open');
      if (errorEl) errorEl.textContent = '';
    }

    function updateAvatarByControl(btn){
      if (!btn || !draftAvatarData) return;
      const dir = btn.dataset.dir;
      const zoom = btn.dataset.zoom;
      if (dir === 'left') avatarPos.x = clamp(avatarPos.x - MOVE_STEP, 0, 100);
      if (dir === 'right') avatarPos.x = clamp(avatarPos.x + MOVE_STEP, 0, 100);
      if (dir === 'up') avatarPos.y = clamp(avatarPos.y - MOVE_STEP, 0, 100);
      if (dir === 'down') avatarPos.y = clamp(avatarPos.y + MOVE_STEP, 0, 100);
      if (zoom === 'in') avatarPos.scale = clamp(avatarPos.scale + SCALE_STEP, SCALE_MIN, SCALE_MAX);
      if (zoom === 'out') avatarPos.scale = clamp(avatarPos.scale - SCALE_STEP, SCALE_MIN, SCALE_MAX);
      syncAvatarPreview();
    }

    async function onFileSelected(){
      const file = fileInput && fileInput.files && fileInput.files[0];
      if (!file) return;
      const allowed = ['image/png','image/jpeg','image/webp','image/gif'];
      if (!allowed.includes(file.type)){
        if (errorEl) errorEl.textContent = 'Допустимы только PNG/JPG/WEBP/GIF.';
        return;
      }
      if (file.size > 10 * 1024 * 1024){
        if (errorEl) errorEl.textContent = 'Файл слишком большой (максимум 10 МБ).';
        return;
      }
      try {
        draftAvatarData = await compressImage(file);
        avatarPos = normalizeAvatarPos({ x: 50, y: 50, scale: 100 });
        syncAvatarPreview();
        if (errorEl) errorEl.textContent = '';
      } catch (e){
        console.error('[profile] avatar read failed', e);
        if (errorEl) errorEl.textContent = 'Не удалось загрузить фото.';
      }
    }

    if (avatarBox){
      avatarBox.addEventListener('click', ()=>{ if (fileInput) fileInput.click(); });
    }
    if (fileInput){
      fileInput.addEventListener('change', onFileSelected);
    }
    controls.forEach((btn)=>btn.addEventListener('click', ()=>updateAvatarByControl(btn)));

    if (editBtn) editBtn.addEventListener('click', open);
    if (closeBtn) closeBtn.addEventListener('click', close);
    if (modal) modal.addEventListener('click', (e)=>{ if (e.target === modal) close(); });
    document.addEventListener('keydown', (e)=>{
      if (e.key === 'Escape' && modal && modal.classList.contains('is-open')) close();
    });

    if (saveBtn){
      saveBtn.addEventListener('click', async ()=>{
        const payload = {};
        ['first','last','city','email','link','interests'].forEach((k)=>{
          const el = $(`#pe_${k}`);
          payload[k] = el ? el.value.trim() : '';
        });
        payload.avatar_data = draftAvatarData || '';
        avatarPos = draftAvatarData ? applyAvatarStyles(prev, avatarPos) : normalizeAvatarPos(avatarPos);
        payload.avatar_pos = avatarPos;

        const { resp, data } = await api('/api/profile/', {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf() },
          body: JSON.stringify(payload),
        });
        if (!resp.ok || !data.success){
          console.error('[profile] save failed', { status: resp.status, data });
          if (errorEl) errorEl.textContent = 'Не удалось сохранить профиль';
          return;
        }
        profileState = { ...profileState, ...payload };
        close();
        loadProfile();
      });
    }

    if (logoutBtn){
      logoutBtn.addEventListener('click', async ()=>{
        await api('/api/auth/logout/', { method: 'POST', headers: { 'X-CSRFToken': csrf() } });
        window.location.assign('/');
      });
    }
  }

  document.addEventListener('DOMContentLoaded', async ()=>{
    const p = await loadProfile();
    bindEditor(p || {});
  });
})();
