// Applies the reader's saved theme before the first paint, so a light-theme reader never sees a
// dark flash. It is a separate file rather than an inline script because the public origin sends
// script-src 'self'. /assets is cached immutably: change the version in the filename, not the file.
(function () {
  try {
    if (localStorage.getItem('boustrategy-theme') === 'light') {
      document.documentElement.dataset.theme = 'light'
    }
  } catch (error) {
    // A browser with site data blocked has no saved choice; the dark default stands.
  }
})()
