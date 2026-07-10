(function(){
  function initProfileTabs(){
    const tabList = document.querySelector('[data-profile-tabs]');
    if (!tabList) return;

    const buttons = Array.from(tabList.querySelectorAll('[data-profile-tab]'));
    const sections = Array.from(document.querySelectorAll('[data-profile-content]'));
    const indicator = tabList.querySelector('.profile-tabs__indicator');
    if (!buttons.length || !sections.length) return;

    let activeTab = buttons[0].dataset.profileTab || 'rubrics';

    function syncIndicator(){
      const activeButton = buttons.find((button)=>button.dataset.profileTab === activeTab);
      if (!activeButton || !indicator) return;
      indicator.style.width = `${activeButton.offsetWidth}px`;
      indicator.style.transform = `translateX(${activeButton.offsetLeft}px)`;
    }

    function activate(tabName){
      activeTab = buttons.some((button)=>button.dataset.profileTab === tabName) ? tabName : (buttons[0].dataset.profileTab || 'rubrics');
      buttons.forEach((button)=>{
        const selected = button.dataset.profileTab === activeTab;
        button.classList.toggle('is-active', selected);
        button.setAttribute('aria-selected', selected ? 'true' : 'false');
        button.tabIndex = selected ? 0 : -1;
      });
      sections.forEach((section)=>{
        section.hidden = section.dataset.profileContent !== activeTab;
      });
      window.requestAnimationFrame(syncIndicator);
    }

    buttons.forEach((button)=>{
      button.addEventListener('click', ()=>activate(button.dataset.profileTab || 'rubrics'));
      button.addEventListener('keydown', (event)=>{
        if (!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return;
        event.preventDefault();
        const currentIndex = buttons.indexOf(button);
        let nextIndex = currentIndex;
        if (event.key === 'ArrowLeft') nextIndex = (currentIndex - 1 + buttons.length) % buttons.length;
        if (event.key === 'ArrowRight') nextIndex = (currentIndex + 1) % buttons.length;
        if (event.key === 'Home') nextIndex = 0;
        if (event.key === 'End') nextIndex = buttons.length - 1;
        const nextButton = buttons[nextIndex];
        activate(nextButton.dataset.profileTab || 'rubrics');
        nextButton.focus();
      });
    });
    window.addEventListener('resize', syncIndicator);
    activate(activeTab);
  }

  if (document.readyState === 'loading'){
    document.addEventListener('DOMContentLoaded', initProfileTabs, { once:true });
  } else {
    initProfileTabs();
  }
})();
