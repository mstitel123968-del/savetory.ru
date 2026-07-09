
// populate 10 sample news and wire toggle (only small targeted changes)
// News content is provided by the server (DB-backed) via a json_script tag.
let newsData = [];
try {
  const newsDataEl = document.getElementById('news-data');
  const parsed = newsDataEl ? JSON.parse(newsDataEl.textContent || '[]') : [];
  newsData = Array.isArray(parsed) ? parsed : [];
} catch (e) {
  newsData = [];
}

const list = document.getElementById('newsList');
const params = new URLSearchParams(window.location.search);
const articleSlug = (params.get('article') || '').trim();
let initialAutoExpandedSlug = null;
let preserveInitialAutoExpanded = false;

function isAutoExpandEnabled(){
  return document.body.classList.contains('news-auto-expand');
}

function buildParagraphWithStep(text){
  const p = document.createElement('p');
  const match = text.match(/^(Шаг \d\.)(.*)$/);
  if (!match) {
    p.textContent = text;
    return p;
  }
  const strong = document.createElement('strong');
  strong.textContent = match[1];
  p.appendChild(strong);
  p.appendChild(document.createTextNode(match[2]));
  return p;
}

function buildNewsBody(n){
  const wrapper = document.createElement('div');
  wrapper.className = 'news-full';

  const blocks = n.full.split('\n\n').filter(Boolean);
  blocks.forEach((block) => {
    if (/^\d\)/.test(block)) {
      const h3 = document.createElement('h3');
      h3.textContent = block;
      wrapper.appendChild(h3);
      return;
    }
    wrapper.appendChild(buildParagraphWithStep(block));
  });

  return wrapper;
}

function buildCard(n){
  const card = document.createElement('article');
  card.className = 'news-card tech-article';
  card.setAttribute('role', 'button');
  card.setAttribute('tabindex', '0');
  card.setAttribute('aria-expanded', 'false');
  if (n.slug) {
    card.id = n.slug;
  }

  const title = document.createElement('h2');
  title.className = 'news-title';
  title.textContent = n.title;

  const preview = document.createElement('p');
  preview.className = 'news-preview';
  preview.textContent = n.preview;

  card.appendChild(title);
  card.appendChild(preview);
  card.appendChild(buildNewsBody(n));

  const centerBar = document.createElement('div');
  centerBar.className = 'center-bar';
  centerBar.setAttribute('aria-hidden', 'true');
  card.appendChild(centerBar);

  card.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      toggleNewsCard(card);
    }
  });
  return card;
}

function toggleNewsCard(card){
  if (!card) return;
  preserveInitialAutoExpanded = false;
  if (isAutoExpandEnabled()) {
    card.classList.add('expanded');
    card.setAttribute('aria-expanded', 'true');
    return;
  }
  const willExpand = !card.classList.contains('expanded');
  document.querySelectorAll('.news-card.expanded').forEach(c => {
    if (c !== card) {
      c.classList.remove('expanded');
      c.setAttribute('aria-expanded', 'false');
    }
  });

  if (willExpand) {
    card.classList.add('expanded');
    card.setAttribute('aria-expanded', 'true');
    card.scrollIntoView({ behavior: 'smooth', block: 'center' });
  } else {
    card.classList.remove('expanded');
    card.setAttribute('aria-expanded', 'false');
  }
}

function expandNewsCardByHash(hash, options = {}){
  if (!hash) return false;
  const slug = hash.replace(/^#/, '').trim();
  if (!slug) return false;
  return expandNewsCardBySlug(slug, options);
}

function expandNewsCardBySlug(slug, options = {}){
  if (!slug) return false;
  const card = document.getElementById(slug);
  if (!card || !card.classList.contains('news-card')) return false;

  if (!isAutoExpandEnabled()) {
    document.querySelectorAll('.news-card.expanded').forEach((item) => {
      if (item !== card) {
        item.classList.remove('expanded');
        item.setAttribute('aria-expanded', 'false');
      }
    });
  }

  card.classList.add('expanded');
  card.setAttribute('aria-expanded', 'true');

  if (options.scroll !== false) {
    card.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
  return true;
}

function applyAutoExpand(){
  const auto = isAutoExpandEnabled();
  document.querySelectorAll('.news-card').forEach((card)=>{
    if(auto){
      card.classList.add('expanded');
      card.setAttribute('aria-expanded', 'true');
    }else{
      card.classList.remove('expanded');
      card.setAttribute('aria-expanded', 'false');
    }
  });

  if (!auto && preserveInitialAutoExpanded && initialAutoExpandedSlug) {
    const card = document.getElementById(initialAutoExpandedSlug);
    if (card && card.classList.contains('news-card')) {
      card.classList.add('expanded');
      card.setAttribute('aria-expanded', 'true');
    }
  }
}

newsData.forEach(n=>{
  if(!list) return;
  const card = buildCard(n);
  if (newsData.length === 1) {
    card.classList.add('expanded');
    card.setAttribute('aria-expanded', 'true');
  }
  list.appendChild(card);
});

applyAutoExpand();
if (articleSlug) {
  const expanded = expandNewsCardBySlug(articleSlug, { scroll: true });
  if (expanded) {
    initialAutoExpandedSlug = articleSlug;
    preserveInitialAutoExpanded = true;
  }
} else {
  expandNewsCardByHash(window.location.hash, { scroll: false });
}

const bodyClassObserver = new MutationObserver((mutations)=>{
  if(mutations.some(m=>m.attributeName==='class')){
    applyAutoExpand();
  }
});
if(document.body){
  bodyClassObserver.observe(document.body,{attributes:true,attributeFilter:['class']});
}

// toggle logic: open clicked card, close others
document.addEventListener('click', (e)=>{
  if(isAutoExpandEnabled()) return;
  const card = e.target.closest('.news-card');
  if(card){
    toggleNewsCard(card);
  }
});

window.addEventListener('hashchange', () => {
  expandNewsCardByHash(window.location.hash);
});

const root = document.documentElement;
const backLink = document.querySelector('[data-news-back]');
if (root && root.classList.contains('news-guest') && backLink) {
  backLink.hidden = false;
}

if (typeof window !== 'undefined' && window.__newsAuthed) {
  const pageTitle = document.querySelector('[data-page-title]');
  if (pageTitle) {
    pageTitle.textContent = 'Техническая информация';
  }
  document.querySelectorAll('.side-nav .side-btn').forEach(btn => {
    if (btn.textContent && btn.textContent.trim() === 'Инструкции по пользованию') {
      btn.remove();
    }
  });
}
