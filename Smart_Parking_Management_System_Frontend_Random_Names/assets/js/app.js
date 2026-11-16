document.addEventListener("DOMContentLoaded", () => {
  // Current year
  document.querySelectorAll("[data-year]").forEach(el => el.textContent = new Date().getFullYear());

  // Password toggles
  document.querySelectorAll("[data-password-toggle]").forEach(btn => {
    btn.addEventListener("click", () => {
      const input = document.querySelector(btn.getAttribute("data-password-toggle"));
      if (!input) return;
      input.type = input.type === "password" ? "text" : "password";
      btn.classList.toggle("bi-eye");
      btn.classList.toggle("bi-eye-slash");
    });
  });

  // Demo alerts
  document.querySelectorAll("[data-demo-action]").forEach(btn => {
    btn.addEventListener("click", () => {
      const msg = btn.getAttribute("data-demo-action") || "Action completed.";
      const box = document.getElementById("demoToast");
      if (box) {
        box.querySelector(".toast-body").textContent = msg;
        bootstrap.Toast.getOrCreateInstance(box).show();
      } else {
        alert(msg);
      }
    });
  });

  // Slot selection
  document.querySelectorAll(".slot-card[data-slot-id]").forEach(card => {
    if (card.classList.contains("disabled")) return;
    card.addEventListener("click", () => {
      document.querySelectorAll(".slot-card[data-slot-id]").forEach(x => x.classList.remove("selected"));
      card.classList.add("selected");
      const slotName = card.querySelector(".slot-no")?.textContent?.trim() || "slot";
      const target = document.getElementById("selectedSlot");
      if (target) target.value = slotName;
      const summary = document.getElementById("slotSummary");
      if (summary) summary.textContent = `${slotName} selected`;
    });
  });

  // Simple booking form feedback
  const bookingForm = document.getElementById("bookingForm");
  if (bookingForm) {
    bookingForm.addEventListener("submit", (e) => {
      e.preventDefault();
      window.location.href = "payment.html";
    });
  }

  // Search/filter parking slots
  const search = document.getElementById("slotSearch");
  if (search) {
    search.addEventListener("input", () => {
      const q = search.value.toLowerCase().trim();
      document.querySelectorAll(".slot-card[data-slot-id]").forEach(card => {
        const text = card.textContent.toLowerCase();
        card.style.display = text.includes(q) ? "" : "none";
      });
    });
  }

  // Admin occupancy chart
  const ctx = document.getElementById("occupancyChart");
  if (ctx && window.Chart) {
    new Chart(ctx, {
      type: "line",
      data: {
        labels: ["8 AM","10 AM","12 PM","2 PM","4 PM","6 PM","8 PM"],
        datasets: [{
          label: "Occupied Slots",
          data: [28,42,56,71,64,49,37],
          tension: .35,
          fill: true
        }]
      },
      options: {
        responsive:true,
        plugins:{legend:{display:false}},
        scales:{y:{beginAtZero:true}}
      }
    });
  }
});
