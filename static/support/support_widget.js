(function () {
  const root = document.querySelector("[data-support-widget]");
  if (!root) {
    return;
  }

  const panel = root.querySelector("[data-support-widget-panel]");
  const toggle = root.querySelector("[data-support-widget-toggle]");
  const closeButton = root.querySelector("[data-support-widget-close]");
  const frame = root.querySelector("[data-support-widget-frame]");
  const retryButton = root.querySelector("[data-support-widget-retry]");
  const errorMessage = root.querySelector("[data-support-widget-error-message]");
  const embedUrl = root.dataset.embedUrl || "";
  const pageName = root.dataset.pageName || "Support";
  const loadTimeoutMs = 12000;

  let isOpen = false;
  let hasLoaded = false;
  let loadTimer = null;

  function clearLoadTimer() {
    if (loadTimer) {
      window.clearTimeout(loadTimer);
      loadTimer = null;
    }
  }

  function setStatus(status) {
    root.dataset.status = status;
  }

  function setError(message) {
    if (errorMessage) {
      errorMessage.textContent = message;
    }
    setStatus("error");
  }

  function loadFrame(forceReload) {
    if (!embedUrl) {
      setError("Support is not configured for this page.");
      return;
    }

    if (!navigator.onLine) {
      setError("You appear to be offline. Reconnect and try again.");
      return;
    }

    clearLoadTimer();
    setStatus("loading");

    if (forceReload) {
      hasLoaded = false;
      frame.removeAttribute("src");
    }

    if (!frame.getAttribute("src")) {
      frame.setAttribute("src", embedUrl);
    }

    loadTimer = window.setTimeout(function () {
      setError("Support took too long to load. You can retry or open it in a new tab.");
    }, loadTimeoutMs);
  }

  function setOpen(nextOpenState) {
    isOpen = nextOpenState;
    root.dataset.state = isOpen ? "open" : "closed";
    toggle.setAttribute("aria-expanded", String(isOpen));
    toggle.setAttribute("aria-label", isOpen ? "Close support" : "Open support");
    panel.setAttribute("aria-hidden", String(!isOpen));

    if (!isOpen) {
      clearLoadTimer();
      return;
    }

    if (!hasLoaded || root.dataset.status === "error") {
      loadFrame(root.dataset.status === "error");
    }
  }

  toggle.addEventListener("click", function () {
    setOpen(!isOpen);
  });

  if (closeButton) {
    closeButton.addEventListener("click", function () {
      setOpen(false);
    });
  }

  if (retryButton) {
    retryButton.addEventListener("click", function () {
      loadFrame(true);
    });
  }

  frame.addEventListener("load", function () {
    clearLoadTimer();
    hasLoaded = true;
    setStatus("ready");
  });

  frame.addEventListener("error", function () {
    clearLoadTimer();
    setError("Support could not be loaded right now.");
  });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && isOpen) {
      setOpen(false);
    }
  });

  document.addEventListener("click", function (event) {
    if (!isOpen || root.contains(event.target)) {
      return;
    }
    setOpen(false);
  });

  window.addEventListener("online", function () {
    if (isOpen && !hasLoaded) {
      loadFrame(true);
    }
  });

  toggle.title = pageName;
})();
