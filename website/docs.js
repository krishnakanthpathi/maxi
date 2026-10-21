const status = document.getElementById('docs-status');
document.querySelectorAll('[data-copy]').forEach(button => {
  button.addEventListener('click', async () => {
    const code = button.closest('.code-block').querySelector('code');
    try {
      await navigator.clipboard.writeText(code.textContent);
      button.textContent = 'Copied ✓';
      status.textContent = 'Commands copied.';
    } catch {
      const selection = window.getSelection();
      const range = document.createRange();
      range.selectNodeContents(code);
      selection.removeAllRanges();
      selection.addRange(range);
      button.textContent = 'Select + copy';
      status.textContent = 'Code selected. Copy the highlighted text.';
    }
    setTimeout(() => { button.textContent = 'Copy ⧉'; }, 2200);
  });
});

const links = [...document.querySelectorAll('.docs-toc a')];
const sections = links.map(link => document.querySelector(link.hash));
let scheduled = false;
function updateSection() {
  let active = sections[0];
  for (const section of sections) {
    if (section.getBoundingClientRect().top <= 130) active = section;
  }
  for (const link of links) {
    if (link.hash === '#' + active.id) link.setAttribute('aria-current', 'location');
    else link.removeAttribute('aria-current');
  }
  scheduled = false;
}
window.addEventListener('scroll', () => {
  if (!scheduled) { scheduled = true; requestAnimationFrame(updateSection); }
}, { passive: true });
window.addEventListener('resize', updateSection);
updateSection();

const toc = document.querySelector('.docs-toc');
const mobile = window.matchMedia('(max-width: 760px)');
function updateToc() { toc.open = !mobile.matches; }
mobile.addEventListener('change', updateToc);
updateToc();
// Keep navigation expanded on desktop; mobile uses a native disclosure.
toc.addEventListener('toggle', () => { if (!mobile.matches) toc.open = true; });
