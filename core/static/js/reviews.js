(function(){
  const list = document.getElementById('reviewsList');
  const form = document.getElementById('reviewForm');
  const formCard = document.getElementById('reviewFormCard');
  const ratingEl = document.getElementById('reviewRating');
  const textEl = document.getElementById('reviewText');
  const errorEl = document.getElementById('reviewError');
  const stars = Array.from(document.querySelectorAll('.reviews-stars__star'));
  let editingId = null;
  let authed = false;

  function csrf(){ const m=document.cookie.match(/csrftoken=([^;]+)/); return m ? decodeURIComponent(m[1]) : ''; }
  async function api(url, options){
    const resp = await fetch(url, { credentials: 'include', ...(options || {}) });
    const data = await resp.json().catch(()=>({ success:false }));
    return { resp, data };
  }
  function setError(msg){ if (errorEl) errorEl.textContent = msg || ''; }
  function updateStars(v){
    const n = Number(v) || 0;
    stars.forEach((s,i)=>{ s.classList.toggle('is-active', i < n); s.textContent = i < n ? '★' : '☆'; });
    if (ratingEl) ratingEl.value = n > 0 ? String(n) : '';
  }
  function esc(s){ return String(s||'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;'); }

  function render(reviews){
    if (!list) return;
    if (!reviews.length){
      list.innerHTML = '<article class="reviews-empty">Станьте первым, кто поделится впечатлениями о СКлад.</article>';
      return;
    }
    list.innerHTML = reviews.map((r)=>{
      const rating = Math.max(1, Math.min(5, Number(r.rating) || 1));
      const starsText = '★'.repeat(rating) + '☆'.repeat(5-rating);
      const dateText = r.created_at ? new Date(r.created_at).toLocaleDateString('ru-RU') : '';
      return `<article class="reviews-item">
        <div class="reviews-item__author">${esc(r.author || 'Пользователь')}</div>
        <div class="reviews-item__stars">${starsText}</div>
        ${dateText ? `<div class="reviews-item__date">${dateText}</div>` : ''}
        <p class="reviews-item__text">${esc(r.text || '')}</p>
        ${r.is_owner ? `<button type="button" class="reviews-item__edit" data-id="${r.id}" data-rating="${rating}" data-text="${esc(r.text || '')}">Редактировать</button>` : ''}
      </article>`;
    }).join('');
  }

  async function load(){
    const status = await api('/api/auth/status/');
    authed = Boolean(status.data && status.data.authenticated);
    if (formCard) formCard.hidden = !authed;

    const res = await api('/api/reviews/');
    if (res.resp.ok && res.data.success){
      render(Array.isArray(res.data.reviews) ? res.data.reviews : []);
    }
  }

  stars.forEach((s)=> s.addEventListener('click', ()=> updateStars(Number(s.dataset.value))));

  if (list){
    list.addEventListener('click', (e)=>{
      const btn = e.target.closest('[data-id]');
      if (!btn) return;
      editingId = btn.dataset.id;
      updateStars(Number(btn.dataset.rating));
      if (textEl) textEl.value = btn.dataset.text || '';
      setError('');
    });
  }

  if (form){
    form.addEventListener('submit', async (e)=>{
      e.preventDefault();
      setError('');
      if (!authed){ setError('Необходимо войти в аккаунт.'); return; }
      const rating = Number(ratingEl && ratingEl.value);
      const text = (textEl && textEl.value || '').trim();
      if (!rating || rating < 1 || rating > 5){ setError('Укажите рейтинг от 1 до 5'); return; }
      if (!text){ setError('Введите текст отзыва'); return; }

      const url = editingId ? `/api/reviews/${editingId}/` : '/api/reviews/create/';
      const method = editingId ? 'PATCH' : 'POST';
      const { resp, data } = await api(url, {
        method,
        headers: { 'Content-Type':'application/json', 'X-CSRFToken': csrf() },
        body: JSON.stringify({ rating, text }),
      });
      if (!resp.ok || !data.success){ setError('Не удалось сохранить отзыв'); return; }

      editingId = null;
      form.reset();
      updateStars(0);
      await load();
    });
  }

  document.addEventListener('DOMContentLoaded', load);
})();
