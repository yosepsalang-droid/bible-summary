(function () {
  const viewBooks = document.getElementById("viewBooks");
  const viewChapters = document.getElementById("viewChapters");
  const viewSummary = document.getElementById("viewSummary");
  const gridOld = document.getElementById("gridOld");
  const gridNew = document.getElementById("gridNew");
  const gridChapters = document.getElementById("gridChapters");
  const headerTitle = document.getElementById("headerTitle");
  const bookSubtitle = document.getElementById("bookSubtitle");
  const btnBack = document.getElementById("btnBack");
  const summaryMeta = document.getElementById("summaryMeta");
  const summaryBody = document.getElementById("summaryBody");
  const loadingOverlay = document.getElementById("loadingOverlay");

  let currentBook = null;
  let navStack = ["books"];

  const LONG_NAMES = ["예레미야애가", "데살로니가전서", "데살로니가후서"];

  function createBookButton(book) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn-book" + (LONG_NAMES.includes(book.name) ? " btn-book--long" : "");
    btn.textContent = book.name;
    btn.addEventListener("click", () => openChapters(book));
    return btn;
  }

  function renderBooks() {
    BIBLE_BOOKS.old.forEach((book) => gridOld.appendChild(createBookButton(book)));
    BIBLE_BOOKS.new.forEach((book) => gridNew.appendChild(createBookButton(book)));
  }

  function switchView(fromEl, toEl) {
    fromEl.classList.remove("view-active");
    fromEl.classList.add("view-exit");
    toEl.hidden = false;
    requestAnimationFrame(() => {
      toEl.classList.add("view-active");
      setTimeout(() => {
        fromEl.classList.remove("view-exit");
        fromEl.hidden = true;
      }, 350);
    });
  }

  function openChapters(book) {
    currentBook = book;
    gridChapters.innerHTML = "";
    bookSubtitle.textContent = `총 ${book.chapters}장 — 장을 선택하세요`;

    for (let ch = 1; ch <= book.chapters; ch++) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "btn-chapter";
      btn.textContent = `${ch}장`;
      btn.addEventListener("click", () => loadSummary(book.name, ch));
      gridChapters.appendChild(btn);
    }

    headerTitle.textContent = book.name;
    btnBack.hidden = false;
    navStack = ["books", "chapters"];
    switchView(viewBooks, viewChapters);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  const CARD_STYLES = {
    core: "summary-card--core",
    history: "summary-card--history",
    hebrew: "summary-card--hebrew",
    places: "summary-card--places",
  };

  const SUMMARY_SECTIONS = [
    {
      id: "core",
      emoji: "📝",
      title: "문단별 핵심",
      cardClass: "summary-card--core",
      rich: true,
      header: /(?:^|\n)\s*(?:📝\s*문단별\s*핵심|a\.?\s*문단별\s*핵심)\s*[:：]?\s*/i,
    },
    {
      id: "history",
      emoji: "🌍",
      title: "역사&문화적 배경",
      cardClass: "summary-card--history",
      rich: true,
      header: /(?:^|\n)\s*(?:🌍\s*역사\s*[&＆]\s*문화(?:적)?\s*배경|b\.?\s*역사\s*[&＆]\s*문화(?:적)?\s*배경)\s*[:：]?\s*/i,
    },
    {
      id: "hebrew",
      emoji: "💡",
      title: "중요한 히브리어",
      cardClass: "summary-card--hebrew",
      rich: true,
      header: /(?:^|\n)\s*(?:💡\s*중요한\s*(?:히브리어|원어)|c\.?\s*중요한\s*(?:히브리어|원어))\s*[:：]?\s*/i,
    },
    {
      id: "places",
      emoji: "📍",
      title: "지역명&인물의 뜻",
      cardClass: "summary-card--places",
      rich: true,
      header: /(?:^|\n)\s*(?:📍\s*지역명\s*[&＆]\s*인물(?:의)?\s*뜻|d\.?\s*지역명\s*[&＆]\s*인물(?:의)?\s*뜻)\s*[:：]?\s*/i,
    },
  ];

  function buildCard(section, body, isHtml) {
    const useRich = isHtml || section.rich || /<table|<ul|<ol|<li/i.test(body);
    const inner = useRich
      ? `<div class="summary-card__rich">${body.trim()}</div>`
      : `<p class="summary-card__body">${escapeHtml(body.trim()).replace(/\n/g, "<br>")}</p>`;
    return (
      `<article class="summary-card ${section.cardClass}">` +
      `<header class="summary-card__head">` +
      `<span class="summary-card__emoji" aria-hidden="true">${section.emoji}</span>` +
      `<h3 class="summary-card__title">${section.title}</h3>` +
      `</header>` +
      inner +
      `</article>`
    );
  }

  function renderFromSections(sections) {
    return sections
      .map((s) => {
        const meta = SUMMARY_SECTIONS.find((x) => x.id === s.id) || {
          emoji: s.emoji || "📖",
          title: s.title || "",
          cardClass: CARD_STYLES[s.id] || "summary-card--core",
          rich: true,
        };
        return buildCard(meta, s.html, true);
      })
      .join("");
  }

  function formatSummary(text) {
    const found = [];

    SUMMARY_SECTIONS.forEach((section, idx) => {
      const headerMatch = text.match(section.header);
      if (!headerMatch) return;

      const start = headerMatch.index + headerMatch[0].length;
      let end = text.length;

      for (let j = idx + 1; j < SUMMARY_SECTIONS.length; j++) {
        const slice = text.slice(start);
        const next = slice.match(SUMMARY_SECTIONS[j].header);
        if (next) {
          end = Math.min(end, start + next.index);
          break;
        }
      }

      const body = text.slice(start, end).replace(/^[\s:：\-]+/, "").trim();
      if (body) found.push({ section, body });
    });

    if (found.length) {
      return found.map(({ section, body }) => buildCard(section, body)).join("");
    }

    return `<article class="summary-card summary-card--core">` +
      `<p class="summary-card__body">${escapeHtml(text).replace(/\n/g, "<br>")}</p>` +
      `</article>`;
  }

  function escapeHtml(s) {
    const div = document.createElement("div");
    div.textContent = s;
    return div.innerHTML;
  }

  async function loadSummary(bookName, chapter) {
    loadingOverlay.hidden = false;
    summaryMeta.textContent = `${bookName} ${chapter}장`;
    summaryBody.innerHTML = "";

    try {
      const res = await fetch("/api/summarize", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ book: bookName, chapter }),
      });
      const data = await res.json();

      if (!res.ok) {
        summaryBody.innerHTML = `<p class="summary-error">${escapeHtml(data.error || "요약 생성에 실패했습니다.")}</p>`;
      } else if (data.sections && data.sections.length) {
        summaryBody.innerHTML = renderFromSections(data.sections);
      } else {
        summaryBody.innerHTML = formatSummary(data.summary);
      }

      headerTitle.textContent = `${bookName} ${chapter}장`;
      navStack = ["books", "chapters", "summary"];
      switchView(viewChapters, viewSummary);
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (err) {
      summaryBody.innerHTML = `<p class="summary-error">네트워크 오류가 발생했습니다. 다시 시도해 주세요.</p>`;
      headerTitle.textContent = `${bookName} ${chapter}장`;
      navStack = ["books", "chapters", "summary"];
      switchView(viewChapters, viewSummary);
    } finally {
      loadingOverlay.hidden = true;
    }
  }

  function goBack() {
    const current = navStack[navStack.length - 1];

    if (current === "summary") {
      navStack.pop();
      headerTitle.textContent = currentBook.name;
      switchView(viewSummary, viewChapters);
    } else if (current === "chapters") {
      navStack.pop();
      currentBook = null;
      headerTitle.textContent = "성경 요약";
      btnBack.hidden = true;
      switchView(viewChapters, viewBooks);
    }
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  btnBack.addEventListener("click", goBack);
  renderBooks();
})();
