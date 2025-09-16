// (function() {
//     const bg = localStorage.getItem("themeBgColor");
//     const text = localStorage.getItem("themeTextColor");
//     const containerBg = localStorage.getItem("themeContainerBg");
//     const sectionBg = localStorage.getItem("themeSectionBg");

//     if (bg) document.documentElement.style.setProperty("--theme-bg", bg);
//     if (text) document.documentElement.style.setProperty("--theme-text", text);
//     if (containerBg) document.documentElement.style.setProperty("--theme-container-bg", containerBg);
//     if (sectionBg) document.documentElement.style.setProperty("--theme-section", sectionBg);
// })();

// 載入 localStorage 並套用主題變數
(function () {
    const keys = [
        "bg", "text", "heading",  "surface", "section", "tab-bg",
        "tab-active-bg", "table-header-bg", "border", "surface", "table-border"
    ];
    keys.forEach(key => {
        const val = localStorage.getItem(`theme-${key}`);
        if (val) {
            document.documentElement.style.setProperty(`--theme-${key}`, val);
        }
    });
})();

// 套用主題（整組變數）
function setTheme(theme) {
    for (let key in theme) {
        const cssVar = `--theme-${key}`;
        document.documentElement.style.setProperty(cssVar, theme[key]);
        localStorage.setItem(`theme-${key}`, theme[key]);
    }
}

// 依據背景色快速匹配其餘色彩
function matchcolorTheme(bg, text = null) {
    const isDark = bg.toLowerCase() === "#333333";
    const theme = {
        "bg": bg,
        "surface": isDark ? "#444" : "#ffffff",  
        "text": text || (isDark ? "#ffffff" : "#333333"),
        "heading": isDark ? "#ffffff" : "#136bc9",
        "surface": isDark ? "#444" : "#ffffff",
        "section": isDark ? "#555" : "#fbf9f3",
        "table-header-bg": isDark ? "#666" : "#f0e8d8",
        "table-border": isDark ? "#888" : "#d6c9aa",
        "tab-bg": bg,
        "tab-active-bg": isDark ? "#222" : "#ffffff",
        "border": "#b0a99f"
    };
    setTheme(theme);
}