// Keep the legacy tools available to administrators without bypassing session/CSRF checks.
(() => {
  const nativeFetch = window.fetch.bind(window);
  const identity = (async () => {
    const status = await nativeFetch("/api/auth/status").then((response) => response.json());
    if (!status.enabled) return null;
    const response = await nativeFetch("/api/auth/me");
    if (!response.ok) { location.replace("./workspace.html"); throw new Error("请先登录文档工作台"); }
    const current = await response.json();
    if (!current.user.is_admin) { location.replace("./workspace.html"); throw new Error("请使用文档工作台访问已授权项目"); }
    return current;
  })();
  // Initialization failures are also surfaced by each request, without an unhandled rejection.
  identity.catch(() => {});
  window.fetch = async (input, options = {}) => {
    const url = new URL(input instanceof Request ? input.url : String(input), location.href);
    if (url.origin !== location.origin || !url.pathname.startsWith("/api/")) return nativeFetch(input, options);
    const current = await identity;
    const method = (options.method || (input instanceof Request ? input.method : "GET")).toUpperCase();
    const headers = new Headers(options.headers || (input instanceof Request ? input.headers : undefined));
    if (current && !["GET", "HEAD"].includes(method)) headers.set("X-CSRF-Token", current.csrf_token);
    return nativeFetch(input, { ...options, headers });
  };
})();
