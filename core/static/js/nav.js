(function(){
  document.addEventListener('DOMContentLoaded', () => {
    const body = document.body;
    const sidebar = document.querySelector('.sidebar');
    const topbarInner = document.querySelector('.topbar-inner');
    const mobileMedia = window.matchMedia('(max-width: 960px)');

    if (body && sidebar && topbarInner){
      let navToggle = topbarInner.querySelector('.mobile-nav-toggle');
      if (!navToggle){
        navToggle = document.createElement('button');
        navToggle.type = 'button';
        navToggle.className = 'mobile-nav-toggle';
        navToggle.setAttribute('aria-label', 'Открыть меню');
        navToggle.setAttribute('aria-expanded', 'false');
        navToggle.innerHTML = '<span class="mobile-nav-toggle__line"></span><span class="mobile-nav-toggle__line"></span><span class="mobile-nav-toggle__line"></span>';
        topbarInner.insertBefore(navToggle, topbarInner.firstChild);
      }

      let backdrop = document.querySelector('.mobile-nav-backdrop');
      if (!backdrop){
        backdrop = document.createElement('button');
        backdrop.type = 'button';
        backdrop.className = 'mobile-nav-backdrop';
        backdrop.setAttribute('aria-label', 'Закрыть меню');
        backdrop.setAttribute('aria-hidden', 'true');
        document.body.appendChild(backdrop);
      }

      const closeMobileNav = () => {
        body.classList.remove('mobile-nav-open');
        navToggle.setAttribute('aria-expanded', 'false');
      };

      const openMobileNav = () => {
        body.classList.add('mobile-nav-open');
        navToggle.setAttribute('aria-expanded', 'true');
      };

      const toggleMobileNav = () => {
        if (body.classList.contains('mobile-nav-open')){
          closeMobileNav();
        } else {
          openMobileNav();
        }
      };

      navToggle.addEventListener('click', toggleMobileNav);
      backdrop.addEventListener('click', closeMobileNav);

      document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && body.classList.contains('mobile-nav-open')){
          closeMobileNav();
          navToggle.focus();
        }
      });

      sidebar.addEventListener('click', (event) => {
        if (!mobileMedia.matches){
          return;
        }
        const clickedLink = event.target.closest('a.side-btn, .market-dropup__item');
        if (clickedLink){
          closeMobileNav();
        }
      });

      const handleMobileBreakpoint = () => {
        if (!mobileMedia.matches){
          closeMobileNav();
        }
      };

      if (typeof mobileMedia.addEventListener === 'function'){
        mobileMedia.addEventListener('change', handleMobileBreakpoint);
      } else if (typeof mobileMedia.addListener === 'function'){
        mobileMedia.addListener(handleMobileBreakpoint);
      }
      window.addEventListener('resize', handleMobileBreakpoint);
    }

    const groups = Array.from(document.querySelectorAll('[data-market-dropup]'));
    if (groups.length){
      let openGroup = null;

      function getTrigger(group){
        return group.querySelector('.nav-market');
      }

      function getList(group){
        return group.querySelector('[data-market-list]');
      }

      function applyPosition(list){
        if (!list){
          return;
        }
        list.style.setProperty('--market-dropup-offset-y', '0px');
        const rect = list.getBoundingClientRect();
        const viewportTop = 12;
        const viewportBottom = window.innerHeight - 12;
        let offset = 0;

        if (rect.bottom > viewportBottom){
          offset -= rect.bottom - viewportBottom;
        }

        if (rect.top + offset < viewportTop){
          offset += viewportTop - (rect.top + offset);
        }

        list.style.setProperty('--market-dropup-offset-y', `${offset}px`);
      }

      function closeGroup(group, {focusTrigger = false} = {}){
        const list = getList(group);
        const trigger = getTrigger(group);
        if (!list || list.hidden){
          return;
        }
        list.hidden = true;
        group.classList.remove('market-dropup--open');
        list.style.removeProperty('--market-dropup-offset-y');
        if (trigger){
          trigger.setAttribute('aria-expanded', 'false');
        }
        if (openGroup === group){
          openGroup = null;
        }
        if (focusTrigger && trigger){
          trigger.focus();
        }
      }

      function focusFirstItem(list){
        const item = list.querySelector('.market-dropup__item');
        if (item){
          item.focus();
        }
      }

      function openGroupMenu(group){
        const list = getList(group);
        const trigger = getTrigger(group);
        if (!list || !trigger){
          return;
        }
        if (openGroup && openGroup !== group){
          closeGroup(openGroup);
        }
        list.hidden = false;
        group.classList.add('market-dropup--open');
        trigger.setAttribute('aria-expanded', 'true');
        openGroup = group;
        requestAnimationFrame(() => {
          applyPosition(list);
          focusFirstItem(list);
        });
      }

      function toggleGroup(group){
        const list = getList(group);
        if (!list){
          return;
        }
        if (list.hidden){
          openGroupMenu(group);
        } else {
          closeGroup(group, {focusTrigger: true});
        }
      }

      function handleTriggerKeydown(event, group){
        if (event.defaultPrevented){
          return;
        }
        if (event.key === 'Enter' || event.key === ' '){
          event.preventDefault();
          toggleGroup(group);
        } else if (event.key === 'ArrowUp' || event.key === 'ArrowDown'){
          event.preventDefault();
          openGroupMenu(group);
        }
      }

      function handleListKeydown(event, group){
        const list = getList(group);
        if (!list){
          return;
        }
        const items = Array.from(list.querySelectorAll('.market-dropup__item'));
        if (!items.length){
          return;
        }
        const currentIndex = items.indexOf(event.target);
        if (event.key === 'Escape'){
          event.preventDefault();
          closeGroup(group, {focusTrigger: true});
          return;
        }
        if (event.key === 'ArrowDown'){
          event.preventDefault();
          const nextIndex = currentIndex === -1 ? 0 : (currentIndex + 1) % items.length;
          items[nextIndex].focus();
        } else if (event.key === 'ArrowUp'){
          event.preventDefault();
          const prevIndex = currentIndex <= 0 ? items.length - 1 : currentIndex - 1;
          items[prevIndex].focus();
        } else if (event.key === 'Home'){
          event.preventDefault();
          items[0].focus();
        } else if (event.key === 'End'){
          event.preventDefault();
          items[items.length - 1].focus();
        }
      }

      groups.forEach((group) => {
        const trigger = getTrigger(group);
        const list = getList(group);
        if (!trigger || !list){
          return;
        }
        const isDisabled = trigger.getAttribute('aria-disabled') === 'true'
          || trigger.hasAttribute('data-disabled');
        if (isDisabled){
          trigger.setAttribute('aria-expanded', 'false');
          list.hidden = true;
          return;
        }
        list.setAttribute('role', 'menu');
        trigger.addEventListener('click', (event) => {
          event.preventDefault();
          toggleGroup(group);
        });
        trigger.addEventListener('keydown', (event) => handleTriggerKeydown(event, group));
        list.addEventListener('keydown', (event) => handleListKeydown(event, group));
      });

      document.addEventListener('click', (event) => {
        if (!openGroup){
          return;
        }
        if (openGroup.contains(event.target)){
          return;
        }
        closeGroup(openGroup);
      });

      document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && openGroup){
          closeGroup(openGroup, {focusTrigger: true});
        }
      });

      const repositionOpenGroup = () => {
        if (!openGroup){
          return;
        }
        const list = getList(openGroup);
        if (!list || list.hidden){
          return;
        }
        applyPosition(list);
      };

      window.addEventListener('resize', repositionOpenGroup);
      window.addEventListener('scroll', repositionOpenGroup, true);
    }
  });
})();
