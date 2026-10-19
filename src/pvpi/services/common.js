// Shared by the dashboard's pages: helpers, and the light / dark toggle.
"use strict";
const $ = id => document.getElementById(id);
const fmt = (v, digits) => (v == null || Number.isNaN(v)) ? "–" : v.toFixed(digits);

// GET, or with `body` a JSON request (POST unless `method` says otherwise). Throws the server's error.
async function getJSON(url, body, method) {
  const options = { cache: "no-store" };
  if (body !== undefined || method) {
    options.method = method || "POST";
    if (body !== undefined) { options.headers = { "Content-Type": "application/json" }; options.body = JSON.stringify(body); }
  }
  const response = await fetch(url, options);
  const answer = await response.json();
  if (!response.ok) { const err = new Error(answer.error || response.statusText); err.answer = answer; throw err; }
  return answer;
}

// ---- Light / dark toggle: follows the device until picked, then remembered in this browser ----
const deviceDark = window.matchMedia("(prefers-color-scheme: dark)");
const currentTheme = () => document.documentElement.dataset.theme || (deviceDark.matches ? "dark" : "light");
function showTheme() {
  const label = currentTheme() === "dark" ? "Switch to light mode" : "Switch to dark mode";
  $("theme").setAttribute("aria-label", label);
  $("theme").title = label;
  window.dispatchEvent(new Event("themechange"));
}
$("theme").addEventListener("click", () => {
  const theme = currentTheme() === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = theme;
  try { localStorage.setItem("pvpi-theme", theme); } catch (e) {}
  showTheme();
});
deviceDark.addEventListener("change", showTheme);
showTheme();
