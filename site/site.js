/* The theme button, the remembered language and the copy buttons. Everything else
   on the site is static HTML: each language is its own page, built by site/build.py. */
(function () {
  const root = document.documentElement;
  const media = window.matchMedia("(prefers-color-scheme: light)");

  function shown() {
    const chosen = root.dataset.theme;
    root.dataset.shown = chosen || (media.matches ? "light" : "dark");
  }
  shown();
  media.addEventListener("change", shown);

  const btn = document.getElementById("themebtn");
  if (btn) {
    btn.addEventListener("click", function () {
      const next = root.dataset.shown === "light" ? "dark" : "light";
      root.dataset.theme = next;
      try { localStorage.setItem("tigertag-theme", next); } catch (e) {}
      shown();
    });
  }

  /* The language menu closes on a click outside it, or on Escape. */
  const box = document.querySelector(".langbox");
  if (box) {
    document.addEventListener("click", function (e) { if (box.open && !box.contains(e.target)) box.open = false; });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape") box.open = false; });
  }

  /* A language picked in the menu is kept for the next visit to the English
     root page, which then forwards to it. Search engines read every page as it
     is: the redirect only follows a choice the reader made. */
  document.querySelectorAll(".langlist a[data-lang]").forEach(function (a) {
    a.addEventListener("click", function () {
      try { localStorage.setItem("tigertag-lang", a.dataset.lang); } catch (e) {}
    });
  });
  if (root.dataset.lang === "en") {
    let saved = null;
    try { saved = localStorage.getItem("tigertag-lang"); } catch (e) {}
    const target = saved && saved !== "en" && document.querySelector('.langlist a[data-lang="' + saved + '"]');
    if (target) window.location.replace(target.href + window.location.hash);
  }

  /* Copy buttons: the code of the block they sit in (or their data-copy text). */
  const done = document.body.dataset.copied || "OK";
  document.querySelectorAll(".copy").forEach(function (b) {
    const label = b.textContent;
    b.addEventListener("click", function () {
      const code = b.parentElement.querySelector("code");
      const text = b.dataset.copy || (code ? code.innerText : "");
      if (!navigator.clipboard) return;
      navigator.clipboard.writeText(text.replace(/\s+$/, "") + "\n").then(function () {
        b.textContent = done;
        b.classList.add("is-done");
        setTimeout(function () { b.textContent = label; b.classList.remove("is-done"); }, 1600);
      }).catch(function () {});
    });
  });
})();
