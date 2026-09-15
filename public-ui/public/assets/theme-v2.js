// Applies the reader's theme before the first paint, so the page never flashes the wrong one.
// Light is the default; only a reader's explicit choice of dark is stored. It is a separate file
// rather than an inline script because the public origin sends script-src 'self'. /assets is
// cached immutably: change the version in the filename, not the file.
(function () {
  try {
    if (localStorage.getItem('boustrategy-theme-v2') === 'dark') return
  } catch (error) {
    // A browser with site data blocked has no saved choice; the light default applies.
  }
  document.documentElement.dataset.theme = 'light'
})()
