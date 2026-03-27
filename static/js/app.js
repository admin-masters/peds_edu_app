document.addEventListener("DOMContentLoaded", function () {
  var header = document.getElementById("siteHeader");
  var nav = document.getElementById("siteNav");
  var toggle = document.getElementById("navToggle");

  function syncShadow() {
    if (!header) {
      return;
    }
    header.classList.toggle("is-scrolled", window.scrollY > 8);
  }

  function setOpen(open) {
    if (!header || !toggle) {
      return;
    }
    header.classList.toggle("is-open", open);
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
  }

  syncShadow();
  window.addEventListener("scroll", syncShadow, { passive: true });

  document.querySelectorAll("[data-phone-kind]").forEach(function (link) {
    var phoneKind = link.getAttribute("data-phone-kind");
    var rawNumber = link.getAttribute("data-phone-number") || "";
    var digits = rawNumber.replace(/\D+/g, "");

    if (!digits) {
      link.setAttribute("aria-disabled", "true");
      link.removeAttribute("href");
      return;
    }

    if (phoneKind === "call") {
      link.setAttribute("href", "tel:" + digits);
      return;
    }

    if (phoneKind === "whatsapp") {
      if (digits.length === 10) {
        digits = "91" + digits;
      }
      link.setAttribute("href", "https://wa.me/" + digits);
      link.setAttribute("target", "_blank");
      link.setAttribute("rel", "noopener noreferrer");
    }
  });

  if (!header || !nav || !toggle) {
    return;
  }

  toggle.addEventListener("click", function () {
    setOpen(!header.classList.contains("is-open"));
  });

  nav.querySelectorAll("a").forEach(function (link) {
    link.addEventListener("click", function () {
      setOpen(false);
    });
  });

  document.addEventListener("click", function (event) {
    if (!header.contains(event.target)) {
      setOpen(false);
    }
  });

  window.addEventListener("resize", function () {
    if (window.innerWidth > 1023) {
      setOpen(false);
    }
  });
});
