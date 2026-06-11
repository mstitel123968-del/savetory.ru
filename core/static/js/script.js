
// populate 10 sample news and wire toggle (only small targeted changes)
const newsData = [
{
    slug: 'financial-support',
    title: 'Финансовая поддержка проекта',
    preview: 'Если вам нравится проект и вы хотите помочь его развитию, сайт можно будет поддержать финансово. Это добровольная поддержка, которая поможет развитию функциональности, стабильности и интерфейса.',
    full: 'Сайт продолжает развиваться, и каждая доработка, улучшение интерфейса и добавление новых возможностей требуют времени и ресурсов.\n\nЕсли вам нравится проект и вы хотите помочь его развитию, можно будет поддержать сайт финансово. Это полностью добровольно — сайт продолжит работать и развиваться, а любая поддержка станет вкладом в его дальнейшее улучшение.\n\nПолученные средства могут быть направлены на развитие функциональности, повышение стабильности, улучшение дизайна и внедрение новых полезных возможностей.\n\n[Реквизиты для поддержки будут размещены здесь]\n\nСпасибо за интерес к проекту и за любую форму поддержки — даже простое использование сайта и обратная связь уже очень важны.'
  },
{
    title: 'СКлад запустилось: место, где удобно хранить информацию о вещах и готовить их к продаже',
    preview: 'Мы рады сообщить, что сайт «СКлад» официально начал работу. Это сервис, который помогает собрать в одном месте фото и полную карточку предмета: характеристики, заметки, историю, состояние, цену — всё, что важно для хранения, учёта или последующей продажи.',
    full: 'Ниже — понятный обзор того, что уже доступно на старте.\n\n1) Хранение данных о предметах: рубрики, поля и карточки\n\nГлавная функция сервиса — создание аккуратных карточек предметов с фотографиями и информацией.\n\nШаг 1. Создайте рубрику\n\nЧтобы начать, нужно завести рубрику (например: «Монеты», «Техника», «Коллекция», «Одежда»):\n\nНажмите кнопку «Создать рубрику»\n\nВведите название рубрики\n\nНажмите «Сохранить»\n\nРубрика — это как папка, в которой будут храниться ваши карточки.\n\nШаг 2. Настройте поля под свои задачи\n\nПосле создания рубрики можно настроить, какая информация будет в карточке предмета:\n\nОтключать ненужные поля — чтобы ничего лишнего не мешало\n\nДобавлять новые поля — если вам нужен свой формат учёта\n\nЕсть специальный тип: «масштабируемое поле» — при нажатии на соответствующий булит создаётся поле, куда удобно вносить длинные описания (например: история предмета, подробное состояние, заметки для продажи, комплектация и т.д.)\n\nШаг 3. Заполняйте карточку предмета\n\nКогда поля настроены, можно добавлять предметы:\n\nФотографии: до 5 изображений на одну карточку\n\nИнформация: заполнение всех сохранённых полей (ваша индивидуальная структура)\n\nИ самое важное: в любой момент карточку можно:\n\nредактировать (обновить фото, поправить данные)\n\nудалить, если она больше не нужна\n\n2) Профиль: фото и данные аккаунта\n\nВ разделе Профиль можно оформить свою страницу:\n\nДобавить фото профиля\n\nДоступно редактирование положения и размера изображения (можно подвинуть и подогнать кадр так, как удобно)\n\nЗаполнить информацию об аккаунте (чтобы профиль выглядел аккуратно и узнаваемо)\n\n3) Настройки: гибкая система внешнего вида\n\nМы сделали раздел Настройки максимально практичным — чтобы сайт можно было настроить под себя и под разные сценарии использования (дом, работа, телефон/ноутбук, дневной/вечерний режим).\n\nВозможности настройки внешнего вида:\n\nВыбор общей темы оформления — чтобы интерфейс был комфортным для глаз\n\nТонкая настройка визуальных элементов: вы можете менять то, как выглядит интерфейс “в целом”, не ломая привычную структуру страниц\n\nУправление акцентами: настраивается то, что выделяется в интерфейсе (акцентные элементы, визуальные подсказки, выделения)\n\nНастройка контрастности и читабельности: удобно, если вы много работаете с текстом и карточками\n\nНастройки интерфейса под привычный стиль: спокойный минимализм или более заметные выделения — выбираете вы\n\nИдея простая: СКлад должно быть удобным лично для вас, поэтому внешний вид можно подстроить под вкус и комфорт.\n\n4) Тех. информация: новости о работе и изменениях\n\nРаздел Тех. информация — это наша “служебная лента”:\n\nздесь будут публиковаться новости о доработках\n\nизменения и улучшения\n\nсообщения о работе сайта и важных обновлениях\n\nЕсли хочется понимать, что именно меняется — это место будет самым полезным.\n\n5) Отзывы: оценка и комментарий\n\nНам важна обратная связь — сервис развивается вместе с пользователями. В разделе Отзывы можно:\n\nпоставить оценку до 5 звёзд\n\nнаписать текстовый отзыв\n\nМы правда рады любому отзыву — и позитивному, и критическому: он помогает сделать СКлад понятнее и удобнее.\n\nДобро пожаловать в «СКлад»\n\nЕсли вы ведёте коллекцию, храните информацию о личных вещах, готовите лоты к продаже или просто хотите порядок в данных — СКлад создано для этого.\n\nСпасибо, что вы с нами в начале пути. Следите за обновлениями в разделе Тех. информация — впереди много улучшений.'
  },
];

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
