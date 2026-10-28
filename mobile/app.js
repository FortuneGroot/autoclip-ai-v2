"use strict";
const key = new URLSearchParams(location.search).get("key") || "";
const form = document.getElementById("generate-form");
const urlInput = document.getElementById("url");
const generate = document.getElementById("generate");
const progressCard = document.getElementById("progress-card");
const statusText = document.getElementById("status-text");
const percent = document.getElementById("percent");
const progressFill = document.getElementById("progress-fill");
const errorBox = document.getElementById("error");
const jobsBox = document.getElementById("jobs");
const jobCount = document.getElementById("job-count");
const localVideo = document.getElementById("local-video");
const runNotice = text("p", "run-notice", ""); runNotice.setAttribute("role", "status");
const runAgain = text("button", "rerun-button", "Generate again anyway"); runAgain.type = "button"; runAgain.hidden = true;
form.after(runNotice, runAgain);
let lastSignature = "";
let pendingRefinement = null;
function api(path) { const u = new URL(path, location.origin); u.searchParams.set("key", key); return u.toString(); }
async function json(path, options) {
  const response = await fetch(api(path), { cache: "no-store", ...options });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
  return data;
}
function showError(message) { errorBox.textContent = message; errorBox.hidden = false; }
function clearError() { errorBox.hidden = true; errorBox.textContent = ""; }
function text(tag, className, value) { const el = document.createElement(tag); if (className) el.className = className; el.textContent = String(value ?? ""); return el; }
function clipCard(clip) {
  const card = text("article", "clip", "");
  const video = document.createElement("video"); video.controls = true; video.playsInline = true; video.preload = "none";
  video.poster = api(clip.poster_url); video.src = api(clip.video_url); card.append(video);
  const body = text("div", "clip-body", "");
  body.append(text("strong", "", `${clip.rank}. ${clip.title}`));
  body.append(text("div", "meta", `${clip.duration}s · Score ${clip.score}`));
  body.append(text("p", "caption", clip.social_caption));
  const actions = text("div", "actions", "");
  const save = text("a", "download", "Save MP4"); save.href = api(`${clip.video_url}?download=1`); save.setAttribute("download", `AUTOCLIP_${clip.rank}.mp4`); actions.append(save);
  const copy = text("button", "copy", "Copy caption"); copy.type = "button";
  copy.addEventListener("click", async () => { try { await navigator.clipboard.writeText(clip.social_caption); copy.textContent = "Copied"; } catch { showError("Select the caption text to copy it."); } });
  actions.append(copy); body.append(actions); card.append(body); return card;
}
function refineForm(job) {
  const section = text("section", "refine", "");
  const toggle = text("button", "refine-toggle", "Optional: guide clips with my notes");
  toggle.type = "button";
  toggle.setAttribute("aria-expanded", "false");
  const form = document.createElement("form"); form.className = "refine-form"; form.hidden = true;
  const label = text("label", "", "Paste any moments you noted in the original video");
  const input = document.createElement("textarea");
  input.id = `markers-${job.job}`; input.rows = 3; input.maxLength = 4000;
  input.placeholder = "12.45\n15\n1:02:15"; input.required = true;
  label.htmlFor = input.id;
  const hint = text("p", "refine-hint", "You do not need notes for automatic Generate Clips. If you have them, enter up to 100 approximate times, one per line. Use 12.45 for 12 minutes 45 seconds, 15 for 15 minutes, or 1:02:15. AUTOCLIP chooses the ending and exports one clip per mark when complete speech is available.");
  const notice = text("p", "refine-notice", ""); notice.setAttribute("role", "status");
  const submit = text("button", "refine-submit", "Create clips from my notes"); submit.type = "submit";
  form.append(label, input, hint, submit, notice);
  toggle.addEventListener("click", () => {
    form.hidden = !form.hidden;
    toggle.setAttribute("aria-expanded", String(!form.hidden));
    if (!form.hidden) input.focus();
  });
  form.addEventListener("submit", async event => {
    event.preventDefault(); clearError(); notice.textContent = ""; submit.disabled = true;
    try {
      await json(`/api/jobs/${encodeURIComponent(job.job)}/refine`, {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({timestamps: input.value.trim()})
      });
      notice.textContent = "Finding clips near your marks. This uses the saved video; no new transcription.";
      pendingRefinement = {notice, submit};
      await refresh();
    } catch (err) { notice.textContent = err.message; submit.disabled = false; }
  });
  section.append(toggle, form);
  return section;
}
function jobPanel(job) {
  const panel = text("article", "job", ""); panel.id = `job-${job.job}`;
  const head = text("div", "job-head", ""); const label = text("div", "", "");
  label.append(text("h3", "", job.source_title), text("p", "", `${job.clips.length} ranked clips · ${job.selection_mode || "local AI"}`)); head.append(label);
  const headActions = text("div", "job-actions", "");
  const all = text("a", "all-link", "Download clips"); all.href = api(job.download_all_url); all.setAttribute("download", "AUTOCLIP_AI_clips.zip"); headActions.append(all);
  const remove = text("button", "delete-job", "Delete this run"); remove.type = "button";
  remove.addEventListener("click", async () => {
    if (!confirm(`Permanently delete this run and its clip files?\n${job.source_title}\nThis cannot be undone.`)) return;
    clearError(); remove.disabled = true;
    try {
      await json(`/api/jobs/${encodeURIComponent(job.job)}`, {method:"DELETE"});
      lastSignature = "";
      await refresh();
    } catch (err) { showError(err.message); remove.disabled = false; }
  });
  headActions.append(remove); head.append(headActions); panel.append(head);
  if (job.can_refine) panel.append(refineForm(job));
  const grid = text("div", "clips", ""); job.clips.forEach(c => grid.append(clipCard(c))); panel.append(grid);
  return panel;
}
function renderJobs(items) {
  const signature = JSON.stringify(items.map(j => [j.job, j.clips.length, j.can_refine, j.source_key]));
  if (signature === lastSignature) return;
  lastSignature = signature; jobsBox.replaceChildren();
  if (!items.length) { jobCount.textContent = "0 videos"; const empty = text("div", "empty", ""); empty.append(text("span", "", "✦"), text("h3", "", "Your next great clip starts here."), text("p", "", "Generate from a video above and your finished clips will appear here.")); jobsBox.append(empty); return; }
  const groups = new Map();
  for (const job of items) {
    const id = job.source_key || job.job;
    if (!groups.has(id)) groups.set(id, []);
    groups.get(id).push(job);
  }
  jobCount.textContent = `${groups.size} video${groups.size === 1 ? "" : "s"}`;
  for (const group of groups.values()) {
    jobsBox.append(jobPanel(group[0]));
    if (group.length > 1) {
      const history = document.createElement("details"); history.className = "job-history";
      history.append(text("summary", "", `Show ${group.length - 1} older run${group.length === 2 ? "" : "s"} of this video`));
      for (const job of group.slice(1)) history.append(jobPanel(job));
      jobsBox.append(history);
    }
  }
}
async function refresh() {
  try {
    const [state, library] = await Promise.all([json("/api/status"), json("/api/jobs")]);
    const running = state.status === "running"; generate.disabled = running;
    progressCard.hidden = !running;
    if (running) { const p = Math.max(0, Math.min(100, Math.round(Number(state.progress) * 100))); statusText.textContent = state.message; percent.textContent = `${p}%`; progressFill.style.width = `${p}%`; }
    if (state.status === "error") showError(state.message);
    if (pendingRefinement && state.status !== "running") {
      pendingRefinement.notice.textContent = state.status === "error" ? state.message : "Refined clip ready in your library.";
      pendingRefinement.submit.disabled = false;
      pendingRefinement = null;
    }
    renderJobs(library.jobs);
  } catch (err) { showError(`Cannot reach AUTOCLIP AI on Windows. Keep it running and use the same Wi-Fi. ${err.message}`); }
}
async function submitGenerate(force) {
  clearError(); runNotice.textContent = ""; runAgain.hidden = true;
  try {
    const result = await json("/api/jobs", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({url:urlInput.value.trim(), force})});
    if (result.status === "existing") {
      runNotice.textContent = "This video is already in your library. Another run with the same settings will repeat the clips.";
      runAgain.hidden = false;
      const target = document.getElementById(`job-${result.job}`);
      if (target) { const history = target.closest("details"); if (history) history.open = true; target.scrollIntoView({behavior:"smooth", block:"start"}); }
    } else { runNotice.textContent = "Processing started. Your clips will appear below."; await refresh(); }
  } catch (err) { showError(err.message); }
}
form.addEventListener("submit", event => { event.preventDefault(); submitGenerate(false); });
runAgain.addEventListener("click", () => submitGenerate(true));
localVideo.addEventListener("change", async () => {
  const file = localVideo.files && localVideo.files[0];
  if (!file) return;
  clearError();
  const match = /\.(mp4|mov|mkv|webm|m4v)$/i.exec(file.name);
  if (!match || file.size <= 0 || file.size > 10 * 1024 * 1024 * 1024) {
    showError("Choose an MP4, MOV, MKV, WEBM, or M4V video under 10 GB.");
    localVideo.value = "";
    return;
  }
  generate.disabled = true;
  progressCard.hidden = false;
  statusText.textContent = "Uploading video from iPhone";
  percent.textContent = "0%";
  progressFill.style.width = "0%";
  try {
    await json("/api/upload", {method:"POST", headers:{"Content-Type":"application/octet-stream","X-Video-Extension":`.`+match[1].toLowerCase()}, body:file});
    await refresh();
  } catch (err) { showError(err.message); generate.disabled = false; }
  finally { localVideo.value = ""; }
});
refresh(); setInterval(refresh, 2500);
