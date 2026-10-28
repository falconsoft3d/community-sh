// Light/dark theme. Loaded synchronously in <head> so the page never flashes the wrong theme.
// The choice is saved per browser; without one, the system preference is followed.
(function () {
    var STORAGE_KEY = 'theme';
    var media = window.matchMedia('(prefers-color-scheme: dark)');

    function storedTheme() {
        try {
            return localStorage.getItem(STORAGE_KEY);
        } catch (e) {
            return null;
        }
    }

    function apply(theme) {
        var dark = theme ? theme === 'dark' : media.matches;
        document.documentElement.classList.toggle('dark', dark);
        document.documentElement.style.colorScheme = dark ? 'dark' : 'light';
    }

    apply(storedTheme());

    // Follow the system while the user hasn't picked a theme
    media.addEventListener('change', function () {
        if (!storedTheme()) {
            apply(null);
        }
    });

    // Sidebar collapsed to icons only, remembered per browser
    try {
        if (localStorage.getItem('sidebar') === 'collapsed') {
            document.documentElement.classList.add('sidebar-collapsed');
        }
    } catch (e) {}

    window.toggleSidebar = function () {
        var collapsed = document.documentElement.classList.toggle('sidebar-collapsed');
        try {
            localStorage.setItem('sidebar', collapsed ? 'collapsed' : 'expanded');
        } catch (e) {}
    };

    window.toggleTheme = function () {
        var next = document.documentElement.classList.contains('dark') ? 'light' : 'dark';
        try {
            localStorage.setItem(STORAGE_KEY, next);
        } catch (e) {
            // Private mode: the toggle still works for this page
        }
        apply(next);
    };
})();
