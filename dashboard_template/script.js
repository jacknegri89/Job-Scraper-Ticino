"use strict";

const state = {
  category: "all", country: "all", seniority: "all", status: "all", salary: "all",
  aiOnly: false, preciseOnly: false, query: "", place: "", source: ""
};
const grid = document.getElementById("grid");
const cards = Array.from(grid.querySelectorAll(".card"));

// Original order means newest first, as sorted by the generator.
cards.forEach((card, index) => { card.dataset.order = index; });

function matchesStatus(card) {
  if (state.status === "all") {
    return card.dataset.status !== "gone";
  }
  return card.dataset.status === state.status;
}

function matchesSalary(card) {
  if (state.salary === "all") {
    return true;
  }
  if (state.salary === "stated") {
    return card.dataset.salary === "stated" || card.dataset.salary === "extracted";
  }
  return card.dataset.salary === state.salary;
}

function cardMatches(card) {
  const data = card.dataset;
  const checks = [
    state.category === "all" || data.category === state.category,
    state.country === "all" || data.country === state.country,
    state.seniority === "all" || data.seniority === state.seniority,
    matchesStatus(card),
    matchesSalary(card),
    !state.aiOnly || data.ai === "match",
    !state.preciseOnly || data.precise === "yes",
    !state.query || data.search.includes(state.query),
    !state.place || data.place === state.place,
    !state.source || data.sources.includes("|" + state.source + "|")
  ];
  return checks.every(Boolean);
}

function applyFilters() {
  let visible = 0;
  for (const card of cards) {
    const show = cardMatches(card);
    card.hidden = !show;
    if (show) {
      visible++;
    }
  }
  document.getElementById("visible-n").textContent = visible;
  document.getElementById("empty").classList.toggle("show", visible === 0);
}

function numberOf(card, name, missing) {
  const value = parseFloat(card.dataset[name]);
  if (Number.isNaN(value)) {
    return missing;
  }
  return value;
}

function applySort(mode) {
  const sorted = [...cards];
  if (mode === "km") {
    sorted.sort((a, b) => numberOf(a, "km", 9999) - numberOf(b, "km", 9999));
  } else if (mode === "net") {
    sorted.sort((a, b) => numberOf(b, "net", -1) - numberOf(a, "net", -1));
  } else if (mode === "checked") {
    sorted.sort((a, b) => b.dataset.checked.localeCompare(a.dataset.checked) || a.dataset.order - b.dataset.order);
  } else {
    sorted.sort((a, b) => a.dataset.order - b.dataset.order);
  }
  for (const card of sorted) {
    grid.appendChild(card);
  }
}

document.getElementById("search").addEventListener("input", (event) => {
  state.query = event.target.value.toLowerCase().trim();
  applyFilters();
});

document.getElementById("sort").addEventListener("change", (event) => {
  applySort(event.target.value);
});

document.getElementById("place").addEventListener("change", (event) => {
  state.place = event.target.value;
  applyFilters();
});

document.getElementById("source").addEventListener("change", (event) => {
  state.source = event.target.value;
  applyFilters();
});

document.getElementById("precise").addEventListener("change", (event) => {
  state.preciseOnly = event.target.checked;
  applyFilters();
});

// Every chip group is a [data-filter] container; the AI chip is a separate toggle.
for (const group of document.querySelectorAll("[data-filter]")) {
  group.addEventListener("click", (event) => {
    const chip = event.target.closest(".chip");
    if (!chip) {
      return;
    }
    if (chip.id === "chip-ai") {
      state.aiOnly = !state.aiOnly;
      chip.setAttribute("aria-pressed", String(state.aiOnly));
    } else {
      state[group.dataset.filter] = chip.dataset.value;
      for (const button of group.querySelectorAll(".chip[data-value]")) {
        button.setAttribute("aria-pressed", String(button === chip));
      }
    }
    applyFilters();
  });
}

applyFilters();

// Press "/" to focus search.
addEventListener("keydown", (event) => {
  if (event.key === "/" && document.activeElement.tagName !== "INPUT") {
    event.preventDefault();
    document.getElementById("search").focus();
  }
});

// ---- Listing text: show the whole text, or translate it into Italian.
//
// "Translate to Italian" only ever uses the browser's own translator, which works on this
// device and sends nothing anywhere. If the browser has none, or it fails, the text stays as
// it was and a second, separate button offers Google Translate: the text leaves this page
// only when that button is pressed.

const TARGET_LANGUAGE = "it";
// The online address carries the text; browsers and Google accept about this much.
const ONLINE_TRANSLATION_MAX_ENCODED_CHARS = 3500;
// Some browsers expose the translator but never answer; every wait is limited so nothing hangs.
const AVAILABILITY_TIMEOUT_MS = 3000;
const LANGUAGE_PACK_TIMEOUT_MS = 120000;
const TRANSLATE_PARAGRAPH_TIMEOUT_MS = 20000;
const TRANSLATE_TOTAL_TIMEOUT_MS = 90000;
const translators = new Map();

function withTimeout(promise, milliseconds) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error("timeout")), milliseconds);
    promise.then(
      (value) => { clearTimeout(timer); resolve(value); },
      (error) => { clearTimeout(timer); reject(error); }
    );
  });
}

// Returns the browser's translator, or null when it is missing, unavailable or does not answer.
async function browserTranslator(sourceLanguage, note) {
  if (!("Translator" in self)) {
    return null;
  }
  if (translators.has(sourceLanguage)) {
    return translators.get(sourceLanguage);
  }
  try {
    const options = { sourceLanguage, targetLanguage: TARGET_LANGUAGE };
    const availability = await withTimeout(Translator.availability(options), AVAILABILITY_TIMEOUT_MS);
    if (availability === "unavailable") {
      return null;
    }
    if (availability !== "available") {
      note.textContent = "Downloading the language pack (first use only)...";
    }
    options.monitor = (monitor) => {
      monitor.addEventListener("downloadprogress", (event) => {
        note.textContent = "Downloading the language pack: " + Math.round(event.loaded * 100) + "%";
      });
    };
    const translator = await withTimeout(Translator.create(options), LANGUAGE_PACK_TIMEOUT_MS);
    translators.set(sourceLanguage, translator);
    return translator;
  } catch (error) {
    return null;
  }
}

function paragraphsOf(description) {
  return Array.from(description.querySelectorAll(".desc-text p"));
}

function onlineButtonOf(description) {
  return description.querySelector('[data-action="translate-online"]');
}

function restoreOriginalText(description) {
  for (const paragraph of paragraphsOf(description)) {
    if (paragraph.dataset.original) {
      paragraph.textContent = paragraph.dataset.original;
    }
  }
  description.querySelector(".desc-text").lang = description.dataset.lang;
}

// Translates every paragraph or throws: a half-translated text is never shown as a translation.
async function translateInPlace(translator, description) {
  const startedAt = Date.now();
  let changedParagraphs = 0;
  for (const paragraph of paragraphsOf(description)) {
    if (Date.now() - startedAt > TRANSLATE_TOTAL_TIMEOUT_MS) {
      throw new Error("timeout");
    }
    if (!paragraph.dataset.original) {
      paragraph.dataset.original = paragraph.textContent;
    }
    const original = paragraph.dataset.original;
    const translated = await withTimeout(translator.translate(original), TRANSLATE_PARAGRAPH_TIMEOUT_MS);
    if (typeof translated !== "string" || translated.trim() === "") {
      throw new Error("empty translation");
    }
    if (translated.trim() !== original.trim()) {
      changedParagraphs++;
    }
    paragraph.textContent = translated;
  }
  if (changedParagraphs === 0) {
    throw new Error("nothing was translated");
  }
}

function offerOnlineTranslation(description, note, reason) {
  note.textContent = reason + " You can send the text to Google Translate instead.";
  const onlineButton = onlineButtonOf(description);
  if (onlineButton) {
    onlineButton.hidden = false;
  }
}

async function onTranslateClick(button) {
  const description = button.closest(".desc");
  const note = description.querySelector(".desc-note");
  if (description.dataset.translated === "yes") {
    restoreOriginalText(description);
    description.dataset.translated = "no";
    button.textContent = "Translate to Italian";
    note.textContent = "";
    return;
  }
  button.disabled = true;
  note.textContent = "Preparing the translation...";
  const onlineButton = onlineButtonOf(description);
  if (onlineButton) {
    onlineButton.hidden = true;
  }
  const translator = await browserTranslator(button.dataset.from, note);
  if (translator === null) {
    offerOnlineTranslation(description, note, "This browser cannot translate on this device.");
    button.disabled = false;
    return;
  }
  try {
    await translateInPlace(translator, description);
    description.querySelector(".desc-text").lang = TARGET_LANGUAGE;
    description.dataset.translated = "yes";
    button.textContent = "Show original";
    note.textContent = "Translated on this device.";
  } catch (error) {
    restoreOriginalText(description);
    offerOnlineTranslation(description, note, "The translation did not work.");
  }
  button.disabled = false;
}

// Pressed on purpose: the start of the listing text is sent to Google in the address of a new tab.
function onOnlineTranslateClick(button) {
  const description = button.closest(".desc");
  const note = description.querySelector(".desc-note");
  const text = paragraphsOf(description).map((paragraph) => paragraph.dataset.original || paragraph.textContent).join("\n");
  let encoded = encodeURIComponent(text);
  let shortened = false;
  if (encoded.length > ONLINE_TRANSLATION_MAX_ENCODED_CHARS) {
    shortened = true;
    // Cut at an encoded space so no character is split in half.
    const lastSpace = encoded.lastIndexOf("%20", ONLINE_TRANSLATION_MAX_ENCODED_CHARS);
    if (lastSpace > 0) {
      encoded = encoded.slice(0, lastSpace);
    } else {
      encoded = encoded.slice(0, ONLINE_TRANSLATION_MAX_ENCODED_CHARS);
    }
  }
  const address = "https://translate.google.com/?sl=" + button.dataset.from + "&tl=" + TARGET_LANGUAGE + "&text=" + encoded + "&op=translate";
  window.open(address, "_blank", "noopener,noreferrer");
  if (shortened) {
    note.textContent = "Sent the start of the text to Google Translate (it is too long to send whole).";
  } else {
    note.textContent = "Sent the text to Google Translate.";
  }
}

function onExpandClick(button) {
  const textBox = button.closest(".desc").querySelector(".desc-text");
  const isOpen = textBox.classList.toggle("clamp") === false;
  button.setAttribute("aria-expanded", String(isOpen));
  if (isOpen) {
    button.textContent = "Show less";
  } else {
    button.textContent = "Show full text";
  }
}

grid.addEventListener("click", (event) => {
  const button = event.target.closest(".desc-tools button");
  if (!button) {
    return;
  }
  if (button.dataset.action === "translate") {
    onTranslateClick(button);
  } else if (button.dataset.action === "translate-online") {
    onOnlineTranslateClick(button);
  } else if (button.dataset.action === "expand") {
    onExpandClick(button);
  }
});
