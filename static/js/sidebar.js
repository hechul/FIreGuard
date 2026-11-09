/* Responsive navigation; navigation content remains the existing dashboard menu. */
(() => {
  'use strict';
  function initSidebar() {
    const sidebar = document.querySelector('.sidebar');
    const title = document.querySelector('.topbar-title');
    if (!sidebar || !title || sidebar.dataset.sidebarReady === 'true') return;
    sidebar.dataset.sidebarReady = 'true';
    sidebar.id = sidebar.id || 'mainSidebar';
    const mobile = window.matchMedia('(max-width: 760px)');
    const compact = window.matchMedia('(max-width: 1080px)');
    const key = 'fireguard-sidebar-collapsed';
    const groupKey = 'fireguard-sidebar-group-collapsed';
    const nav = sidebar.querySelector('.nav-list');
    if (!nav) return;
    nav.id = nav.id || 'monitoringNav';
    const shell = document.querySelector('.app-shell');
    let stored = null;
    try { stored = localStorage.getItem(key); } catch (_) { /* storage may be disabled */ }
    let collapsed = stored === null ? compact.matches : stored === 'true';
    let groupCollapsed = false;
    try { groupCollapsed = localStorage.getItem(groupKey) === 'true'; } catch (_) {}
    let menuOpen = false;

    const makeButton = (className) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = className;
      button.setAttribute('aria-controls', sidebar.id);
      return button;
    };
    const desktopToggle = makeButton('sidebar-toggle');
    const mobileToggle = makeButton('sidebar-mobile-toggle');
    const groupToggle = makeButton('sidebar-group-toggle');
    groupToggle.setAttribute('aria-controls', nav.id);
    groupToggle.textContent = '관제 메뉴';
    sidebar.insertBefore(desktopToggle, nav);
    sidebar.insertBefore(groupToggle, nav);
    title.insertBefore(mobileToggle, title.firstChild);
    const backdrop = document.createElement('button');
    backdrop.type = 'button';
    backdrop.className = 'sidebar-backdrop';
    backdrop.tabIndex = -1;
    backdrop.setAttribute('aria-label', '메뉴 닫기');
    document.body.appendChild(backdrop);
    // Keep menu labels available to assistive technology and compact tooltips.
    sidebar.querySelectorAll('.nav-item').forEach((item) => {
      const text = item.querySelector('div')?.childNodes[0]?.textContent?.trim();
      if (text) { item.setAttribute('aria-label', text); item.title = text; }
    });
    const render = () => {
      document.body.classList.toggle('sidebar-collapsed', !mobile.matches && collapsed);
      document.body.classList.toggle('sidebar-mobile-open', mobile.matches && menuOpen);
      const shown = mobile.matches ? menuOpen : true;
      sidebar.setAttribute('aria-hidden', String(!shown));
      if ('inert' in sidebar) sidebar.inert = !shown;
      // Icons remain available when the desktop sidebar is collapsed. Restore
      // the user's group preference as soon as the sidebar expands again.
      const compactIcons = !mobile.matches && collapsed;
      const groupOpen = compactIcons || !groupCollapsed;
      groupToggle.hidden = compactIcons;
      groupToggle.setAttribute('aria-expanded', String(groupOpen));
      nav.hidden = !groupOpen;
      nav.setAttribute('aria-hidden', String(!groupOpen));
      if ('inert' in nav) nav.inert = !groupOpen;
      desktopToggle.textContent = collapsed ? '›' : '‹';
      desktopToggle.setAttribute('aria-label', collapsed ? '사이드바 펼치기' : '사이드바 접기');
      desktopToggle.setAttribute('aria-expanded', String(!collapsed));
      desktopToggle.title = collapsed ? '사이드바 펼치기' : '사이드바 접기';
      mobileToggle.textContent = menuOpen ? '×' : '☰';
      mobileToggle.setAttribute('aria-label', menuOpen ? '메뉴 닫기' : '메뉴 열기');
      mobileToggle.setAttribute('aria-expanded', String(menuOpen));
      backdrop.hidden = !(mobile.matches && menuOpen);
      window.dispatchEvent(new Event('resize'));
    };
    desktopToggle.addEventListener('click', () => {
      collapsed = !collapsed;
      stored = String(collapsed);
      try { localStorage.setItem(key, stored); } catch (_) {}
      render();
    });
    groupToggle.addEventListener('click', () => {
      groupCollapsed = !groupCollapsed;
      try { localStorage.setItem(groupKey, String(groupCollapsed)); } catch (_) {}
      render();
    });
    const closeMenu = (restoreFocus = false) => {
      if (!menuOpen) return;
      menuOpen = false;
      render();
      if (restoreFocus && mobile.matches) mobileToggle.focus();
    };
    mobileToggle.addEventListener('click', () => { menuOpen = !menuOpen; render(); });
    backdrop.addEventListener('click', () => closeMenu(true));
    sidebar.querySelectorAll('.nav-item').forEach((item) => item.addEventListener('click', () => {
      if (mobile.matches) closeMenu(true);
    }));
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && mobile.matches && menuOpen) closeMenu(true);
    });
    const onChange = () => { if (!mobile.matches) menuOpen = false; render(); };
    mobile.addEventListener('change', onChange);
    compact.addEventListener('change', () => {
      if (stored === null) collapsed = compact.matches;
      onChange();
    });
    // The canvas may finish resizing only after the grid transition ends.
    shell?.addEventListener('transitionend', (event) => {
      if (event.target === shell && event.propertyName === 'grid-template-columns') {
        window.dispatchEvent(new Event('resize'));
      }
    });
    render();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initSidebar);
  else initSidebar();
})();
