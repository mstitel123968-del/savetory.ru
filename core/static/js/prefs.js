(function(){
  const KEY='ui_prefs_v1';
  const DEFAULTS={
    theme:'light',
    accent:'blue',
    customThemeColor:'#102a43',
    customAccentColor:'#3b82f6',
    fontScale:1,
    bgIntensity:1,
    fontFamily:'system',
    lineHeight:'normal',
    density:'cozy',
    sidebarSize:'normal',
    cardStyle:'elevated',
    backgroundStyle:'gradient',
    bodyWeight:'regular',
    headingFont:'sans',
    headingStyle:'minimal',
    headingColor:'auto',
    textTone:'balanced',
    reduceMotion:false,
    plainBackground:false,
    focusStrong:false,
    showHints:true,
    topbarMode:'floating',
    expandNews:false,
    archiveView:'cards',
    archiveSort:'created',
    archiveCardSize:'medium',
    archiveEmptyFields:'dash',
    archiveThumbnails:'always',
  };
  const UI_PREF_KEYS=[
    'theme',
    'customThemeColor',
    'fontScale',
    'bgIntensity',
    'accent',
    'customAccentColor',
    'fontFamily',
    'lineHeight',
    'density',
    'sidebarSize',
    'cardStyle',
    'backgroundStyle',
    'bodyWeight',
    'headingFont',
    'headingStyle',
    'headingColor',
    'textTone',
    'reduceMotion',
    'plainBackground',
    'focusStrong',
    'showHints',
    'topbarMode',
    'expandNews',
    'archiveView',
    'archiveSort',
    'archiveCardSize',
    'archiveEmptyFields',
    'archiveThumbnails',
  ];
  const themeClasses=['theme-dark','theme-light','theme-retro','theme-sepia','theme-contrast','theme-midnight','theme-aurora','theme-pastel'];
  const accentClasses=['accent-blue','accent-black','accent-red','accent-green','accent-violet','accent-emerald','accent-amber','accent-rose','accent-sky','accent-mint','accent-copper'];
  const customThemeProperties=['--app-gradient','--bg','--card','--card-overlay','--card-border','--input-bg','--input-fg','--input-border','--input-placeholder','--btn-bg','--btn-fg','--btn-bg-hover','--btn-border','--btn-shadow','--topbar-bg','--topbar-border','--overlay','--text','--text-base','--muted','--muted-base','--body-color','--heading-color','--app-surface','--app-border','--app-soft'];
  const customAccentProperties=['--accent','--primary-bg','--primary-hover','--primary-fg','--accent-bg','--accent-fg'];
  const fontStacks={
    system:'-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif',
    arial:'"Arial","Helvetica",sans-serif',
    montserrat:'"Montserrat","Arial","Helvetica",sans-serif',
    roboto:'"Roboto","Noto Sans","Helvetica Neue",Arial,sans-serif',
    playfair:'"Playfair Display","Times New Roman",serif',
    lato:'"Lato","Segoe UI","Helvetica Neue",Arial,sans-serif',
    kudry:'"Kudry","PT Sans","Arial",sans-serif',
  };
  const lineClasses={normal:'line-normal',relaxed:'line-relaxed',compact:'line-compact'};
  const lineClassValues=Object.values(lineClasses);
  const densityClasses={cozy:'density-cozy',compact:'density-compact',spacious:'density-spacious'};
  const densityValues=Object.values(densityClasses);
  const sidebarClasses={narrow:'sidebar-narrow',normal:'sidebar-normal',wide:'sidebar-wide'};
  const sidebarValues=Object.values(sidebarClasses);
  const cardClasses={elevated:'card-elevated',flat:'card-flat',outline:'card-outline'};
  const cardValues=Object.values(cardClasses);
  const topbarClasses={floating:'topbar-floating',static:'topbar-static',hidden:'topbar-hidden'};
  const topbarValues=Object.values(topbarClasses);
  const backgroundClasses={gradient:'background-style-gradient',mesh:'background-style-mesh',soft:'background-style-soft'};
  const backgroundValues=Object.values(backgroundClasses);
  const bodyWeightClasses={regular:'text-weight-regular',medium:'text-weight-medium',strong:'text-weight-strong'};
  const bodyWeightValues=Object.values(bodyWeightClasses);
  const headingFontClasses={sans:'heading-font-sans',serif:'heading-font-serif',display:'heading-font-display'};
  const headingFontValues=Object.values(headingFontClasses);
  const headingStyleClasses={minimal:'heading-style-minimal',soft:'heading-style-soft',caps:'heading-style-caps'};
  const headingStyleValues=Object.values(headingStyleClasses);
  const headingColorClasses={auto:null,accent:'heading-color-accent',muted:'heading-color-muted'};
  const headingColorValues=Object.values(headingColorClasses).filter(Boolean);
  const textToneClasses={balanced:'text-tone-balanced',soft:'text-tone-soft',bold:'text-tone-bold'};
  const textToneValues=Object.values(textToneClasses);
  const archiveViewClasses={cards:'archive-view-cards',list:'archive-view-list'};
  const archiveViewValues=Object.values(archiveViewClasses);
  const archiveSortClasses={created:'archive-sort-created',title:'archive-sort-title',rubric:'archive-sort-rubric',manual:'archive-sort-manual'};
  const archiveSortValues=Object.values(archiveSortClasses);
  const archiveCardSizeClasses={small:'archive-card-small',medium:'archive-card-medium',large:'archive-card-large'};
  const archiveCardSizeValues=Object.values(archiveCardSizeClasses);
  const archiveEmptyFieldClasses={dash:'archive-empty-dash',hide:'archive-empty-hide'};
  const archiveEmptyFieldValues=Object.values(archiveEmptyFieldClasses);
  const archiveThumbnailClasses={always:'archive-thumbs-always',hidden:'archive-thumbs-hidden'};
  const archiveThumbnailValues=Object.values(archiveThumbnailClasses);

  function load(){
    try {
      const raw=JSON.parse(localStorage.getItem(KEY)||'{}');
      return raw && typeof raw==='object' ? raw : {};
    } catch(e){
      return {};
    }
  }

  function normalize(raw){
    const source=raw && typeof raw==='object' ? raw : {};
    const prefs={};
    UI_PREF_KEYS.forEach((key)=>{
      prefs[key]=Object.prototype.hasOwnProperty.call(source,key) ? source[key] : DEFAULTS[key];
    });
    return prefs;
  }

  function save(prefs){
    const normalized=normalize(prefs);
    try {
      localStorage.setItem(KEY, JSON.stringify(normalized));
    } catch(e){}
    return normalized;
  }

  function resetAppearance(){
    const prefs=save(DEFAULTS);
    apply(prefs);
    return prefs;
  }

  function pick(obj,key,fallback){
    if(obj && Object.prototype.hasOwnProperty.call(obj,key)) return obj[key];
    return fallback;
  }

  function normalizeHex(value,fallback){
    const text=String(value||'').trim();
    return /^#[0-9a-f]{6}$/i.test(text) ? text.toLowerCase() : fallback;
  }

  function hexRgb(value){
    const hex=normalizeHex(value,'#000000').slice(1);
    return [parseInt(hex.slice(0,2),16),parseInt(hex.slice(2,4),16),parseInt(hex.slice(4,6),16)];
  }

  function mixHex(first,second,weight){
    const a=hexRgb(first),b=hexRgb(second),w=Math.min(1,Math.max(0,Number(weight)||0));
    return '#'+a.map((value,index)=>Math.round(value*w+b[index]*(1-w)).toString(16).padStart(2,'0')).join('');
  }

  function luminance(value){
    const channels=hexRgb(value).map((channel)=>{ const c=channel/255; return c<=.03928?c/12.92:Math.pow((c+.055)/1.055,2.4); });
    return channels[0]*.2126+channels[1]*.7152+channels[2]*.0722;
  }

  function clearInline(properties){
    const targets=[document.documentElement,document.body].filter(Boolean);
    targets.forEach((target)=>properties.forEach((property)=>target.style.removeProperty(property)));
  }

  function applyCustomTheme(color){
    const root=document.body||document.documentElement;
    const light=luminance(color)>.48;
    const bg=light?mixHex(color,'#ffffff',.48):mixHex(color,'#050914',.38);
    const card=light?mixHex(color,'#ffffff',.44):mixHex(color,'#0d1728',.54);
    const input=light?mixHex(color,'#ffffff',.34):mixHex(color,'#111c2d',.46);
    const border=light?mixHex(color,'#64748b',.46):mixHex(color,'#475569',.48);
    const text=light?'#101827':'#edf4ff';
    const muted=light?'#465267':'#9ba9bd';
    const topbar=light?mixHex(color,'#ffffff',.46):mixHex(color,'#08111f',.52);
    const overlay=light?'rgba(15,23,42,.28)':'rgba(3,7,18,.74)';
    if(document.body){ document.body.classList.add(light?'theme-light':'theme-dark'); }
    root.style.setProperty('--app-gradient',`radial-gradient(120% 120% at 0% 0%, ${mixHex(color,light?'#ffffff':'#111827',light?.58:.48)} 0%, ${bg} 58%, ${mixHex(bg,light?'#ffffff':'#000000',light?.82:.76)} 100%)`);
    root.style.setProperty('--bg',bg);
    root.style.setProperty('--card',card);
    root.style.setProperty('--card-overlay',card);
    root.style.setProperty('--card-border',border);
    root.style.setProperty('--input-bg',input);
    root.style.setProperty('--input-fg',text);
    root.style.setProperty('--input-border',border);
    root.style.setProperty('--input-placeholder',muted);
    root.style.setProperty('--btn-bg',input);
    root.style.setProperty('--btn-fg',text);
    root.style.setProperty('--btn-bg-hover',mixHex(color,input,.20));
    root.style.setProperty('--btn-border',border);
    root.style.setProperty('--btn-shadow',light?'0 14px 32px rgba(30,50,70,.16)':'0 14px 32px rgba(3,7,18,.42)');
    root.style.setProperty('--topbar-bg',topbar);
    root.style.setProperty('--topbar-border',border);
    root.style.setProperty('--overlay',overlay);
    root.style.setProperty('--text',text);
    root.style.setProperty('--text-base',text);
    root.style.setProperty('--muted',muted);
    root.style.setProperty('--muted-base',muted);
    root.style.setProperty('--body-color',text);
    root.style.setProperty('--heading-color',text);
    root.style.setProperty('--app-surface',card);
    root.style.setProperty('--app-border',border);
    root.style.setProperty('--app-soft',mixHex(color,card,.16));
    if(root!==document.documentElement){
      customThemeProperties.forEach((property)=>{
        const value=root.style.getPropertyValue(property);
        if(value){ document.documentElement.style.setProperty(property,value); }
      });
    }
  }

  function applyCustomAccent(color){
    const root=document.body||document.documentElement;
    const foreground=luminance(color)>.46?'#07111f':'#ffffff';
    root.style.setProperty('--accent',color);
    root.style.setProperty('--primary-bg',color);
    root.style.setProperty('--primary-hover',mixHex(color,luminance(color)>.46?'#000000':'#ffffff',.84));
    root.style.setProperty('--primary-fg',foreground);
    root.style.setProperty('--accent-bg',`color-mix(in srgb,${color} 25%,transparent)`);
    root.style.setProperty('--accent-fg',foreground);
    if(root!==document.documentElement){
      customAccentProperties.forEach((property)=>{
        const value=root.style.getPropertyValue(property);
        if(value){ document.documentElement.style.setProperty(property,value); }
      });
    }
  }

  function applyBackgroundStyle(style){
    const body=document.body;
    if(!body) return;
    body.style.removeProperty('--background-overlay');
    if(style==='gradient'){
      body.style.setProperty('--background-overlay','linear-gradient(135deg,color-mix(in srgb,var(--bg) 72%,var(--accent) 28%) 0%,var(--bg) 46%,color-mix(in srgb,var(--bg) 52%,var(--accent) 48%) 100%)');
    } else if(style==='mesh'){
      body.style.setProperty('--background-overlay','radial-gradient(circle at 12% 12%,color-mix(in srgb,var(--accent) 52%,transparent) 0%,transparent 38%),radial-gradient(circle at 88% 8%,color-mix(in srgb,var(--accent) 38%,transparent) 0%,transparent 42%),radial-gradient(circle at 54% 92%,color-mix(in srgb,var(--bg) 44%,var(--accent) 30%) 0%,transparent 48%),var(--app-gradient)');
    } else if(style==='soft'){
      body.style.setProperty('--background-overlay','linear-gradient(160deg,color-mix(in srgb,var(--bg) 76%,#ffffff 24%) 0%,color-mix(in srgb,var(--bg) 84%,#000000 16%) 100%),radial-gradient(200% 220% at 50% 120%,color-mix(in srgb,var(--accent) 18%,transparent) 0%,transparent 70%),var(--app-gradient)');
    }
  }

  function apply(p){
    const body=document.body;
    if(!body) return;
    const prefs=normalize(p||{});

    // Theme management
    body.classList.remove(...themeClasses);
    body.classList.remove('theme-system');
    body.removeAttribute('data-system-theme');
    clearInline(customThemeProperties);
    let theme=typeof prefs.theme==='string' ? prefs.theme : DEFAULTS.theme;
    if(theme==='custom'){
      applyCustomTheme(normalizeHex(prefs.customThemeColor,DEFAULTS.customThemeColor));
      body.dataset.customTheme='true';
    } else {
      const themeClass='theme-'+theme;
      if(!themeClasses.includes(themeClass)){
        theme = DEFAULTS.theme;
      }
      body.classList.add('theme-'+theme);
      body.removeAttribute('data-custom-theme');
    }
    if(theme!=='custom' && !themeClasses.includes('theme-'+theme)){
      theme = DEFAULTS.theme;
    }

    // Accent colors
    body.classList.remove(...accentClasses);
    clearInline(customAccentProperties);
    const accent = typeof prefs.accent==='string' ? prefs.accent : DEFAULTS.accent;
    if(accent==='custom'){
      applyCustomAccent(normalizeHex(prefs.customAccentColor,DEFAULTS.customAccentColor));
      body.dataset.customAccent='true';
    } else {
      const accentClass='accent-'+accent;
      if(accentClasses.includes(accentClass)){ body.classList.add(accentClass); }
      else { body.classList.add('accent-'+DEFAULTS.accent); }
      body.removeAttribute('data-custom-accent');
    }

    // Typography
    body.classList.remove('font-system','font-serif','font-rounded','font-mono','font-arial','font-montserrat','font-roboto','font-playfair','font-lato','font-kudry');
    const fontKey = typeof prefs.fontFamily === 'string' ? prefs.fontFamily : DEFAULTS.fontFamily;
    const fontStack = fontStacks[fontKey] || fontStacks[DEFAULTS.fontFamily];
    document.documentElement.style.setProperty('--ff-base', fontStack);

    body.classList.remove(...lineClassValues);
    const lineClass=lineClasses[prefs.lineHeight] || lineClasses[DEFAULTS.lineHeight];
    body.classList.add(lineClass);

    // Density & layout
    body.classList.remove(...densityValues);
    const densityClass=densityClasses[prefs.density] || densityClasses[DEFAULTS.density];
    body.classList.add(densityClass);

    body.classList.remove(...sidebarValues);
    const sidebarClass=sidebarClasses[prefs.sidebarSize] || sidebarClasses[DEFAULTS.sidebarSize];
    body.classList.add(sidebarClass);

    body.classList.remove(...cardValues);
    const cardClass=cardClasses[prefs.cardStyle] || cardClasses[DEFAULTS.cardStyle];
    body.classList.add(cardClass);

    body.classList.remove(...topbarValues);
    const topbarClass=topbarClasses[prefs.topbarMode] || topbarClasses[DEFAULTS.topbarMode];
    body.classList.add(topbarClass);

    body.classList.remove(...backgroundValues);
    const backgroundClass=backgroundClasses[prefs.backgroundStyle] || backgroundClasses[DEFAULTS.backgroundStyle];
    body.classList.add(backgroundClass);
    applyBackgroundStyle(backgroundClasses[prefs.backgroundStyle] ? prefs.backgroundStyle : DEFAULTS.backgroundStyle);

    body.classList.remove(...bodyWeightValues);
    const bodyWeightClass=bodyWeightClasses[prefs.bodyWeight] || bodyWeightClasses[DEFAULTS.bodyWeight];
    if(bodyWeightClass){ body.classList.add(bodyWeightClass); }

    body.classList.remove(...headingFontValues);
    const headingFontClass=headingFontClasses[prefs.headingFont] || headingFontClasses[DEFAULTS.headingFont];
    if(headingFontClass){ body.classList.add(headingFontClass); }

    body.classList.remove(...headingStyleValues);
    const headingStyleClass=headingStyleClasses[prefs.headingStyle] || headingStyleClasses[DEFAULTS.headingStyle];
    if(headingStyleClass){ body.classList.add(headingStyleClass); }

    body.classList.remove(...headingColorValues);
    const headingColorClass=headingColorClasses[prefs.headingColor] || headingColorClasses[DEFAULTS.headingColor];
    if(headingColorClass){ body.classList.add(headingColorClass); }

    body.classList.remove(...textToneValues);
    const toneClass=textToneClasses[prefs.textTone] || textToneClasses[DEFAULTS.textTone];
    if(toneClass){ body.classList.add(toneClass); }

    body.classList.remove(...archiveViewValues);
    body.classList.add(archiveViewClasses[prefs.archiveView] || archiveViewClasses[DEFAULTS.archiveView]);

    body.classList.remove(...archiveSortValues);
    body.classList.add(archiveSortClasses[prefs.archiveSort] || archiveSortClasses[DEFAULTS.archiveSort]);

    body.classList.remove(...archiveCardSizeValues);
    body.classList.add(archiveCardSizeClasses[prefs.archiveCardSize] || archiveCardSizeClasses[DEFAULTS.archiveCardSize]);

    body.classList.remove(...archiveEmptyFieldValues);
    body.classList.add(archiveEmptyFieldClasses[prefs.archiveEmptyFields] || archiveEmptyFieldClasses[DEFAULTS.archiveEmptyFields]);

    body.classList.remove(...archiveThumbnailValues);
    body.classList.add(archiveThumbnailClasses[prefs.archiveThumbnails] || archiveThumbnailClasses[DEFAULTS.archiveThumbnails]);

    // Toggles
    body.classList.toggle('reduce-motion', !!prefs.reduceMotion);
    body.classList.toggle('plain-background', !!prefs.plainBackground);
    body.classList.toggle('focus-strong', !!prefs.focusStrong);
    body.classList.toggle('hide-hints', prefs.showHints === false);
    body.classList.toggle('news-auto-expand', !!prefs.expandNews);

    const scale=Number(pick(prefs,'fontScale',DEFAULTS.fontScale));
    document.documentElement.style.setProperty('--fz-scale', String(scale>0?scale:1));
    let intensity = Number(pick(prefs, 'bgIntensity', DEFAULTS.bgIntensity));
    if (!Number.isFinite(intensity)) intensity = DEFAULTS.bgIntensity;
    intensity = Math.min(1, Math.max(0, intensity));
    const overlayAlpha = intensity >= 0.995 ? 1 : Number(intensity.toFixed(2));
    document.documentElement.style.setProperty('--bg-intensity', intensity.toFixed(3));
    document.documentElement.style.setProperty('--bg-overlay-alpha', overlayAlpha.toFixed(2));
  }

  const initialPrefs=normalize(load());
  apply(initialPrefs);
  window.__loadUIPrefs=function(){ return normalize(load()); };
  window.__saveUIPrefs=save;
  window.__applyUIPrefs=apply;
  window.__resetUIPrefs=resetAppearance;
  window.__uiPrefsDefaults=Object.assign({}, DEFAULTS);
  window.__uiPrefKeys=UI_PREF_KEYS.slice();
  window.TrezoUIPrefs={
    key:KEY,
    defaults:Object.assign({}, DEFAULTS),
    keys:UI_PREF_KEYS.slice(),
    load:window.__loadUIPrefs,
    save,
    apply,
    resetAppearance,
  };

})();

/* Live-обновление темы и масштаба на других открытых страницах */
window.addEventListener('storage', (ev) => {
  try{
    if(ev.key === 'ui_prefs_v1'){
      if (typeof __loadUIPrefs === 'function' && typeof __applyUIPrefs === 'function'){
        __applyUIPrefs(__loadUIPrefs());
      }
    }
  }catch(e){}
});

document.addEventListener('visibilitychange', () => {
  if (!document.hidden){
    try{
      if (typeof __loadUIPrefs === 'function' && typeof __applyUIPrefs === 'function'){
        __applyUIPrefs(__loadUIPrefs());
      }
    }catch(e){}
  }
});
