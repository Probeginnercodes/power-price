/* Local mode stays unchanged. Hosted mode adds an anonymous bearer session and API base URL. */
(function () {
  const configuration = window.FORECAST_CONFIG || {};
  if (!configuration.hosted) return;
  const originalFetch = window.fetch.bind(window);
  const apiBase = (configuration.apiBase || "").replace(/\/$/, "");
  let token = sessionStorage.getItem("forecast-demo-token:" + apiBase);
  let sessionPromise = null;
  async function session() {
    if (token) return token;
    if (!sessionPromise) {
      sessionPromise = originalFetch(apiBase + "/api/session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      })
        .then(async (response) => {
          const body = await response.json();
          if (!response.ok) throw Error(body.error || "Could not start demo session");
          token = body.token;
          sessionStorage.setItem("forecast-demo-token:" + apiBase, token);
          return token;
        })
        .finally(() => {
          sessionPromise = null;
        });
    }
    return sessionPromise;
  }
  window.fetch = async function (url, options = {}) {
    if (typeof url !== "string" || !url.startsWith("/api/")) return originalFetch(url, options);
    const bearer = await session();
    const response = await originalFetch(apiBase + url, {
      ...options,
      headers: { ...options.headers, Authorization: "Bearer " + bearer },
    });
    if (response.status === 401) {
      token = null;
      sessionStorage.removeItem("forecast-demo-token:" + apiBase);
    }
    return response;
  };
  // Download links need the same ownership check as JSON requests; never put tokens in URLs.
  document.addEventListener("click", async (event) => {
    const link = event.target.closest("a[download]");
    if (!link || !link.getAttribute("href")?.startsWith("/api/")) return;
    event.preventDefault();
    try {
      const response = await window.fetch(link.getAttribute("href"));
      if (!response.ok) throw Error((await response.json()).error || "Download unavailable");
      const objectUrl = URL.createObjectURL(await response.blob());
      const download = document.createElement("a");
      download.href = objectUrl;
      download.download = link.download;
      download.click();
      setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
    } catch (error) {
      document.getElementById("job").textContent = error.message;
    }
  });
  document.addEventListener("DOMContentLoaded", () => {
    const days = document.getElementById("days");
    days.max = "3";
    days.value = "1";
    document.getElementById("job").textContent =
      "Public demo: 1–3 days per run; one worker; results retained 24 hours.";
    document.getElementById("trial-accounting").textContent =
      "Hosted demo: jobs and results are isolated by anonymous session. The original development trial history remains incomplete; no final inference claim is made.";
    // A public visitor never sees another visitor's full research-trial ledger.
    document.querySelectorAll('a[href^="/api/research/"]').forEach((link) => link.remove());
  });
})();
