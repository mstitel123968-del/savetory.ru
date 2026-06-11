(function(){
  const sloganNode = document.querySelector('[data-landing-slogan]');
  if(!sloganNode) return;

  const slogans = [
    'Твоя коллекция — в одном месте.',
    'Создай своё пространство уже сегодня.',
    'Твоя история начинается с загрузки.',
    'Файлы тоже любят уют.',
    'Память создаётся здесь.'
  ];

  const INITIAL = sloganNode.textContent.trim();
  let index = Math.max(0, slogans.indexOf(INITIAL));
  sloganNode.textContent = slogans[index];

  const FADE_MS = 300;
  const INTERVAL_MS = 5000;
  let intervalId = null;
  let fadeTimeout = null;

  function nextSlogan(){
    sloganNode.classList.add('is-fading');
    fadeTimeout = window.setTimeout(() => {
      index = (index + 1) % slogans.length;
      sloganNode.textContent = slogans[index];
      sloganNode.classList.remove('is-fading');
      fadeTimeout = null;
    }, FADE_MS);
  }

  function startRotation(){
    if(intervalId !== null) return;
    intervalId = window.setInterval(nextSlogan, INTERVAL_MS);
  }

  function stopRotation(){
    if(intervalId !== null){
      window.clearInterval(intervalId);
      intervalId = null;
    }
    if(fadeTimeout !== null){
      window.clearTimeout(fadeTimeout);
      fadeTimeout = null;
      sloganNode.classList.remove('is-fading');
      sloganNode.textContent = slogans[index];
    }
  }

  document.addEventListener('visibilitychange', () => {
    if(document.hidden){
      stopRotation();
    } else {
      startRotation();
    }
  });

  startRotation();
})();
