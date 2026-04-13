/* ============================================
   KSU AUV Data Visualizer – Client Script
   ============================================ */

   
// 1. SPA page navigation (show/hide the 3 pages)
document.querySelectorAll(".nav-link").forEach(link => {
  link.addEventListener("click", e => {
    e.preventDefault();
    const target = link.dataset.target;
    document.querySelectorAll(".page").forEach(p => 
      p.classList.toggle("hidden", p.id !== target)
    );
    document.querySelectorAll(".nav-link").forEach(l =>
      l.classList.toggle("active", l === link)
    );
  });
});

// 2. Slider <-> number box sync (inputs form force, outputs M1-M8)
document.querySelectorAll("[data-sync]").forEach(slider => {
  const partner = document.getElementById(slider.dataset.sync);
  if (!partner) return;
  slider.addEventListener("input", () => partner.value = slider.value);
  partner.addEventListener("input", () => slider.value = partner.value);
});

// 3. Direction dropdown constraints
const opposites = {
  forward:"backward", backward:"forward",
  left:"right", right:"left",
  up:"down", down:"up",
  yaw_right:"yaw_left", yaw_left:"yaw_right"
};
const dir1 = document.getElementById("direction1");
const dir2 = document.getElementById("direction2");
if (dir1 && dir2) {
  function updateDirs() {
    [...dir2.options].forEach(o => o.disabled = 
      o.value === dir1.value || o.value === opposites[dir1.value]);
    [...dir1.options].forEach(o => o.disabled = 
      o.value === dir2.value || o.value === opposites[dir2.value]);
  }
  dir1.addEventListener("change", updateDirs);
  dir2.addEventListener("change", updateDirs);
}

// 4. Arm / fire toggle buttons (local state only)
document.querySelectorAll("[data-toggle]").forEach(btn => {
  btn.addEventListener("click", () => {
    const active = btn.dataset.toggleActive === "true";
    btn.dataset.toggleActive = String(!active);
    btn.textContent = !active ? btn.dataset.labelOn : btn.dataset.labelOff;
    // hidden input carries state into the HTMX form POST
    const input = document.getElementById(btn.dataset.toggle);
    if (input) input.value = !active ? "1" : "0";
  });
});

// 5. Chart.js — initialize charts (data comes from HTMX separately)
// ... chart setup here, ~10-15 lines per chart