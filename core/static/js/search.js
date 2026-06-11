(function(){
  const OPEN_SESSION_KEY = 'trezo:open-file';
  const OPEN_EVENT_NAME = 'trezo-open-file';
  const api = window.TrezoSearch = window.TrezoSearch || {};
  let stateCache = { rubrics: [] };

  async function loadState(){
    try {
      const resp = await fetch('/api/archive/state/', { credentials: 'include', cache: 'no-store' });
      const data = await resp.json();
      if (resp.ok && data && data.success && data.state && typeof data.state === 'object'){
        stateCache = data.state;
        return;
      }
    } catch (e) {}
  }

  function normalize(v){
    const t = String(v || '');
    try { return t.toLocaleLowerCase('ru-RU'); } catch (e){ return t.toLowerCase(); }
  }

  function collectMatches(query){
    const q = normalize(query).trim();
    if (!q) return [];
    const out = [];
    const rubrics = Array.isArray(stateCache.rubrics) ? stateCache.rubrics : [];
    rubrics.forEach((rubric)=>{
      const files = Array.isArray(rubric && rubric.files) ? rubric.files : [];
      files.forEach((file)=>{
        const title = file && file.values ? String(file.values.title || '') : '';
        if (!title) return;
        if (normalize(title).includes(q)){
          out.push({
            rubricId: String(rubric.id),
            fileId: String(file.id),
            rubricName: String(rubric.name || 'Рубрика'),
            title,
          });
        }
      });
    });
    return out.slice(0, 30);
  }

  function createComponent(wrap){
    const input = wrap.querySelector('.search');
    let host = wrap.querySelector('[data-search-results]');
    if (!input) return null;
    if (!host){
      host = document.createElement('div');
      host.className = 'search-results hidden';
      host.dataset.searchResults = 'true';
      wrap.appendChild(host);
    }

    function clear(){ host.innerHTML=''; host.classList.add('hidden'); }

    function render(){
      const matches = collectMatches(input.value || '');
      if (!matches.length){ clear(); return; }
      host.innerHTML = matches.map((m)=>{
        const href = `/archive/?rubric=${encodeURIComponent(m.rubricId)}&file=${encodeURIComponent(m.fileId)}`;
        return `<a class="search-results__item" href="${href}" data-rubric-id="${m.rubricId}" data-file-id="${m.fileId}">
          <span class="search-results__title">${m.title}</span>
          <span class="search-results__rubric">${m.rubricName}</span>
        </a>`;
      }).join('');
      host.classList.remove('hidden');
    }

    input.addEventListener('input', render);
    input.addEventListener('focus', render);
    document.addEventListener('click', (e)=>{ if (!wrap.contains(e.target)) clear(); });

    host.addEventListener('click', (e)=>{
      const link = e.target.closest('a[data-rubric-id][data-file-id]');
      if (!link) return;
      const detail = { rubricId: link.dataset.rubricId, fileId: link.dataset.fileId };
      const isArchive = Boolean(document.getElementById('archiveModalHost'));
      if (isArchive){
        e.preventDefault();
        window.dispatchEvent(new CustomEvent(OPEN_EVENT_NAME, { detail }));
      } else {
        try { sessionStorage.setItem(OPEN_SESSION_KEY, JSON.stringify(detail)); } catch (err) {}
      }
    });

    return { refresh: render, clear };
  }

  const components = Array.from(document.querySelectorAll('.search-wrap')).map(createComponent).filter(Boolean);

  api.refresh = function(){ components.forEach((c)=>c.refresh()); };
  api.hide = function(){ components.forEach((c)=>c.clear()); };
  api.resetCache = function(){ loadState().then(()=>api.refresh()); };
  api.setActiveState = function(_login, state){ stateCache = state && typeof state === 'object' ? state : { rubrics: [] }; api.refresh(); };

  loadState().then(()=>api.refresh());
})();
