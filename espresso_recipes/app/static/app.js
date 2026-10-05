const base = document.body.dataset.base;

// Selects with an "Add new…" / "Other…" entry reveal a text input for it.
for (const select of document.querySelectorAll("select[data-reveal]")) {
  const input = document.getElementById(select.dataset.reveal);
  const sync = (focus) => {
    input.hidden = !["new", "other"].includes(select.value);
    if (focus && !input.hidden) input.focus();
  };
  select.addEventListener("change", () => sync(true));
  sync(false);
}

for (const button of document.querySelectorAll("[data-confirm]")) {
  button.addEventListener("click", (event) => {
    if (!confirm(button.dataset.confirm)) event.preventDefault();
  });
}

for (const time of document.querySelectorAll("time[datetime]")) {
  const date = new Date(time.dateTime);
  if (!isNaN(date)) {
    time.textContent = date.toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
  }
}

const search = document.getElementById("search");
if (search) {
  search.addEventListener("input", () => {
    const query = search.value.trim().toLowerCase();
    let visible = 0;
    for (const group of document.querySelectorAll(".group")) {
      let inGroup = 0;
      for (const card of group.querySelectorAll(".card")) {
        card.hidden = !card.textContent.toLowerCase().includes(query);
        if (!card.hidden) inGroup++;
      }
      group.hidden = inGroup === 0;
      visible += inGroup;
    }
    document.getElementById("no-match").hidden = visible > 0 || !query;
  });
}

// The machine is usually off, so the profile list is a cache refreshed in the background.
const profileSelect = document.getElementById("profile");
if (profileSelect) {
  const status = document.getElementById("profile-status");
  const refresh = async (manual) => {
    if (manual) status.textContent = "Asking the machine…";
    let result;
    try {
      const response = await fetch(`${base}/profiles/refresh`, { method: "POST" });
      result = await response.json();
    } catch {
      if (manual) status.textContent = "Refresh failed.";
      return;
    }
    const selected = profileSelect.value;
    for (const option of profileSelect.querySelectorAll("option")) {
      if (/^\d+$/.test(option.value)) option.remove();
    }
    const other = profileSelect.querySelector('option[value="other"]');
    for (const profile of result.profiles) {
      other.before(new Option(profile.name, profile.id));
    }
    profileSelect.value = selected;
    if (manual) status.textContent = result.ok ? "Profiles updated." : `${result.error}. Showing saved profiles.`;
  };
  document.getElementById("refresh-profiles").addEventListener("click", () => refresh(true));
  refresh(false);
}
