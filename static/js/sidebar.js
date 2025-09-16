fetch('/static/partials/sidebar.html')
  .then(res => res.text())
  .then(html => {
    document.getElementById('sidebar-container').innerHTML = html;

    // 這裡可以綁定所有 sidebar 中的行為
    const logoutBtn = document.getElementById('logout');
    if (logoutBtn) {
      logoutBtn.addEventListener('click', function (e) {
        e.preventDefault();
        fetch('/logout').then(() => {
          localStorage.clear();
          sessionStorage.clear();
          window.location.href = '/';
        });
      });
    }

    // 其他你想加的 sidebar 功能都可以寫在這裡
  });

