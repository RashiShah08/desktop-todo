/* ─────────────────────────────────────────────────────────────
   Frontend logic — talks to Python via window.pywebview.api.
   Faithfully renders the Figma design.
─────────────────────────────────────────────────────────── */

const PRIORITY_COLORS = {
  none: "transparent",
  low: "#5B8FA8",
  medium: "#C4A24A",
  high: "#D4845A",
};

const CATEGORY_STYLES = {
  Work:     { fg: "#6390B8", bg: "rgba(99,144,184,0.14)" },
  Personal: { fg: "#A07A80", bg: "rgba(160,122,128,0.14)" },
  College:  { fg: "#7A9E6A", bg: "rgba(122,158,106,0.14)" },
  Learning: { fg: "#7A9E6A", bg: "rgba(122,158,106,0.14)" },   // alias for old data
};
const CATEGORY_ORDER = ["Work", "Personal", "College"];

const BUCKET_ACCENT = {
  Overdue:    "#C44040",
  Today:      "#D4845A",
  Tomorrow:   "#C4A24A",
  "This week":"#6390B8",
  Later:      "#6A8A6A",
  Someday:    "#5A5650",
};

const BUCKET_ORDER = ["Overdue", "Today", "Tomorrow", "This week", "Later", "Someday"];

// ─── State ──────────────────────────────────────────────────
let state = {
  tab: "tasks",
  tasks: [],
  doneItems: [],
  news: [],
  newsTime: null,
  gcalConnected: false,
  creating: false,                // full create-form mode
  editing: null,                  // task id being edited, null otherwise
  formFirstRender: false,         // true → next form render auto-focuses the task name input
  viewingDone: false,             // done-list sub-view inside tasks tab
  notes: "",                      // free-form scratchpad text
  notesLoaded: false,
  collapsedBuckets: new Set(),
  search: "",                     // active search filter (lowercase trimmed)
  stats: null,                    // {done_today, done_week, done_total, current_streak, longest_streak}
  focusSession: null,             // {taskId, taskName, totalSec, remainingSec, paused, intervalId}
  // Draft state for the create form
  form: {
    name: "",
    category: "Work",
    priority: "none",
    dueDate: "",          // YYYY-MM-DD
    dueTime: "",          // HH:MM
    reminderPreset: null, // "1d" / "1h" / "30m" / "custom" / null
    remDate: "",
    remTime: "",
    recurrence: "none",   // none / daily / weekdays / weekly / monthly / custom
    recurrenceDays: [],   // [0..6] weekday ints when recurrence === "custom"
    attendees: [],        // ["alice@gmail.com", ...] — sent as GCal event attendees
    attendeeDraft: "",    // what's currently typed in the pill input
  },
  upcoming: [],
};

function resetForm() {
  state.form = {
    name: "", category: "Work", priority: "none",
    dueDate: "", dueTime: "",
    reminderPreset: null, remDate: "", remTime: "",
    recurrence: "none", recurrenceDays: [],
    attendees: [], attendeeDraft: "",
  };
}

// ─── Date helpers ───────────────────────────────────────────
function parseDate(s) {
  // "YYYY-MM-DD" → Date at local midnight
  const [y, m, d] = s.split("-").map(Number);
  return new Date(y, m - 1, d);
}
function startOfDay(d) { return new Date(d.getFullYear(), d.getMonth(), d.getDate()); }
function sameDay(a, b) {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}
function isTomorrow(d) {
  const t = new Date();
  t.setDate(t.getDate() + 1);
  return sameDay(d, t);
}
function isThisWeek(d) {
  const now = startOfDay(new Date());
  const day = now.getDay() || 7;       // Mon = 1 ... Sun = 7
  const monday = new Date(now); monday.setDate(now.getDate() - (day - 1));
  const sunday = new Date(monday); sunday.setDate(monday.getDate() + 6);
  const dd = startOfDay(d);
  return dd >= monday && dd <= sunday;
}
function fmtMonthDay(d) {
  return d.toLocaleString(undefined, { month: "short", day: "numeric" });
}
function getBucket(task) {
  if (!task.dueDate) return "Someday";
  const due = startOfDay(parseDate(task.dueDate));
  const today = startOfDay(new Date());
  if (due < today) return "Overdue";
  if (sameDay(due, today)) return "Today";
  if (isTomorrow(due)) return "Tomorrow";
  if (isThisWeek(due)) return "This week";
  const diffDays = (due - today) / (1000 * 60 * 60 * 24);
  if (diffDays <= 30) return "Later";
  return "Someday";
}
function groupTasks(tasks) {
  const groups = new Map();
  BUCKET_ORDER.forEach(b => groups.set(b, []));
  tasks.forEach(t => groups.get(getBucket(t)).push(t));
  groups.forEach(list => {
    list.sort((a, b) => {
      if (!a.dueDate && !b.dueDate) return 0;
      if (!a.dueDate) return 1;
      if (!b.dueDate) return -1;
      return (a.dueDate + (a.dueTime || "00:00")).localeCompare(b.dueDate + (b.dueTime || "00:00"));
    });
  });
  return new Map(BUCKET_ORDER.filter(b => groups.get(b).length > 0).map(b => [b, groups.get(b)]));
}

// ─── SVG icons (small, inline, no extra deps) ───────────────
const ICON = {
  chevronDown: '<svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><polyline points="6 9 12 15 18 9"/></svg>',
  chevronRight: '<svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><polyline points="9 6 15 12 9 18"/></svg>',
  calendar: '<svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>',
  clock: '<svg width="8" height="8" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>',
  bell: '<svg width="8" height="8" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>',
  check: '<svg width="8" height="6" viewBox="0 0 8 6" fill="none"><path d="M1 3L3 5L7 1" stroke="white" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  checkDone: '<svg width="8" height="6" viewBox="0 0 8 6" fill="none"><path d="M1 3L3 5L7 1" stroke="#4A8064" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  gcalSmall: '<svg width="7" height="7" viewBox="0 0 7 7" fill="none"><circle cx="3.5" cy="3.5" r="2.5" stroke="#4285F4" stroke-width="1"/><path d="M3.5 2v1.5l1 0.7" stroke="#4285F4" stroke-width="0.8" stroke-linecap="round"/></svg>',
  gcalLarge: '<svg width="12" height="12" viewBox="0 0 12 12" fill="none"><rect x="1" y="2" width="10" height="9" rx="1.5" stroke="#4285F4" stroke-width="1"/><path d="M1 5h10" stroke="#4285F4" stroke-width="1"/><path d="M4 1v2M8 1v2" stroke="#4285F4" stroke-width="1" stroke-linecap="round"/><rect x="3.5" y="6.5" width="2" height="2" rx="0.5" fill="#4285F4" opacity="0.7"/></svg>',
  emptyIcon: '<svg width="28" height="28" viewBox="0 0 28 28" fill="none"><circle cx="14" cy="14" r="13" stroke="rgba(255,255,255,0.08)" stroke-width="1.5"/><path d="M9 14h10M14 9v10" stroke="rgba(255,255,255,0.12)" stroke-width="1.5" stroke-linecap="round"/></svg>',
  focus: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><polyline points="12 7 12 12 15.5 14"/></svg>',
};

// ─── Render: task row ───────────────────────────────────────
function renderTaskRow(task) {
  const hasMeta = !!(task.dueDate || task.reminderDate);
  const isOverdueDate = task.dueDate &&
    startOfDay(parseDate(task.dueDate)) < startOfDay(new Date());

  const catStyle = CATEGORY_STYLES[task.category] || CATEGORY_STYLES.Work;

  const row = document.createElement("div");
  row.className = "task-row task-row-editable" + (hasMeta ? " has-meta" : "");
  row.addEventListener("click", () => enterEdit(task));

  // Checkbox
  const cb = document.createElement("button");
  cb.type = "button";                                   // avoid native submit weirdness
  cb.className = "checkbox" + (task.completed ? " checked" : "");
  if (task.completed) cb.innerHTML = ICON.check;
  cb.addEventListener("click", (e) => {
    e.stopPropagation();
    e.preventDefault();
    // Optimistic UI: flip the visual immediately so user sees feedback
    cb.classList.add("checked");
    cb.innerHTML = ICON.check;
    // For recurring tasks, tell the user when the next one will appear
    if (task.recurrence && task.recurrence !== "none") {
      const nxt = predictNextDate(task.dueDate, task.recurrence);
      const when = nxt ? prettyDateFull(nxt) : "tomorrow";
      showToast(`✓ ${task.name} · returns ${when}`);
    }
    pyToggleTask(task.id);
  });
  row.appendChild(cb);

  // Body
  const body = document.createElement("div");
  body.className = "task-body";

  const name = document.createElement("p");
  name.className = "task-name" + (task.completed ? " completed" : "");
  name.textContent = task.name;
  // Subtask progress pill, e.g. "2/5"
  const subs = task.subtasks || [];
  if (subs.length) {
    const done = subs.filter(s => s.done).length;
    const pill = document.createElement("span");
    pill.className = "subtask-progress"
      + (done === subs.length ? " subtask-progress-done" : "");
    pill.textContent = `${done}/${subs.length}`;
    name.appendChild(document.createTextNode(" "));
    name.appendChild(pill);
  }
  body.appendChild(name);

  // Tags row
  const tags = document.createElement("div");
  tags.className = "task-tags";
  const chip = document.createElement("span");
  chip.className = "category-chip";
  chip.style.color = catStyle.fg;
  chip.style.background = catStyle.bg;
  chip.textContent = task.category;
  tags.appendChild(chip);
  if (task.gcalEventId) {
    const gcalDot = document.createElement("span");
    gcalDot.className = "gcal-dot";
    gcalDot.title = "Linked to Google Calendar";
    gcalDot.innerHTML = ICON.gcalSmall;
    tags.appendChild(gcalDot);
  }
  if (task.recurrence && task.recurrence !== "none") {
    const rep = document.createElement("span");
    rep.className = "recurrence-badge";
    const desc = recurrenceDescription(task.recurrence, task.recurrenceDays);
    rep.title = desc;
    // Short label on the row — full description on hover
    rep.textContent = "↻ " + (task.recurrence === "custom"
      ? (task.recurrenceDays || []).map(i => _DAY_NAMES_SHORT[i].toLowerCase()[0]).join("")
      : task.recurrence);
    tags.appendChild(rep);
  }
  if (task.focusMinutesTotal > 0) {
    const focusBadge = document.createElement("span");
    focusBadge.className = "recurrence-badge";
    focusBadge.title = `${task.focusMinutesTotal} min focused on this task`;
    focusBadge.textContent = "⏱ " + fmtFocusTotal(task.focusMinutesTotal);
    tags.appendChild(focusBadge);
  }
  // Tiny avatar dots for attendees — first letter, full email on hover
  const att = task.attendees || [];
  if (att.length) {
    const avatars = document.createElement("span");
    avatars.className = "attendee-avatars";
    avatars.title = att.join(", ");
    att.slice(0, 3).forEach(email => {
      const a = document.createElement("span");
      a.className = "attendee-avatar";
      a.textContent = (email[0] || "?").toUpperCase();
      a.title = email;
      avatars.appendChild(a);
    });
    if (att.length > 3) {
      const more = document.createElement("span");
      more.className = "attendee-avatar attendee-avatar-more";
      more.textContent = `+${att.length - 3}`;
      avatars.appendChild(more);
    }
    tags.appendChild(avatars);
  }
  body.appendChild(tags);

  // Due meta
  if (hasMeta) {
    const meta = document.createElement("div");
    meta.className = "due-meta";
    if (task.dueDate) {
      const pill = document.createElement("span");
      pill.className = "meta-pill" + (isOverdueDate ? " overdue" : "");
      pill.style.color = isOverdueDate ? "#C44040" : "#4E4A46";
      let html = ICON.calendar + " " + fmtMonthDay(parseDate(task.dueDate));
      if (task.dueTime) html += " " + ICON.clock + " " + task.dueTime;
      pill.innerHTML = html;
      meta.appendChild(pill);
    }
    if (task.reminderDate) {
      const pill = document.createElement("span");
      pill.className = "meta-pill";
      pill.style.color = "#5A5650";
      let html = ICON.bell + " " + fmtMonthDay(parseDate(task.reminderDate));
      if (task.reminderTime) html += " " + task.reminderTime;
      pill.innerHTML = html;
      meta.appendChild(pill);
    }
    body.appendChild(meta);
  }

  // Inline subtask list (capped to keep rows compact)
  const subList_items = task.subtasks || [];
  if (subList_items.length) {
    const subList = document.createElement("div");
    subList.className = "task-subtasks";
    const VISIBLE = 3;
    subList_items.slice(0, VISIBLE).forEach(s => {
      const r = document.createElement("div");
      r.className = "task-subtask" + (s.done ? " task-subtask-done" : "");
      r.addEventListener("click", async (e) => {
        e.stopPropagation();
        await safeCall("toggle_subtask", task.id, s.id);
        await refreshData();
      });
      const cb2 = document.createElement("span");
      cb2.className = "task-subtask-cb" + (s.done ? " checked" : "");
      if (s.done) cb2.innerHTML = ICON.check;
      r.appendChild(cb2);
      const txt = document.createElement("span");
      txt.className = "task-subtask-txt";
      txt.textContent = s.text;
      r.appendChild(txt);
      subList.appendChild(r);
    });
    if (subList_items.length > VISIBLE) {
      const more = document.createElement("div");
      more.className = "task-subtask-more";
      more.textContent = `+${subList_items.length - VISIBLE} more`;
      subList.appendChild(more);
    }
    body.appendChild(subList);
  }

  row.appendChild(body);

  // Focus button — starts a Pomodoro-style session on this task
  if (!task.completed) {
    const focusBtn = document.createElement("button");
    focusBtn.type = "button";
    focusBtn.className = "focus-btn";
    focusBtn.title = "Start a focus session";
    focusBtn.innerHTML = ICON.focus;
    focusBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      e.preventDefault();
      if (state.focusSession) {
        showToast("Finish or end your current focus session first");
        return;
      }
      openFocusPicker(task);
    });
    row.appendChild(focusBtn);
  }

  // Priority dot
  if (task.priority && task.priority !== "none") {
    const dot = document.createElement("span");
    dot.className = "priority-dot";
    dot.style.background = PRIORITY_COLORS[task.priority];
    row.appendChild(dot);
  }
  return row;
}

// Quickly predict the next due-date locally — same logic as the Python
// `next_due_date`, used to populate the toast before refreshData lands.
function predictNextDate(iso, recurrence) {
  if (!iso || !recurrence || recurrence === "none") return null;
  const [y, m, d] = iso.split("-").map(Number);
  const dt = new Date(y, m - 1, d);
  if (recurrence === "daily") dt.setDate(dt.getDate() + 1);
  else if (recurrence === "weekly") dt.setDate(dt.getDate() + 7);
  else if (recurrence === "weekdays") {
    dt.setDate(dt.getDate() + 1);
    while (dt.getDay() === 0 || dt.getDay() === 6) dt.setDate(dt.getDate() + 1);
  } else if (recurrence === "monthly") {
    const targetMonth = dt.getMonth() + 1;
    const day = dt.getDate();
    dt.setMonth(targetMonth);
    if (dt.getMonth() !== targetMonth % 12) {
      // Clipped (e.g. Jan 31 → Mar 3). Roll back to last day of intended month.
      dt.setDate(0);
    }
    // Restore original day if possible
    const lastOfMonth = new Date(dt.getFullYear(), dt.getMonth() + 1, 0).getDate();
    dt.setDate(Math.min(day, lastOfMonth));
  }
  return isoFromDate(dt);
}

// ─── Render: bucket section ─────────────────────────────────
function renderBucket(bucket, tasks) {
  const wrap = document.createElement("div");
  const collapsed = state.collapsedBuckets.has(bucket);
  const accent = BUCKET_ACCENT[bucket];

  const header = document.createElement("button");
  header.className = "bucket-header";
  header.addEventListener("click", () => {
    if (collapsed) state.collapsedBuckets.delete(bucket);
    else state.collapsedBuckets.add(bucket);
    render();
  });

  const chev = document.createElement("span");
  chev.className = "bucket-chevron";
  chev.style.color = accent;
  chev.innerHTML = collapsed ? ICON.chevronRight : ICON.chevronDown;
  header.appendChild(chev);

  const label = document.createElement("span");
  label.className = "bucket-label";
  label.style.color = accent;
  label.textContent = bucket;
  header.appendChild(label);

  const count = document.createElement("span");
  count.className = "bucket-count";
  count.style.color = accent;
  count.style.background = hexA(accent, 0.125);
  count.textContent = tasks.length;
  header.appendChild(count);

  wrap.appendChild(header);

  if (!collapsed) {
    tasks.forEach(t => wrap.appendChild(renderTaskRow(t)));
  }
  return wrap;
}

function hexA(hex, alpha) {
  // "#RRGGBB" → "rgba(r,g,b,a)"
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}

// ─── Render: news / done / empty ────────────────────────────
function renderNewsRow(item) {
  const row = document.createElement("div");
  row.className = "news-row";
  row.addEventListener("click", () => pyOpenUrl(item.url));
  row.innerHTML = `
    <div class="news-meta">
      <span class="news-source">${escapeHtml(item.source)}</span>
      <span class="news-time">${escapeHtml(item.time || "")}</span>
    </div>
    <p class="news-headline">${escapeHtml(item.headline)}</p>
  `;
  return row;
}

function renderDoneRow(task) {
  const catStyle = CATEGORY_STYLES[task.category] || CATEGORY_STYLES.Work;
  const row = document.createElement("div");
  row.className = "done-row";
  row.innerHTML = `
    <div class="done-fill">${ICON.checkDone}</div>
    <div class="done-body">
      <p class="done-name">${escapeHtml(task.name)}</p>
      <div class="done-meta">
        <span class="category-chip" style="color:${catStyle.fg};background:${catStyle.bg}">${task.category}</span>
        ${task.gcalEventId ? `<span class="gcal-dot">${ICON.gcalSmall}</span>` : ""}
        ${task.dueDate ? `<span style="font-size:10px;color:#3A3630;display:flex;align-items:center;gap:2px">${ICON.calendar} ${fmtMonthDay(parseDate(task.dueDate))}</span>` : ""}
        ${task.focusMinutesTotal > 0 ? `<span class="recurrence-badge">⏱ ${fmtFocusTotal(task.focusMinutesTotal)}</span>` : ""}
      </div>
    </div>`;
  return row;
}

function renderEmpty(message) {
  const el = document.createElement("div");
  el.className = "empty";
  el.innerHTML = `${ICON.emptyIcon}<p class="empty-text">${escapeHtml(message)}</p>`;
  return el;
}

function renderGcalBanner() {
  const b = document.createElement("div");
  b.className = "gcal-banner";
  b.innerHTML = `
    <div class="gcal-banner-icon">${ICON.gcalLarge}</div>
    <div class="gcal-banner-text">
      <p class="gcal-banner-title">Connect Google Calendar</p>
      <p class="gcal-banner-sub">Sync tasks with your events</p>
    </div>
    <button class="gcal-banner-btn">Connect</button>`;
  b.querySelector("button").addEventListener("click", () => pyConnectGcal());
  return b;
}

// ─── Task form (create OR edit) ─────────────────────────────
function renderTaskForm() {
  const isEdit = !!state.editing;
  const f = document.createElement("div");
  f.className = "create-form";

  // ── Header
  const head = document.createElement("div");
  head.className = "form-head";
  head.innerHTML = `
    <button type="button" class="form-back" id="form-back">← back</button>
    <span class="form-title">${isEdit ? "edit task" : "new task"}</span>
    <button type="button" class="form-save" id="form-save">save</button>`;
  f.appendChild(head);

  // ── TASK
  f.appendChild(formSection("", () => {
    const wrap = document.createElement("div");
    const input = document.createElement("input");
    input.className = "form-input form-input-hero";
    input.placeholder = "What needs doing?";
    input.value = state.form.name;
    input.addEventListener("input", (e) => state.form.name = e.target.value);
    input.addEventListener("keydown", (e) => {
      if (e.key === "Escape") cancelCreate();
    });
    // Only focus the TASK input on the FIRST render after opening the form
    // (a fresh Add or Edit). On chip clicks / picker selections re-rendering
    // the form, leave focus where the user put it — focusing the input here
    // would make the browser scroll-into-view and snap the page to the top.
    if (state.formFirstRender) {
      state.formFirstRender = false;
      setTimeout(() => input.focus(), 0);
    }
    wrap.appendChild(input);
    return wrap;
  }));

  // ── TYPE
  f.appendChild(formSection("TYPE", () => {
    return chipRow(
      CATEGORY_ORDER.map(c => ({
        value: c, label: c,
        fg: CATEGORY_STYLES[c].fg, bg: CATEGORY_STYLES[c].bg,
      })),
      state.form.category,
      v => { state.form.category = v; renderForm(); },
    );
  }));

  // ── PRIORITY
  f.appendChild(formSection("PRIORITY", () => {
    return chipRow(
      [
        { value: "none",   label: "none", fg: "#8A8480", bg: "rgba(255,255,255,0.04)" },
        { value: "low",    label: "low",  fg: "#5B8FA8", bg: "rgba(91,143,168,0.14)" },
        { value: "medium", label: "med",  fg: "#C4A24A", bg: "rgba(196,162,74,0.14)" },
        { value: "high",   label: "high", fg: "#D4845A", bg: "rgba(212,132,90,0.14)" },
      ],
      state.form.priority,
      v => { state.form.priority = v; renderForm(); },
    );
  }));

  // ── DUE — custom date + time picker buttons
  f.appendChild(formSection("DUE DATE & TIME", () => {
    const row = document.createElement("div");
    row.className = "form-row";

    const dateBtn = pickerButton(
      state.form.dueDate ? prettyDateFull(state.form.dueDate) : "pick date",
      "form-date",
      () => openDatePicker(state.form.dueDate, picked => {
        state.form.dueDate = picked;
        applyReminderPreset();
        renderForm();
      }),
    );
    row.appendChild(dateBtn);

    const timeBtn = pickerButton(
      state.form.dueTime ? prettyTime(state.form.dueTime) : "pick time",
      "form-time",
      () => openTimePicker(state.form.dueTime, picked => {
        state.form.dueTime = picked;
        applyReminderPreset();
        renderForm();
      }),
    );
    row.appendChild(timeBtn);

    return row;
  }));

  // ── REPEAT
  f.appendChild(formSection("REPEAT", () => {
    const wrap = document.createElement("div");
    wrap.className = "repeat-wrap";
    const chips = chipRow(
      [
        { value: "none",     label: "none",     fg: "#8A8480", bg: "rgba(255,255,255,0.04)" },
        { value: "daily",    label: "daily",    fg: "#D4845A", bg: "rgba(212,132,90,0.14)" },
        { value: "weekdays", label: "weekdays", fg: "#D4845A", bg: "rgba(212,132,90,0.14)" },
        { value: "weekly",   label: "weekly",   fg: "#D4845A", bg: "rgba(212,132,90,0.14)" },
        { value: "monthly",  label: "monthly",  fg: "#D4845A", bg: "rgba(212,132,90,0.14)" },
        { value: "custom",   label: "custom",   fg: "#D4845A", bg: "rgba(212,132,90,0.14)" },
      ],
      state.form.recurrence,
      v => {
        // First mark the row so styles know this is the REPEAT row — done
        // after construction below.
        state.form.recurrence = v;
        // For "custom", pre-fill recurrenceDays with today's weekday so the
        // user sees one selected day instead of an empty grid.
        if (v === "custom" && state.form.recurrenceDays.length === 0) {
          const today = new Date();
          // JS Sunday=0..Sat=6  →  ISO Mon=0..Sun=6
          const isoWeekday = (today.getDay() + 6) % 7;
          state.form.recurrenceDays = [isoWeekday];
        }
        if (v !== "custom") {
          // Clear day picker selections — they're meaningless outside custom
          state.form.recurrenceDays = [];
        }
        if (v && v !== "none" && !state.form.dueDate) {
          state.form.dueDate = firstOccurrenceFor(v);
        }
        applyReminderPreset();
        renderForm();
      },
    );
    chips.classList.add("chip-row-repeat");
    wrap.appendChild(chips);

    // 7-day toggle picker, only for "custom"
    if (state.form.recurrence === "custom") {
      const dayWrap = document.createElement("div");
      dayWrap.className = "weekday-picker";
      ["M", "T", "W", "T", "F", "S", "S"].forEach((label, i) => {
        const cell = document.createElement("button");
        cell.type = "button";
        cell.className = "weekday-cell";
        if (state.form.recurrenceDays.includes(i)) cell.classList.add("weekday-on");
        if (i >= 5) cell.classList.add("weekday-weekend");
        cell.textContent = label;
        cell.addEventListener("click", (e) => {
          e.preventDefault();
          const has = state.form.recurrenceDays.includes(i);
          state.form.recurrenceDays = has
            ? state.form.recurrenceDays.filter(x => x !== i)
            : [...state.form.recurrenceDays, i].sort();
          renderForm();
        });
        dayWrap.appendChild(cell);
      });
      wrap.appendChild(dayWrap);
    }

    // Helpful hint when a recurrence is set
    if (state.form.recurrence && state.form.recurrence !== "none") {
      const hint = document.createElement("div");
      hint.className = "form-hint form-hint-info";
      const startStr = state.form.dueDate ? prettyDateFull(state.form.dueDate) : "today";
      const descr = recurrenceDescription(state.form.recurrence, state.form.recurrenceDays);
      hint.textContent = `${descr} · starts ${startStr} · syncs to Google Calendar`;
      wrap.appendChild(hint);
    }
    return wrap;
  }));

  // ── REMIND ME
  f.appendChild(formSection("REMIND ME", () => {
    const wrap = document.createElement("div");
    wrap.className = "reminder-wrap";
    const dueSet = !!state.form.dueDate;
    const presets = [
      { value: "1d",     label: "1 day" },
      { value: "1h",     label: "1 hr"  },
      { value: "30m",    label: "30 min" },
      { value: "custom", label: "custom" },
    ];
    const chips = chipRow(
      presets.map(p => ({
        value: p.value, label: p.label,
        fg: "#D4845A", bg: "rgba(212,132,90,0.14)",
      })),
      state.form.reminderPreset,
      v => {
        if (state.form.reminderPreset === v) {
          // Tap again to clear
          state.form.reminderPreset = null;
          state.form.remDate = ""; state.form.remTime = "";
        } else {
          state.form.reminderPreset = v;
          applyReminderPreset();
        }
        renderForm();
      },
    );
    chips.classList.add("chip-row-reminder");
    wrap.appendChild(chips);

    // Hint when due not set
    if (!dueSet && state.form.reminderPreset && state.form.reminderPreset !== "custom") {
      const hint = document.createElement("div");
      hint.className = "form-hint";
      hint.textContent = "set a due date above first";
      wrap.appendChild(hint);
    }

    if (state.form.reminderPreset === "custom") {
      // Roomy card with stacked, full-width pickers
      const card = document.createElement("div");
      card.className = "reminder-custom-card";

      const cap = document.createElement("div");
      cap.className = "reminder-sub-cap";
      cap.textContent = "REMIND ME AT";
      card.appendChild(cap);

      card.appendChild(pickerButton(
        state.form.remDate ? prettyDateFull(state.form.remDate) : "pick date",
        "form-date reminder-picker",
        () => openDatePicker(state.form.remDate, picked => {
          state.form.remDate = picked;
          renderForm();
        }),
      ));
      card.appendChild(pickerButton(
        state.form.remTime ? prettyTime(state.form.remTime) : "pick time",
        "form-time reminder-picker",
        () => openTimePicker(state.form.remTime, picked => {
          state.form.remTime = picked;
          renderForm();
        }),
      ));

      // Clear-link to wipe both
      if (state.form.remDate || state.form.remTime) {
        const clear = document.createElement("button");
        clear.className = "reminder-clear";
        clear.textContent = "clear";
        clear.addEventListener("click", () => {
          state.form.remDate = ""; state.form.remTime = "";
          renderForm();
        });
        card.appendChild(clear);
      }

      wrap.appendChild(card);
    } else if (state.form.reminderPreset && state.form.remDate) {
      // Show the computed reminder time as a styled callout
      const line = document.createElement("div");
      line.className = "reminder-computed";
      const niceTime = state.form.remTime ? ` · ${prettyTime(state.form.remTime)}` : "";
      line.innerHTML = `<span class="reminder-arrow">↳</span> pings ${prettyDateFull(state.form.remDate)}${niceTime}`;
      wrap.appendChild(line);
    }
    return wrap;
  }));

  // ── WITH (attendees) — sits below the essentials; it's the least-used field
  f.appendChild(formSection("WITH", () => renderAttendeesSection()));

  // Subtasks (edit mode only — we need a saved task id to attach them)
  if (isEdit) {
    f.appendChild(renderSubtaskSection());
  }

  // Danger zone (edit only)
  if (isEdit) {
    const danger = document.createElement("div");
    danger.className = "form-danger";
    danger.innerHTML = `<button type="button" class="form-delete" id="form-delete">delete this task</button>`;
    f.appendChild(danger);
  }

  // Wire header buttons
  setTimeout(() => {
    document.getElementById("form-back")?.addEventListener(
      "click", isEdit ? cancelEdit : cancelCreate);
    document.getElementById("form-save")?.addEventListener(
      "click", isEdit ? submitEdit : submitCreate);
    document.getElementById("form-delete")?.addEventListener("click", submitDelete);
  }, 0);

  return f;
}

// Build a labelled section
function formSection(caption, builder) {
  const sec = document.createElement("div");
  sec.className = "form-section";
  if (caption) {
    const lbl = document.createElement("div");
    lbl.className = "form-caption";
    lbl.textContent = caption;
    sec.appendChild(lbl);
  }
  sec.appendChild(builder());
  return sec;
}

// Build a chip row that shares horizontal space evenly
function chipRow(options, currentValue, onSelect) {
  const row = document.createElement("div");
  row.className = "chip-row";
  options.forEach(opt => {
    const btn = document.createElement("button");
    btn.type = "button";                              // never submit; never auto-scroll
    btn.className = "chip";
    btn.textContent = opt.label;
    if (opt.value === currentValue) {
      btn.classList.add("chip-active");
      btn.style.background = opt.fg;
      btn.style.color = "#fff";
    } else {
      btn.style.background = opt.bg;
      btn.style.color = opt.fg;
    }
    btn.addEventListener("click", (e) => {
      e.preventDefault();
      onSelect(opt.value);
    });
    row.appendChild(btn);
  });
  return row;
}

function prettyDate(yyyyMmDd) {
  if (!yyyyMmDd) return "";
  try {
    const [y, m, d] = yyyyMmDd.split("-").map(Number);
    const dt = new Date(y, m - 1, d);
    return dt.toLocaleString(undefined, { month: "short", day: "numeric" });
  } catch (_) { return yyyyMmDd; }
}

function prettyDateFull(yyyyMmDd) {
  if (!yyyyMmDd) return "";
  try {
    const [y, m, d] = yyyyMmDd.split("-").map(Number);
    const dt = new Date(y, m - 1, d);
    return dt.toLocaleString(undefined, { weekday: "short", month: "short", day: "numeric" });
  } catch (_) { return yyyyMmDd; }
}

function isoFromDate(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

// First occurrence date for a recurrence — today, or the next weekday
// when "weekdays" is picked on a Saturday/Sunday.
function firstOccurrenceFor(recurrence) {
  const t = new Date();
  if (recurrence === "weekdays") {
    while (t.getDay() === 0 || t.getDay() === 6) t.setDate(t.getDate() + 1);
  }
  return isoFromDate(t);
}

const _DAY_NAMES_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

// Human-readable description of a recurrence — used in form hints and badges.
function recurrenceDescription(recurrence, days) {
  if (!recurrence || recurrence === "none") return "";
  if (recurrence === "daily")    return "Every day";
  if (recurrence === "weekdays") return "Mon to Fri";
  if (recurrence === "weekly")   return "Every week";
  if (recurrence === "monthly")  return "Every month";
  if (recurrence === "custom") {
    const arr = Array.isArray(days) ? days : [];
    if (arr.length === 0) return "Pick days below";
    if (arr.length === 7) return "Every day";
    return "Every " + arr.map(i => _DAY_NAMES_SHORT[i]).join(", ");
  }
  return recurrence;
}

function prettyTime(hhMm) {
  if (!hhMm) return "";
  const [h, m] = hhMm.split(":").map(Number);
  const ampm = h < 12 ? "AM" : "PM";
  const h12 = h % 12 || 12;
  return `${h12}:${String(m).padStart(2, "0")} ${ampm}`;
}

// ─── Reusable picker button ─────────────────────────────────
function pickerButton(label, extraClass, onClick) {
  const b = document.createElement("button");
  b.className = "picker-btn " + (extraClass || "");
  // Pick the right glyph automatically from the variant class.
  const isTime = (extraClass || "").includes("time");
  const icon = isTime ? ICON.clock : ICON.calendar;
  b.innerHTML = `<span class="picker-icon">${icon}</span><span class="picker-label">${escapeHtml(label)}</span>`;
  b.addEventListener("click", (e) => { e.preventDefault(); onClick(); });
  return b;
}

// ─── Modal overlay framework ────────────────────────────────
function openOverlay(buildContent) {
  // Remove any existing overlay
  document.querySelectorAll(".overlay").forEach(o => o.remove());

  const back = document.createElement("div");
  back.className = "overlay";
  const panel = document.createElement("div");
  panel.className = "overlay-panel";

  back.addEventListener("click", (e) => {
    if (e.target === back) closeOverlay();
  });

  const close = () => closeOverlay();
  panel.appendChild(buildContent(close));
  back.appendChild(panel);
  document.body.appendChild(back);

  // Fade in
  requestAnimationFrame(() => back.classList.add("overlay-shown"));
}

function closeOverlay() {
  const o = document.querySelector(".overlay");
  if (!o) return;
  o.classList.remove("overlay-shown");
  setTimeout(() => o.remove(), 140);
}

// ─── Focus Mode ──────────────────────────────────────────────
const FOCUS_PRESETS = [
  { value: 25, label: "25 min" },
  { value: 45, label: "45 min" },
  { value: 60, label: "60 min" },
  { value: -1, label: "custom" },
];

function openFocusPicker(task) {
  let chosenMinutes = 25;
  let customMode = false;

  openOverlay((close) => {
    const root = document.createElement("div");
    root.className = "picker-card";

    const head = document.createElement("div");
    head.className = "picker-head picker-head-simple";
    head.innerHTML = `<span class="picker-time-display">Focus on “${escapeHtml(task.name)}”</span>`;
    root.appendChild(head);

    const body = document.createElement("div");
    root.appendChild(body);

    function startNow() {
      if (!(chosenMinutes > 0)) return;
      close();
      startFocusSession(task, chosenMinutes);
    }

    function syncStartLabel() {
      const btn = body.querySelector('[data-act="start"]');
      if (btn) btn.textContent = `start ${chosenMinutes}m`;
    }

    function rebuild() {
      body.innerHTML = "";

      body.appendChild(chipRow(
        FOCUS_PRESETS.map(p => ({
          value: p.value, label: p.label,
          fg: "#D4845A", bg: "rgba(212,132,90,0.14)",
        })),
        customMode ? -1 : chosenMinutes,
        v => {
          customMode = (v === -1);
          if (!customMode) chosenMinutes = v;
          rebuild();
        },
      ));

      // Custom duration is an inline field, never a native prompt() — a
      // system dialog in a webview is labelled with the page origin, which
      // looks broken inside a styled app.
      if (customMode) {
        const row = document.createElement("div");
        row.className = "focus-custom-row";
        const input = document.createElement("input");
        input.type = "number";
        input.className = "form-input focus-custom-input";
        input.min = "1";
        input.max = "600";
        input.value = String(chosenMinutes);
        input.addEventListener("input", () => {
          const n = parseInt(input.value, 10);
          chosenMinutes = (n > 0) ? Math.min(n, 600) : 0;
          syncStartLabel();
        });
        input.addEventListener("keydown", (e) => {
          if (e.key === "Enter") { e.preventDefault(); startNow(); }
        });
        row.appendChild(input);
        const unit = document.createElement("span");
        unit.className = "focus-custom-unit";
        unit.textContent = "minutes";
        row.appendChild(unit);
        body.appendChild(row);
        setTimeout(() => { input.focus(); input.select(); }, 0);
      }

      const acts = document.createElement("div");
      acts.className = "picker-actions";
      acts.innerHTML = `
        <button class="picker-act-secondary" data-act="cancel">cancel</button>
        <button class="picker-act-primary" data-act="start">start ${chosenMinutes}m</button>`;
      acts.querySelector('[data-act="cancel"]').addEventListener("click", close);
      acts.querySelector('[data-act="start"]').addEventListener("click", startNow);
      body.appendChild(acts);
    }

    rebuild();
    return root;
  });
}

function startFocusSession(task, minutes) {
  const totalSec = Math.round(minutes * 60);
  state.focusSession = {
    taskId: task.id,
    taskName: task.name,
    totalSec,
    remainingSec: totalSec,
    paused: false,
    intervalId: null,
  };
  render();
  openFocusSessionOverlay();
  _tickFocusSession();
}

function fmtFocusTotal(totalMinutes) {
  const m = Math.max(0, Math.round(totalMinutes));
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  const rem = m % 60;
  return rem ? `${h}h ${rem}m` : `${h}h`;
}

function fmtMmSs(totalSeconds) {
  const s = Math.max(0, Math.round(totalSeconds));
  const m = Math.floor(s / 60);
  const ss = String(s % 60).padStart(2, "0");
  return `${m}:${ss}`;
}

function openFocusSessionOverlay() {
  openOverlay((close) => {
    const fs = state.focusSession;
    const root = document.createElement("div");
    root.className = "focus-session-card";
    root.innerHTML = `
      <button type="button" class="focus-session-back" data-act="back">← back to tasks</button>
      <div class="focus-session-task">${escapeHtml(fs ? fs.taskName : "")}</div>
      <div class="focus-session-timer" id="focus-timer-display">${fmtMmSs(fs ? fs.remainingSec : 0)}</div>
      <div class="focus-session-state" id="focus-state-display"></div>
      <div class="focus-session-actions">
        <button class="picker-act-secondary" data-act="pause">pause</button>
        <button class="picker-act-secondary" data-act="end">end session</button>
      </div>`;
    root.querySelector('[data-act="back"]').addEventListener("click", close);
    root.querySelector('[data-act="pause"]').addEventListener("click", (e) => {
      toggleFocusPause();
      e.target.textContent = state.focusSession && state.focusSession.paused ? "resume" : "pause";
    });
    root.querySelector('[data-act="end"]').addEventListener("click", () => {
      close();
      endFocusSession(false);
    });
    return root;
  });
}

function _tickFocusSession() {
  const fs = state.focusSession;
  if (!fs) return;
  clearInterval(fs.intervalId);
  fs.intervalId = setInterval(() => {
    const cur = state.focusSession;
    if (!cur || cur.paused) return;
    cur.remainingSec -= 1;
    const timerEl = document.getElementById("focus-timer-display");
    if (timerEl) timerEl.textContent = fmtMmSs(cur.remainingSec);
    const pill = document.getElementById("focus-indicator");
    if (pill) pill.textContent = "⏱ " + fmtMmSs(cur.remainingSec);
    if (cur.remainingSec <= 0) {
      clearInterval(cur.intervalId);
      completeFocusSession();
    }
  }, 1000);
}

function toggleFocusPause() {
  const fs = state.focusSession;
  if (!fs) return;
  fs.paused = !fs.paused;
  const stateEl = document.getElementById("focus-state-display");
  if (stateEl) stateEl.textContent = fs.paused ? "paused" : "";
}

async function completeFocusSession() {
  const fs = state.focusSession;
  if (!fs) return;
  const minutes = Math.max(1, Math.round(fs.totalSec / 60));
  closeOverlay();
  state.focusSession = null;
  render();
  showToast("Focus session complete ✅");
  await safeCall("focus_session_complete", fs.taskId, minutes);
  await refreshData();
}

async function endFocusSession(silent) {
  const fs = state.focusSession;
  if (!fs) return;
  clearInterval(fs.intervalId);
  const elapsedMinutes = Math.round((fs.totalSec - fs.remainingSec) / 60);
  state.focusSession = null;
  render();
  if (elapsedMinutes > 0) {
    await safeCall("focus_session_complete", fs.taskId, elapsedMinutes);
    await refreshData();
  }
  if (!silent) showToast("Focus session ended");
}

// ─── Settings ────────────────────────────────────────────────
function openSettings() {
  openOverlay((close) => {
    const root = document.createElement("div");
    root.className = "settings-card";
    root.innerHTML = `
      <div class="settings-title">Settings</div>
      <div class="settings-row">
        <div>
          <div class="settings-row-label">Start Checkera when your computer starts</div>
          <div class="settings-row-sub" id="autostart-sub">checking…</div>
        </div>
        <button type="button" class="settings-switch" id="autostart-switch" disabled></button>
      </div>`;

    const sw = root.querySelector("#autostart-switch");
    const sub = root.querySelector("#autostart-sub");

    (async () => {
      const status = await safeCall("get_autostart_status");
      if (!status || !status.supported) {
        sub.textContent = "Not supported on this platform";
        return;
      }
      sw.disabled = false;
      sw.classList.toggle("on", !!status.installed);
      sub.textContent = status.installed
        ? "Checkera will launch automatically on boot"
        : "Off — Checkera only opens when you launch it";
    })();

    sw.addEventListener("click", async () => {
      sw.disabled = true;
      const turningOn = !sw.classList.contains("on");
      const res = await safeCall("set_autostart", turningOn);
      if (res && res.ok) {
        sw.classList.toggle("on", turningOn);
        sub.textContent = turningOn
          ? "Checkera will launch automatically on boot"
          : "Off — Checkera only opens when you launch it";
      } else {
        showToast("Couldn't change auto-start setting");
      }
      sw.disabled = false;
    });

    return root;
  });
}

// Driven by the Ctrl+Shift+F global hotkey (see widget.py) — pause/resume an
// active session, or start a default one on the first "Today" task.
function quickToggleFocus() {
  if (state.focusSession) {
    if (document.querySelector(".focus-session-card")) {
      toggleFocusPause();
    } else {
      openFocusSessionOverlay();
    }
    return;
  }
  const today = state.tasks.find(t => getBucket(t) === "Today" || getBucket(t) === "Overdue");
  if (!today) {
    showToast("No task to focus on");
    return;
  }
  startFocusSession(today, 25);
}

// ─── Date picker overlay ────────────────────────────────────
function openDatePicker(initialIso, onPick) {
  let viewY, viewM, selected;
  if (initialIso) {
    const [y, m, d] = initialIso.split("-").map(Number);
    viewY = y; viewM = m; selected = initialIso;
  } else {
    const t = new Date();
    viewY = t.getFullYear(); viewM = t.getMonth() + 1; selected = null;
  }

  openOverlay((close) => {
    const root = document.createElement("div");
    root.className = "picker-card";

    function rebuild() {
      root.innerHTML = "";
      const head = document.createElement("div");
      head.className = "picker-head";
      head.innerHTML = `
        <button class="picker-nav" data-act="prev">‹</button>
        <span class="picker-title">${monthName(viewM)} ${viewY}</span>
        <button class="picker-nav" data-act="next">›</button>`;
      root.appendChild(head);
      head.querySelector('[data-act="prev"]').addEventListener("click", () => {
        viewM--; if (viewM < 1) { viewM = 12; viewY--; } rebuild();
      });
      head.querySelector('[data-act="next"]').addEventListener("click", () => {
        viewM++; if (viewM > 12) { viewM = 1; viewY++; } rebuild();
      });

      // DOW header
      const dow = document.createElement("div");
      dow.className = "picker-dow";
      ["M","T","W","T","F","S","S"].forEach(d => {
        const c = document.createElement("span");
        c.textContent = d;
        dow.appendChild(c);
      });
      root.appendChild(dow);

      // Grid
      const grid = document.createElement("div");
      grid.className = "picker-grid";
      const firstDay = new Date(viewY, viewM - 1, 1);
      const offset = (firstDay.getDay() + 6) % 7; // Monday first
      const daysIn = new Date(viewY, viewM, 0).getDate();
      const today = new Date();
      const todayIso = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2,"0")}-${String(today.getDate()).padStart(2,"0")}`;

      for (let i = 0; i < offset; i++) {
        const blank = document.createElement("span");
        blank.className = "picker-day picker-day-blank";
        grid.appendChild(blank);
      }
      for (let d = 1; d <= daysIn; d++) {
        const iso = `${viewY}-${String(viewM).padStart(2,"0")}-${String(d).padStart(2,"0")}`;
        const btn = document.createElement("button");
        btn.className = "picker-day";
        btn.textContent = d;
        if (iso === todayIso) btn.classList.add("picker-day-today");
        if (iso === selected) btn.classList.add("picker-day-selected");
        btn.addEventListener("click", () => { selected = iso; rebuild(); });
        grid.appendChild(btn);
      }
      root.appendChild(grid);

      // Actions
      const acts = document.createElement("div");
      acts.className = "picker-actions";
      acts.innerHTML = `
        <button class="picker-act-secondary" data-act="cancel">cancel</button>
        <button class="picker-act-secondary" data-act="today">today</button>
        <button class="picker-act-primary" data-act="ok">ok</button>`;
      acts.querySelector('[data-act="cancel"]').addEventListener("click", close);
      acts.querySelector('[data-act="today"]').addEventListener("click", () => {
        const t = new Date();
        viewY = t.getFullYear(); viewM = t.getMonth() + 1;
        selected = `${viewY}-${String(viewM).padStart(2,"0")}-${String(t.getDate()).padStart(2,"0")}`;
        rebuild();
      });
      acts.querySelector('[data-act="ok"]').addEventListener("click", () => {
        if (selected) onPick(selected);
        close();
      });
      root.appendChild(acts);
    }
    rebuild();
    return root;
  });
}

function monthName(m) {
  return ["January","February","March","April","May","June",
          "July","August","September","October","November","December"][m - 1];
}

// ─── Time picker overlay ────────────────────────────────────
function openTimePicker(initialHHMM, onPick) {
  let h12, mm, ampm;
  if (initialHHMM) {
    const [h, m] = initialHHMM.split(":").map(Number);
    h12 = h % 12 || 12;
    mm = String(Math.round(m / 5) * 5 % 60).padStart(2, "0");
    ampm = h < 12 ? "AM" : "PM";
  } else {
    h12 = 9; mm = "00"; ampm = "AM";
  }

  openOverlay((close) => {
    const root = document.createElement("div");
    root.className = "picker-card";

    function rebuild() {
      root.innerHTML = "";
      const head = document.createElement("div");
      head.className = "picker-head picker-head-simple";
      const hourTxt = String(h12);
      const m = parseInt(mm, 10);
      head.innerHTML = `<span class="picker-time-display">${hourTxt}:${mm} <span class="picker-ampm">${ampm}</span></span>`;
      root.appendChild(head);

      // Hour grid
      const hourLabel = document.createElement("div");
      hourLabel.className = "picker-mini-cap";
      hourLabel.textContent = "HOUR";
      root.appendChild(hourLabel);
      const hours = document.createElement("div");
      hours.className = "picker-time-grid";
      for (let i = 1; i <= 12; i++) {
        const b = document.createElement("button");
        b.className = "picker-time-cell";
        b.textContent = i;
        if (i === h12) b.classList.add("picker-time-selected");
        b.addEventListener("click", () => { h12 = i; rebuild(); });
        hours.appendChild(b);
      }
      root.appendChild(hours);

      // Minute grid (5-min increments)
      const mLabel = document.createElement("div");
      mLabel.className = "picker-mini-cap";
      mLabel.textContent = "MINUTE";
      root.appendChild(mLabel);
      const mins = document.createElement("div");
      mins.className = "picker-time-grid";
      for (let i = 0; i < 60; i += 5) {
        const s = String(i).padStart(2, "0");
        const b = document.createElement("button");
        b.className = "picker-time-cell";
        b.textContent = s;
        if (s === mm) b.classList.add("picker-time-selected");
        b.addEventListener("click", () => { mm = s; rebuild(); });
        mins.appendChild(b);
      }
      root.appendChild(mins);

      // AM/PM
      const ap = document.createElement("div");
      ap.className = "picker-ampm-row";
      ["AM","PM"].forEach(v => {
        const b = document.createElement("button");
        b.className = "picker-time-cell picker-ampm-cell";
        b.textContent = v;
        if (v === ampm) b.classList.add("picker-time-selected");
        b.addEventListener("click", () => { ampm = v; rebuild(); });
        ap.appendChild(b);
      });
      root.appendChild(ap);

      // Actions
      const acts = document.createElement("div");
      acts.className = "picker-actions";
      acts.innerHTML = `
        <button class="picker-act-secondary" data-act="cancel">cancel</button>
        <button class="picker-act-primary" data-act="ok">ok</button>`;
      acts.querySelector('[data-act="cancel"]').addEventListener("click", close);
      acts.querySelector('[data-act="ok"]').addEventListener("click", () => {
        let h24 = h12 % 12;
        if (ampm === "PM") h24 += 12;
        const out = `${String(h24).padStart(2,"0")}:${mm}`;
        onPick(out);
        close();
      });
      root.appendChild(acts);
    }
    rebuild();
    return root;
  });
}

// ─── Attendees section (pill input + autocomplete) ──────────
function renderAttendeesSection() {
  const wrap = document.createElement("div");
  wrap.className = "attendees-wrap";

  // Pills row + input live in the same flex container so the input flows
  // after the chips like Gmail's compose To: field.
  const box = document.createElement("div");
  box.className = "attendees-box";

  (state.form.attendees || []).forEach(email => {
    const chip = document.createElement("span");
    chip.className = "attendee-pill";
    chip.innerHTML = `<span class="attendee-pill-text"></span><button type="button" class="attendee-pill-x" aria-label="remove">×</button>`;
    chip.querySelector(".attendee-pill-text").textContent = email;
    chip.querySelector(".attendee-pill-x").addEventListener("click", (e) => {
      e.preventDefault();
      state.form.attendees = state.form.attendees.filter(x => x !== email);
      renderForm();
    });
    box.appendChild(chip);
  });

  const input = document.createElement("input");
  input.type = "email";
  input.className = "attendee-input";
  input.placeholder = state.form.attendees.length === 0
    ? "type an email, press Enter…"
    : "+ add another";
  input.value = state.form.attendeeDraft || "";
  input.autocomplete = "off";
  input.spellcheck = false;

  const commitEmail = () => {
    const v = (input.value || "").trim().toLowerCase();
    input.value = "";
    state.form.attendeeDraft = "";
    if (!v) return;
    if (!v.includes("@") || !v.includes(".")) return;        // soft-validate
    if (state.form.attendees.includes(v)) return;            // dedupe
    state.form.attendees = [...state.form.attendees, v];
    renderForm();
  };

  input.addEventListener("input", (e) => {
    state.form.attendeeDraft = e.target.value;
    refreshAttendeeSuggestions(input);
  });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      commitEmail();
    } else if (e.key === "Backspace" && !input.value && state.form.attendees.length) {
      // Quick backspace pops the last pill
      state.form.attendees = state.form.attendees.slice(0, -1);
      renderForm();
    } else if (e.key === "Escape") {
      input.value = "";
      state.form.attendeeDraft = "";
      hideAttendeeSuggestions();
    }
  });
  input.addEventListener("blur", () => {
    // Commit unfinished email on blur so it's not silently lost
    setTimeout(() => {                                       // give clicks a moment
      if (input.value.trim()) commitEmail();
      hideAttendeeSuggestions();
    }, 120);
  });

  box.appendChild(input);
  wrap.appendChild(box);

  // Suggestions dropdown lives below the box, anchored to it
  const sugg = document.createElement("div");
  sugg.className = "attendee-suggestions hidden";
  sugg.id = "attendee-suggestions";
  wrap.appendChild(sugg);

  return wrap;
}

// Gather every email used in any local task (active + done) for autocomplete.
function _knownEmails() {
  const set = new Set();
  const collect = list => (list || []).forEach(t => (t.attendees || []).forEach(e => set.add(e)));
  collect(state.tasks);
  collect(state.doneItems);
  // Don't suggest ones already on the current draft task
  (state.form.attendees || []).forEach(e => set.delete(e));
  return [...set].sort();
}

function refreshAttendeeSuggestions(inputEl) {
  const sugg = document.getElementById("attendee-suggestions");
  if (!sugg) return;
  const q = (inputEl.value || "").trim().toLowerCase();
  if (!q) { sugg.classList.add("hidden"); sugg.innerHTML = ""; return; }
  const matches = _knownEmails().filter(e => e.includes(q)).slice(0, 5);
  if (!matches.length) { sugg.classList.add("hidden"); sugg.innerHTML = ""; return; }
  sugg.innerHTML = "";
  matches.forEach(email => {
    const row = document.createElement("button");
    row.type = "button";
    row.className = "attendee-sugg-row";
    row.textContent = email;
    row.addEventListener("mousedown", (e) => {
      // mousedown beats the input's blur — keeps the click from being lost
      e.preventDefault();
      state.form.attendees = [...state.form.attendees, email];
      state.form.attendeeDraft = "";
      renderForm();
    });
    sugg.appendChild(row);
  });
  sugg.classList.remove("hidden");
}

function hideAttendeeSuggestions() {
  const sugg = document.getElementById("attendee-suggestions");
  if (sugg) sugg.classList.add("hidden");
}

// ─── Subtasks section (inside edit form) ────────────────────
function renderSubtaskSection() {
  const taskId = state.editing;
  // Find the current task to read its subtasks (may have been updated externally)
  const task = state.tasks.find(t => t.id === taskId)
            || state.doneItems.find(t => t.id === taskId);
  const subs = (task && task.subtasks) || [];

  const sec = document.createElement("div");
  sec.className = "form-section";

  const cap = document.createElement("div");
  cap.className = "form-caption";
  cap.textContent = "SUBTASKS";
  if (subs.length) {
    const c = document.createElement("span");
    c.className = "form-caption-count";
    const doneN = subs.filter(s => s.done).length;
    c.textContent = `  ${doneN}/${subs.length}`;
    cap.appendChild(c);
  }
  sec.appendChild(cap);

  const list = document.createElement("div");
  list.className = "subtask-list";
  subs.forEach(s => list.appendChild(renderSubtaskRow(taskId, s)));
  sec.appendChild(list);

  // Add new subtask
  const addRow = document.createElement("div");
  addRow.className = "subtask-add-row";
  const input = document.createElement("input");
  input.className = "form-input subtask-input";
  input.placeholder = "+ add a step";
  input.addEventListener("keydown", async (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      const v = input.value.trim();
      if (!v) return;
      const res = await safeCall("add_subtask", taskId, v);
      if (res && res.ok) {
        await refreshData();
        // Re-focus the (now empty) input so user can keep adding
        setTimeout(() => {
          const el = document.querySelector(".subtask-input");
          if (el) el.focus();
        }, 0);
      }
    }
  });
  addRow.appendChild(input);
  sec.appendChild(addRow);
  return sec;
}

function renderSubtaskRow(taskId, sub) {
  const row = document.createElement("div");
  row.className = "subtask-row" + (sub.done ? " subtask-row-done" : "");

  const cb = document.createElement("button");
  cb.className = "subtask-cb" + (sub.done ? " checked" : "");
  if (sub.done) cb.innerHTML = ICON.check;
  cb.addEventListener("click", async () => {
    await safeCall("toggle_subtask", taskId, sub.id);
    await refreshData();
  });
  row.appendChild(cb);

  const text = document.createElement("span");
  text.className = "subtask-text";
  text.textContent = sub.text;
  row.appendChild(text);

  const del = document.createElement("button");
  del.className = "subtask-del";
  del.innerHTML = "×";
  del.title = "remove";
  del.addEventListener("click", async () => {
    await safeCall("delete_subtask", taskId, sub.id);
    await refreshData();
  });
  row.appendChild(del);

  return row;
}

// Compute reminder date/time from the currently-selected preset
function applyReminderPreset() {
  const p = state.form.reminderPreset;
  if (!p || p === "custom") return;
  if (!state.form.dueDate) {
    state.form.remDate = ""; state.form.remTime = "";
    return;
  }
  const [y, m, d] = state.form.dueDate.split("-").map(Number);
  const [hh, mm] = (state.form.dueTime || "23:59").split(":").map(Number);
  const dueDt = new Date(y, m - 1, d, hh, mm);
  let offsetMs = 0;
  if (p === "1d") offsetMs = 24 * 60 * 60 * 1000;
  if (p === "1h") offsetMs = 60 * 60 * 1000;
  if (p === "30m") offsetMs = 30 * 60 * 1000;
  const rd = new Date(dueDt.getTime() - offsetMs);
  state.form.remDate = `${rd.getFullYear()}-${String(rd.getMonth() + 1).padStart(2, "0")}-${String(rd.getDate()).padStart(2, "0")}`;
  state.form.remTime = `${String(rd.getHours()).padStart(2, "0")}:${String(rd.getMinutes()).padStart(2, "0")}`;
}

function cancelCreate() {
  state.creating = false;
  resetForm();
  render();
}

async function submitCreate() {
  const name = state.form.name.trim();
  if (!name) {
    document.querySelector(".form-input")?.focus();
    return;
  }
  // Custom recurrence requires at least one weekday — otherwise sweep
  // can't compute a next date and the task silently never recurs.
  if (state.form.recurrence === "custom" && state.form.recurrenceDays.length === 0) {
    await confirmDialog({
      title: "Pick at least one day",
      message: "You picked 'custom' recurrence but no days are selected. Tap M/T/W/T/F/S/S to choose which days this task should fire on.",
      confirmLabel: "ok", cancelLabel: "close",
    });
    return;
  }
  const due_date = state.form.dueDate || null;
  const due_time = state.form.dueTime || null;
  let reminder_at = null;
  if (state.form.reminderPreset && state.form.remDate) {
    const t = state.form.remTime || "09:00";
    reminder_at = `${state.form.remDate}T${t}`;
  }
  const recurrence = state.form.recurrence && state.form.recurrence !== "none"
                     ? state.form.recurrence : null;
  const recurrenceDays = recurrence === "custom" ? state.form.recurrenceDays : null;
  // If the user left an unconfirmed email in the draft, commit it before save
  const pendingDraft = (state.form.attendeeDraft || "").trim().toLowerCase();
  let attendees = state.form.attendees.slice();
  if (pendingDraft.includes("@") && pendingDraft.includes(".") && !attendees.includes(pendingDraft)) {
    attendees.push(pendingDraft);
  }
  await safeCall("add_task", name, state.form.category,
                 (state.form.priority === "none" ? null : state.form.priority),
                 due_date, due_time, reminder_at, recurrence, recurrenceDays, attendees);
  state.creating = false;
  resetForm();
  await refreshData();
}

// Open the edit form for an existing task. Pre-fills state.form from the task.
function enterEdit(task) {
  state.editing = task.id;
  state.creating = false;
  state.viewingDone = false;
  state.formFirstRender = true;
  state.form = {
    name: task.name || "",
    category: task.category || "Work",
    priority: task.priority || "none",
    dueDate: task.dueDate || "",
    dueTime: task.dueTime || "",
    // We don't know which preset was originally chosen — treat any existing
    // reminder as "custom" so the user sees + can edit the exact date/time.
    reminderPreset: task.reminderDate ? "custom" : null,
    remDate: task.reminderDate || "",
    remTime: task.reminderTime || "",
    recurrence: task.recurrence || "none",
    recurrenceDays: Array.isArray(task.recurrenceDays) ? task.recurrenceDays.slice() : [],
    attendees: Array.isArray(task.attendees) ? task.attendees.slice() : [],
    attendeeDraft: "",
  };
  render();
}

function cancelEdit() {
  state.editing = null;
  resetForm();
  render();
}

async function submitEdit() {
  const id = state.editing;
  if (!id) return;
  const name = state.form.name.trim();
  if (!name) {
    document.querySelector(".form-input")?.focus();
    return;
  }
  if (state.form.recurrence === "custom" && state.form.recurrenceDays.length === 0) {
    await confirmDialog({
      title: "Pick at least one day",
      message: "You picked 'custom' recurrence but no days are selected. Tap M/T/W/T/F/S/S to choose which days this task should fire on.",
      confirmLabel: "ok", cancelLabel: "close",
    });
    return;
  }
  let reminder_at = null;
  if (state.form.reminderPreset && state.form.remDate) {
    const t = state.form.remTime || "09:00";
    reminder_at = `${state.form.remDate}T${t}`;
  }
  const fields = {
    name,
    category: state.form.category,
    priority: state.form.priority === "none" ? null : state.form.priority,
    due_date: state.form.dueDate || null,
    due_time: state.form.dueTime || null,
    reminder_at,
    recurrence: state.form.recurrence && state.form.recurrence !== "none"
                ? state.form.recurrence : null,
    recurrence_days: state.form.recurrence === "custom"
                     ? state.form.recurrenceDays : [],
    attendees: (() => {
      // Commit any unconfirmed draft so the user doesn't lose it on save
      const pending = (state.form.attendeeDraft || "").trim().toLowerCase();
      const arr = state.form.attendees.slice();
      if (pending.includes("@") && pending.includes(".") && !arr.includes(pending)) arr.push(pending);
      return arr;
    })(),
  };
  const res = await safeCall("edit_task", id, fields);
  if (res && res.ok === false) {
    console.warn("edit_task failed:", res.error);
    return;
  }
  state.editing = null;
  resetForm();
  await refreshData();
}

async function submitDelete() {
  const id = state.editing;
  if (!id) return;
  const taskName = state.form.name?.trim() || "this task";
  const ok = await confirmDialog({
    title: "Delete task?",
    message: `“${taskName}” will be permanently removed. This can't be undone.`,
    confirmLabel: "delete",
    cancelLabel: "cancel",
    danger: true,
  });
  if (!ok) return;
  await safeCall("delete_task", id);
  state.editing = null;
  resetForm();
  await refreshData();
}

// ─── Custom confirmation dialog (replaces window.confirm) ───
function confirmDialog({ title, message, confirmLabel = "ok",
                        cancelLabel = "cancel", danger = false } = {}) {
  return new Promise((resolve) => {
    let settled = false;
    const finish = (v) => {
      if (settled) return;
      settled = true;
      closeOverlay();
      resolve(v);
    };

    openOverlay((close) => {
      const root = document.createElement("div");
      root.className = "confirm-card" + (danger ? " confirm-danger" : "");

      const icon = document.createElement("div");
      icon.className = "confirm-icon";
      icon.innerHTML = danger
        ? `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/></svg>`
        : `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="13"/><circle cx="12" cy="16" r="0.6" fill="currentColor"/></svg>`;
      root.appendChild(icon);

      const titleEl = document.createElement("div");
      titleEl.className = "confirm-title";
      titleEl.textContent = title || "Are you sure?";
      root.appendChild(titleEl);

      if (message) {
        const msgEl = document.createElement("div");
        msgEl.className = "confirm-message";
        msgEl.textContent = message;
        root.appendChild(msgEl);
      }

      const actions = document.createElement("div");
      actions.className = "confirm-actions";

      const cancelBtn = document.createElement("button");
      cancelBtn.className = "confirm-cancel";
      cancelBtn.textContent = cancelLabel;
      cancelBtn.addEventListener("click", () => finish(false));
      actions.appendChild(cancelBtn);

      const okBtn = document.createElement("button");
      okBtn.className = "confirm-ok" + (danger ? " confirm-ok-danger" : "");
      okBtn.textContent = confirmLabel;
      okBtn.addEventListener("click", () => finish(true));
      actions.appendChild(okBtn);

      root.appendChild(actions);

      // Esc cancels, Enter confirms — local listener removed when settled
      const onKey = (e) => {
        if (settled) { document.removeEventListener("keydown", onKey); return; }
        if (e.key === "Escape") { e.preventDefault(); finish(false); }
        else if (e.key === "Enter") { e.preventDefault(); finish(true); }
      };
      document.addEventListener("keydown", onKey);

      setTimeout(() => okBtn.focus(), 30);
      return root;
    });

    // If the user dismisses by clicking the backdrop, resolve as false
    const back = document.querySelector(".overlay");
    if (back) {
      back.addEventListener("click", (e) => {
        if (e.target === back) finish(false);
      });
    }
  });
}

// Re-render just the form (preserves focus on inputs better than a full render)
function renderForm() { render(); }

// Brief inline toast notification — used for confirming actions like
// "task completed · next: <date>" so users get visible feedback when the
// list change isn't obvious (e.g. recurring task spawning a new occurrence).
function showToast(message, timeoutMs = 2400) {
  // Drop any existing toast so back-to-back actions don't stack
  document.querySelectorAll(".toast").forEach(t => t.remove());
  const t = document.createElement("div");
  t.className = "toast";
  t.textContent = message;
  document.body.appendChild(t);
  requestAnimationFrame(() => t.classList.add("toast-shown"));
  setTimeout(() => {
    t.classList.remove("toast-shown");
    setTimeout(() => t.remove(), 220);
  }, timeoutMs);
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
}

// ─── Main render ────────────────────────────────────────────
function render() {
  const VIEW_LABEL = { tasks: "Today", news: "Feed", notes: "Notes" };
  let title = VIEW_LABEL[state.tab] || "";
  if (state.tab === "tasks" && state.viewingDone) title = "Completed";
  if (state.tab === "tasks" && state.creating)    title = "New";
  if (state.tab === "tasks" && state.editing)     title = "Edit";
  document.getElementById("view-title").textContent = title;

  const inForm = state.creating || !!state.editing;

  let count = 0;
  if (state.tab === "tasks") {
    count = state.viewingDone ? state.doneItems.length : state.tasks.length;
  }
  const countEl = document.getElementById("view-count");
  if (state.tab === "news" || state.tab === "notes" || (state.tab === "tasks" && inForm)) {
    countEl.classList.add("hidden");
  } else {
    countEl.classList.remove("hidden");
    countEl.textContent = count;
  }

  // Header action visibility
  const addBtn  = document.getElementById("action-add");
  const refBtn  = document.getElementById("action-refresh");
  const doneLnk = document.getElementById("action-done");
  // Defaults
  addBtn.classList.add("hidden");
  refBtn.classList.add("hidden");
  doneLnk.classList.add("hidden");

  // Focus session indicator — visible from any tab while a session runs
  const focusPill = document.getElementById("focus-indicator");
  if (state.focusSession) {
    focusPill.classList.remove("hidden");
    focusPill.textContent = "⏱ " + fmtMmSs(state.focusSession.remainingSec);
  } else {
    focusPill.classList.add("hidden");
  }

  if (state.tab === "tasks" && !inForm && !state.viewingDone) {
    addBtn.classList.remove("hidden");
    doneLnk.classList.remove("hidden");
  } else if (state.tab === "news") {
    refBtn.classList.remove("hidden");
  }

  // Tab styling
  document.querySelectorAll(".tab-btn").forEach(b => {
    b.classList.toggle("active", b.dataset.tab === state.tab);
  });

  // Content
  const content = document.getElementById("content");
  // Preserve scroll position across re-renders — otherwise clicking a chip
  // in the form rebuilds the DOM and snaps the user back to the top.
  const savedScrollTop = content.scrollTop;
  // Preserve notes textarea selection so the 60s periodic refresh doesn't
  // snap the user's cursor to the end of the text mid-typing.
  let savedNotesSel = null;
  const activeEl = document.activeElement;
  if (activeEl && activeEl.classList && activeEl.classList.contains("notes-input")) {
    savedNotesSel = {
      start: activeEl.selectionStart,
      end: activeEl.selectionEnd,
      scrollTop: activeEl.scrollTop,
    };
  }
  content.innerHTML = "";

  if (state.tab === "tasks") {
    if (inForm) {
      content.appendChild(renderTaskForm());
    } else if (state.viewingDone) {
      content.appendChild(renderDoneView());
    } else {
      if (!state.gcalConnected) content.appendChild(renderGcalBanner());
      content.appendChild(renderSearchBar());
      const filtered = filterBySearch(state.tasks, state.search);
      const grouped = groupTasks(filtered);
      if (grouped.size === 0) {
        const msg = state.search
          ? `No matches for "${state.search}"`
          : "All clear for today";
        content.appendChild(renderEmpty(msg));
      } else {
        grouped.forEach((tasks, bucket) => content.appendChild(renderBucket(bucket, tasks)));
      }
      // Ghost previews for recurring tasks whose next date hasn't arrived yet
      if (!state.search && state.upcoming && state.upcoming.length) {
        content.appendChild(renderUpcomingSection(state.upcoming));
      }
    }
  } else if (state.tab === "news") {
    if (state.news.length === 0) {
      content.appendChild(renderEmpty("Fetching news…"));
    } else {
      state.news.forEach(item => content.appendChild(renderNewsRow(item)));
    }
  } else if (state.tab === "notes") {
    content.appendChild(renderNotesView());
  }

  // Restore scroll position — must beat the browser's post-click layout pass,
  // which can re-set scrollTop to 0 when focus moves to a recreated element.
  // Setting it twice (sync + next frame) wins the race in practice.
  if (savedScrollTop > 0) {
    content.scrollTop = savedScrollTop;
    requestAnimationFrame(() => { content.scrollTop = savedScrollTop; });
  }
  // Restore notes textarea cursor + scroll if the user was typing in it
  if (savedNotesSel) {
    const newTa = document.querySelector(".notes-input");
    if (newTa) {
      newTa.focus();
      try { newTa.setSelectionRange(savedNotesSel.start, savedNotesSel.end); } catch (_) {}
      newTa.scrollTop = savedNotesSel.scrollTop;
    }
  }
}

// ─── Search bar ─────────────────────────────────────────────
function renderSearchBar() {
  const wrap = document.createElement("div");
  wrap.className = "search-wrap" + (state.search ? " search-active" : "");

  const input = document.createElement("input");
  input.className = "search-input";
  input.id = "search-input";
  input.type = "text";
  input.placeholder = "search tasks…   /";
  input.value = state.search;
  input.spellcheck = false;
  input.autocomplete = "off";

  let typingTimer = null;
  input.addEventListener("input", (e) => {
    const v = e.target.value;
    if (typingTimer) clearTimeout(typingTimer);
    // Re-render in place after a small debounce so the focused input stays focused
    typingTimer = setTimeout(() => {
      state.search = v;
      render();
      // Restore focus and caret after re-render
      const el = document.getElementById("search-input");
      if (el) {
        el.focus();
        el.setSelectionRange(v.length, v.length);
      }
    }, 80);
  });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      e.preventDefault();
      state.search = "";
      render();
    }
  });
  wrap.appendChild(input);

  if (state.search) {
    const clear = document.createElement("button");
    clear.className = "search-clear";
    clear.textContent = "×";
    clear.title = "clear search (Esc)";
    clear.addEventListener("click", () => {
      state.search = "";
      render();
    });
    wrap.appendChild(clear);
  }
  return wrap;
}

function filterBySearch(tasks, query) {
  const q = (query || "").trim().toLowerCase();
  if (!q) return tasks;
  return tasks.filter(t => {
    const hay = [
      t.name,
      t.category,
      t.priority || "",
      t.dueDate || "",
    ].join(" ").toLowerCase();
    return hay.includes(q);
  });
}

// ─── Upcoming ghost rows (recurring tasks not yet spawned) ──
function renderUpcomingSection(items) {
  const wrap = document.createElement("div");
  wrap.className = "upcoming-wrap";

  const head = document.createElement("div");
  head.className = "upcoming-head";
  head.innerHTML = `<span>upcoming</span><span class="upcoming-count">${items.length}</span>`;
  wrap.appendChild(head);

  items.slice(0, 6).forEach(it => {
    const row = document.createElement("div");
    row.className = "upcoming-row";
    // Unambiguous: always show "returns <full date>". No more "in N days ·
    // every day" combos that read oddly when N happens to equal the cycle.
    row.innerHTML = `
      <span class="upcoming-icon">↻</span>
      <span class="upcoming-name">${escapeHtml(it.name)}</span>
      <span class="upcoming-meta">returns ${escapeHtml(prettyDateFull(it.next_date))}</span>`;
    wrap.appendChild(row);
  });
  if (items.length > 6) {
    const more = document.createElement("div");
    more.className = "upcoming-more";
    more.textContent = `+${items.length - 6} more series`;
    wrap.appendChild(more);
  }
  return wrap;
}

// ─── Done sub-view (inside tasks tab) ───────────────────────
function renderDoneView() {
  const wrap = document.createElement("div");
  wrap.className = "sub-view";

  const head = document.createElement("div");
  head.className = "sub-view-head";
  head.innerHTML = `
    <button class="sub-back">← back</button>
    <span class="sub-view-title"></span>
    <span class="sub-view-count">${state.doneItems.length}</span>`;
  head.querySelector(".sub-back").addEventListener("click", () => {
    state.viewingDone = false;
    render();
  });
  wrap.appendChild(head);

  wrap.appendChild(renderStatsPanel());

  if (state.doneItems.length === 0) {
    wrap.appendChild(renderEmpty("Nothing completed yet"));
  } else {
    state.doneItems.forEach(t => wrap.appendChild(renderDoneRow(t)));
  }
  return wrap;
}

function renderStatsPanel() {
  const wrap = document.createElement("div");
  wrap.className = "stats-panel";

  const s = state.stats || {
    done_today: 0, done_week: 0, done_total: 0,
    current_streak: 0, longest_streak: 0,
  };

  const cell = (val, label, accent) => `
    <div class="stat-cell">
      <div class="stat-val" style="color:${accent || "var(--text)"}">${val}</div>
      <div class="stat-lbl">${label}</div>
    </div>`;

  const streakIcon = s.current_streak >= 3 ? "🔥" : (s.current_streak >= 1 ? "✨" : "·");

  wrap.innerHTML = `
    <div class="stats-row">
      ${cell(s.done_today, "today", "#D4845A")}
      ${cell(s.done_week,  "this week", "#C4A24A")}
      ${cell(s.done_total, "all time", "#6390B8")}
    </div>
    <div class="streak-row">
      <span class="streak-flame">${streakIcon}</span>
      <span class="streak-text">streak — <strong>${s.current_streak}</strong> day${s.current_streak === 1 ? "" : "s"}</span>
      ${s.longest_streak > s.current_streak
          ? `<span class="streak-best">best: ${s.longest_streak}</span>`
          : ""}
    </div>`;

  // Refresh stats from backend whenever this panel renders
  loadStats();
  return wrap;
}

// ─── Notes view ─────────────────────────────────────────────
function renderNotesView() {
  const wrap = document.createElement("div");
  wrap.className = "notes-view";

  const ta = document.createElement("textarea");
  ta.className = "notes-input";
  ta.placeholder = "Jot down anything — saves automatically.";
  ta.value = state.notes || "";
  ta.spellcheck = false;

  let saveTimer = null;
  ta.addEventListener("input", (e) => {
    state.notes = e.target.value;
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(() => {
      safeCall("set_notes", state.notes);
      updateNotesStatus("saved");
    }, 400);
    updateNotesStatus("saving…");
  });
  ta.addEventListener("blur", () => {
    if (saveTimer) { clearTimeout(saveTimer); saveTimer = null; }
    safeCall("set_notes", state.notes);
    updateNotesStatus("saved");
  });

  wrap.appendChild(ta);

  const status = document.createElement("div");
  status.className = "notes-status";
  status.id = "notes-status";
  status.textContent = state.notesLoaded ? "saved" : "";
  wrap.appendChild(status);

  // Focus on mount
  setTimeout(() => ta.focus(), 0);
  return wrap;
}

function updateNotesStatus(text) {
  const el = document.getElementById("notes-status");
  if (el) el.textContent = text;
}

// ─── Wire static UI ─────────────────────────────────────────
document.querySelectorAll(".tab-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    state.tab = btn.dataset.tab;
    state.creating = false;
    state.editing = null;
    state.viewingDone = false;
    render();
    if (state.tab === "news" && state.news.length === 0) refreshNews();
    if (state.tab === "notes" && !state.notesLoaded) loadNotes();
  });
});
document.getElementById("action-add").addEventListener("click", () => {
  if (state.tab !== "tasks") state.tab = "tasks";
  state.creating = true;
  state.editing = null;
  state.viewingDone = false;
  state.formFirstRender = true;
  resetForm();
  render();
});
document.getElementById("action-done").addEventListener("click", () => {
  if (state.tab !== "tasks") state.tab = "tasks";
  state.viewingDone = true;
  state.creating = false;
  state.editing = null;
  render();
});
document.getElementById("action-refresh").addEventListener("click", () => {
  document.getElementById("action-refresh").classList.add("spinning");
  // Force a real network refetch — clicking refresh should bypass the cache
  refreshNews(true).finally(() => {
    setTimeout(() => document.getElementById("action-refresh").classList.remove("spinning"), 900);
  });
});
document.getElementById("focus-indicator").addEventListener("click", () => {
  if (state.focusSession && !document.querySelector(".focus-session-card")) {
    openFocusSessionOverlay();
  }
});
document.getElementById("action-settings").addEventListener("click", () => {
  openSettings();
});
// Minimize hides the window outright rather than calling a native minimize:
// with no taskbar button, Windows parks a minimized tool window as a stub in
// the bottom-left corner of the screen. Restore from the tray or Ctrl+Shift+T.
document.getElementById("win-min").addEventListener("click", () => pyHideToTray());
document.getElementById("win-close").addEventListener("click", () => pyHideToTray());

// Frameless windows have no native resize border, so the corner grip drives
// window.resize() through the bridge. Throttled to one call per frame —
// firing on every mousemove floods the JS↔Python bridge and stutters.
(function initResizeGrip() {
  const grip = document.getElementById("resize-grip");
  if (!grip) return;
  let dragging = false, startX = 0, startY = 0, startW = 0, startH = 0, queued = false;
  let pendingW = 0, pendingH = 0;

  grip.addEventListener("mousedown", (e) => {
    e.preventDefault();
    dragging = true;
    startX = e.screenX; startY = e.screenY;
    startW = window.innerWidth; startH = window.innerHeight;
  });
  window.addEventListener("mousemove", (e) => {
    if (!dragging) return;
    pendingW = Math.max(280, startW + (e.screenX - startX));
    pendingH = Math.max(320, startH + (e.screenY - startY));
    if (queued) return;
    queued = true;
    requestAnimationFrame(() => {
      queued = false;
      safeCall("resize_window", pendingW, pendingH);
    });
  });
  window.addEventListener("mouseup", () => { dragging = false; });
})();
// (Title bar buttons removed — using native Windows chrome now)

// ─── Bridge to Python ───────────────────────────────────────
function api() { return (window.pywebview && window.pywebview.api) || null; }
async function safeCall(fn, ...args) {
  const a = api();
  if (!a || !a[fn]) return null;
  try { return await a[fn](...args); } catch (e) { console.error(fn, e); return null; }
}
function pyToggleTask(id)     { return safeCall("toggle_task", id).then(refreshData); }
function pyAddTask(name)      { return safeCall("add_task", name); }
function pyMinimize()         { return safeCall("minimize_window"); }
function pyHideToTray()       { return safeCall("hide_to_tray"); }
function pyOpenUrl(url)       { return safeCall("open_url", url); }

async function pyConnectGcal() {
  const res = await safeCall("connect_gcal");
  if (!res) return;

  if (res.ok && res.stage === "auth_started") {
    await confirmDialog({
      title: "Authorize in your browser",
      message: ("A Google sign-in tab should have opened. Pick your account, " +
                "click Advanced → Go to (unsafe) if you see the warning, then " +
                "Allow. The widget will update automatically."),
      confirmLabel: "got it",
      cancelLabel: "close",
    });
    // Poll for up to ~60s for the token file to appear
    const start = Date.now();
    const poll = setInterval(async () => {
      await refreshData();
      if (state.gcalConnected || Date.now() - start > 60_000) clearInterval(poll);
    }, 2000);
    return;
  }

  if (res.ok && res.stage === "already_connected") {
    await refreshData();
    return;
  }

  // Error stages: library_missing / no_credentials
  await confirmDialog({
    title: res.stage === "no_credentials"
            ? "credentials.json not found"
            : "Can't start sign-in",
    message: res.message || "Something went wrong starting the connection.",
    confirmLabel: "ok",
    cancelLabel: "close",
    danger: false,
  });
}
async function refreshData()  {
  const data = await safeCall("get_state");
  if (data) {
    state.tasks = data.tasks || [];
    state.doneItems = data.doneItems || [];
    state.upcoming = data.upcoming || [];
    state.gcalConnected = !!data.gcalConnected;
    render();
  }
}
async function refreshNews(force = false) {
  const news = await safeCall("get_news", force);
  if (news) {
    state.news = news;
    render();
  }
}
async function loadNotes() {
  const txt = await safeCall("get_notes");
  state.notes = typeof txt === "string" ? txt : "";
  state.notesLoaded = true;
  if (state.tab === "notes") render();
}
async function loadStats() {
  const s = await safeCall("get_stats");
  if (s && typeof s === "object") {
    // Only re-render if the panel is still visible (avoid stomping other views)
    const wasNull = !state.stats;
    state.stats = s;
    if (state.viewingDone && state.tab === "tasks" && wasNull) render();
  }
}

// ─── Boot ───────────────────────────────────────────────────
window.addEventListener("pywebviewready", () => {
  refreshData();
  loadNotes();
});
// Periodic light refresh
setInterval(() => {
  if (api()) refreshData();
}, 60_000);

// Global "/" focuses search when the tasks list is visible
document.addEventListener("keydown", (e) => {
  if (e.key !== "/" || e.ctrlKey || e.metaKey || e.altKey) return;
  // Ignore if we're typing inside an input/textarea already
  const tag = (e.target?.tagName || "").toLowerCase();
  if (tag === "input" || tag === "textarea") return;
  // Only when we're on the plain tasks list (not creating/editing/viewing-done)
  if (state.tab !== "tasks" || state.creating || state.editing || state.viewingDone) return;
  e.preventDefault();
  const el = document.getElementById("search-input");
  if (el) { el.focus(); el.select(); }
});

// Initial empty render so the chrome is visible immediately
render();
