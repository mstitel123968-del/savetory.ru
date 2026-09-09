(() => {
  const dialog = document.querySelector('#info-dialog');
  const content = document.querySelector('#dialog-content');
  let opener;
  document.querySelectorAll('[data-open]').forEach(button => button.addEventListener('click', () => {
    const template = document.getElementById(button.dataset.open);
    if (!template) return;
    opener = button;
    content.replaceChildren(template.content.cloneNode(true));
    const settingsPreview = content.querySelector('[data-settings-preview]');
    if (settingsPreview) {
      // Enlarge the same preview that was clicked, without a second copy drifting.
      settingsPreview.replaceChildren(...Array.from(button.childNodes, node => node.cloneNode(true)));
    }
    const heading = content.querySelector('h2');
    if (heading) { heading.id = 'dialog-heading'; dialog.setAttribute('aria-labelledby', heading.id); }
    dialog.showModal();
  }));
  dialog.querySelector('.close').addEventListener('click', () => dialog.close());
  dialog.addEventListener('click', event => {
    if (event.target.closest('[data-close]')) dialog.close();
    if (event.target === dialog) {
      const box = dialog.getBoundingClientRect();
      if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) dialog.close();
    }
  });
  dialog.addEventListener('close', () => opener?.focus());
})();
