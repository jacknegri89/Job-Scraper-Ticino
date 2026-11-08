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
