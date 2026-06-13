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
        const clickedLink = event.target.closest('a.side-btn, .market-dropup__item, .site-menu__item[href]');
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

    const siteMenus = Array.from(document.querySelectorAll('[data-site-menu]'));
    if (siteMenus.length){
      let openSiteMenu = null;
      let unreadState = { total: 0, latestAt: null, userId: null };

      function unreadSeenKey(){
        return unreadState.userId ? `savetory:messages-menu-seen:${unreadState.userId}` : '';
      }

      function getUnreadSeenAt(){
        const key = unreadSeenKey();
        return key ? window.localStorage.getItem(key) : '';
      }

      function setUnreadSeenAt(value){
        const key = unreadSeenKey();
        if (key && value){
          window.localStorage.setItem(key, value);
        }
      }

      function hasUnreadMessages(){
        return unreadState.total > 0 && !!unreadState.latestAt;
      }

      function hasNewUnreadForMenu(){
        if (!hasUnreadMessages()){
          return false;
        }
        const seenAt = getUnreadSeenAt();
        return !seenAt || unreadState.latestAt > seenAt;
      }

      function getMessagesMenuItem(){
        return document.querySelector('.site-menu__item[data-nav-section="messages"]');
      }

      function applyUnreadIndicators(){
        const onMessagesPage = document.body.classList.contains('messages-page');
        const showOnButton = !onMessagesPage && !openSiteMenu && hasNewUnreadForMenu();
        const showOnMessagesItem = !onMessagesPage && !!openSiteMenu && hasUnreadMessages();
        siteMenus.forEach((menu) => {
          const toggle = getSiteMenuToggle(menu);
          if (toggle){
            toggle.classList.toggle('has-unread-messages', showOnButton);
          }
        });
        const messagesItem = getMessagesMenuItem();
        if (messagesItem){
          messagesItem.classList.toggle('has-unread-messages', showOnMessagesItem);
        }
      }

      async function refreshUnreadIndicators(){
        try {
          const response = await fetch('/api/messages/unread/', {
            credentials: 'include',
            headers: { 'Accept': 'application/json' },
          });
          if (!response.ok){
            return;
          }
          const data = await response.json();
          if (!data || data.success === false){
            return;
          }
          unreadState = {
            total: Number(data.total || 0),
            latestAt: data.latest_at || null,
            userId: data.user_id || null,
          };
          if (document.body.classList.contains('messages-page') && unreadState.latestAt){
            setUnreadSeenAt(unreadState.latestAt);
          }
          applyUnreadIndicators();
        } catch (error){
          // Notification polling should stay silent.
        }
      }

      function getSiteMenuToggle(menu){
        return menu.querySelector('.site-menu__toggle');
      }

      function getSiteMenuList(menu){
        return menu.querySelector('.site-menu__list');
      }

      function getSiteMenuItems(list){
        return Array.from(list.querySelectorAll('.site-menu__item[href], .site-menu__item:not([aria-disabled="true"])'));
      }

      function positionSiteMenu(menu){
        const toggle = getSiteMenuToggle(menu);
        const list = getSiteMenuList(menu);
        if (!toggle || !list || list.hidden){
          return;
        }
        list.style.left = '0px';
        list.style.top = '0px';
        const toggleRect = toggle.getBoundingClientRect();
        list.style.width = `${toggleRect.width}px`;
        const listRect = list.getBoundingClientRect();
        const viewportPadding = 12;
        let left = toggleRect.left;
        left = Math.min(Math.max(viewportPadding, left), Math.max(viewportPadding, window.innerWidth - listRect.width - viewportPadding));
        let top = toggleRect.top - listRect.height;
        if (top < viewportPadding){
          top = Math.min(toggleRect.bottom, window.innerHeight - listRect.height - viewportPadding);
        }
        top = Math.max(viewportPadding, top);
        list.style.left = `${left}px`;
        list.style.top = `${top}px`;
      }

      function closeSiteMenu(menu, { focusToggle = false } = {}){
        const toggle = getSiteMenuToggle(menu);
        const list = getSiteMenuList(menu);
        if (!toggle || !list || list.hidden){
          return;
        }
        list.hidden = true;
        menu.classList.remove('site-menu--open');
        toggle.setAttribute('aria-expanded', 'false');
        list.style.removeProperty('left');
        list.style.removeProperty('top');
        list.style.removeProperty('width');
        if (openSiteMenu === menu){
          openSiteMenu = null;
        }
        applyUnreadIndicators();
        if (focusToggle){
          toggle.focus();
        }
      }

      function openMenu(menu, { focusFirst = false } = {}){
        const toggle = getSiteMenuToggle(menu);
        const list = getSiteMenuList(menu);
        if (!toggle || !list){
          return;
        }
        if (openSiteMenu && openSiteMenu !== menu){
          closeSiteMenu(openSiteMenu);
        }
        list.hidden = false;
        menu.classList.add('site-menu--open');
        toggle.setAttribute('aria-expanded', 'true');
        openSiteMenu = menu;
        if (unreadState.latestAt){
          setUnreadSeenAt(unreadState.latestAt);
        }
        applyUnreadIndicators();
        requestAnimationFrame(() => {
          positionSiteMenu(menu);
          if (focusFirst){
            const firstItem = getSiteMenuItems(list)[0];
            if (firstItem){
              firstItem.focus();
            }
          }
        });
      }

      function toggleSiteMenu(menu){
        const list = getSiteMenuList(menu);
        if (!list){
          return;
        }
        if (list.hidden){
          openMenu(menu);
        } else {
          closeSiteMenu(menu, { focusToggle: true });
        }
      }

      siteMenus.forEach((menu) => {
        const toggle = getSiteMenuToggle(menu);
        const list = getSiteMenuList(menu);
        if (!toggle || !list){
          return;
        }
        toggle.addEventListener('click', (event) => {
          event.preventDefault();
          toggleSiteMenu(menu);
        });
        toggle.addEventListener('keydown', (event) => {
          if (event.key === 'Enter' || event.key === ' '){
            event.preventDefault();
            toggleSiteMenu(menu);
          } else if (event.key === 'ArrowDown' || event.key === 'ArrowUp'){
            event.preventDefault();
            openMenu(menu, { focusFirst: true });
          }
        });
        list.addEventListener('click', (event) => {
          const disabledItem = event.target.closest('.site-menu__item[aria-disabled="true"]');
          if (disabledItem){
            event.preventDefault();
            return;
          }
          if (event.target.closest('.site-menu__item[href]')){
            closeSiteMenu(menu);
          }
        });
        list.addEventListener('keydown', (event) => {
          const items = getSiteMenuItems(list);
          if (!items.length){
            return;
          }
          const currentIndex = items.indexOf(event.target);
          if (event.key === 'Escape'){
            event.preventDefault();
            closeSiteMenu(menu, { focusToggle: true });
          } else if (event.key === 'ArrowDown'){
            event.preventDefault();
            items[(currentIndex + 1 + items.length) % items.length].focus();
          } else if (event.key === 'ArrowUp'){
            event.preventDefault();
            items[(currentIndex <= 0 ? items.length : currentIndex) - 1].focus();
          } else if (event.key === 'Home'){
            event.preventDefault();
            items[0].focus();
          } else if (event.key === 'End'){
            event.preventDefault();
            items[items.length - 1].focus();
          }
        });
      });

      document.addEventListener('click', (event) => {
        if (!openSiteMenu){
          return;
        }
        if (openSiteMenu.contains(event.target)){
          return;
        }
        const list = getSiteMenuList(openSiteMenu);
        if (list && list.contains(event.target)){
          return;
        }
        closeSiteMenu(openSiteMenu);
      });

      document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && openSiteMenu){
          closeSiteMenu(openSiteMenu, { focusToggle: true });
        }
      });

      const repositionSiteMenu = () => {
        if (openSiteMenu){
          positionSiteMenu(openSiteMenu);
        }
      };
      window.addEventListener('resize', repositionSiteMenu);
      window.addEventListener('scroll', repositionSiteMenu, true);
      refreshUnreadIndicators();
      window.setInterval(refreshUnreadIndicators, 30000);
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
