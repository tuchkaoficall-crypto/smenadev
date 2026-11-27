// Скрипты админ-панели СМЕНА

document.addEventListener('DOMContentLoaded', function () {
    // Автозакрытие уведомлений
    document.querySelectorAll('.toast-stack .alert').forEach(function (alert) {
        setTimeout(function () { bootstrap.Alert.getOrCreateInstance(alert).close(); }, 6000);
    });

    // Подтверждение действий: <form data-confirm="Текст"> или <button data-confirm="...">
    document.querySelectorAll('form[data-confirm]').forEach(function (form) {
        form.addEventListener('submit', function (e) {
            if (!confirm(form.dataset.confirm)) e.preventDefault();
        });
    });
    document.querySelectorAll('button[data-confirm], a[data-confirm]').forEach(function (el) {
        el.addEventListener('click', function (e) {
            if (!confirm(el.dataset.confirm)) e.preventDefault();
        });
    });

    // Клик по строке таблицы открывает карточку
    document.querySelectorAll('tr[data-href]').forEach(function (row) {
        row.addEventListener('click', function (e) {
            if (e.target.closest('a, button, form, input, select, label')) return;
            window.location = row.dataset.href;
        });
    });

    // Тема
    var toggle = document.getElementById('themeToggle');
    if (toggle) {
        var setIcon = function () {
            var dark = document.documentElement.getAttribute('data-bs-theme') === 'dark';
            toggle.innerHTML = dark ? '<i class="bi bi-sun"></i>' : '<i class="bi bi-moon-stars"></i>';
        };
        setIcon();
        toggle.addEventListener('click', function () {
            var next = document.documentElement.getAttribute('data-bs-theme') === 'dark' ? 'light' : 'dark';
            document.documentElement.setAttribute('data-bs-theme', next);
            localStorage.setItem('smena-theme', next);
            setIcon();
            document.dispatchEvent(new Event('themechange'));
        });
    }

    // «/» — фокус на глобальный поиск
    document.addEventListener('keydown', function (e) {
        var tag = (e.target.tagName || '').toLowerCase();
        if (e.key === '/' && tag !== 'input' && tag !== 'textarea' && tag !== 'select') {
            var s = document.getElementById('globalSearch');
            if (s) { e.preventDefault(); s.focus(); }
        }
    });

    // Автоотправка фильтров при смене select
    document.querySelectorAll('form.auto-submit select').forEach(function (sel) {
        sel.addEventListener('change', function () { sel.form.submit(); });
    });
});
