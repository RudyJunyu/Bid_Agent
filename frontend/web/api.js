export class ApiClient {
  constructor(base = `${location.origin}/api`) {
    this.base = base.replace(/\/$/, "");
    this.csrfToken = "";
  }

  async request(path, options = {}) {
    const headers = new Headers(options.headers || {});
    const method = options.method || "GET";
    if (this.csrfToken && !["GET", "HEAD"].includes(method)) headers.set("X-CSRF-Token", this.csrfToken);
    let body = options.body;
    if (body && !(body instanceof FormData)) {
      headers.set("Content-Type", "application/json");
      body = JSON.stringify(body);
    }
    const response = await fetch(`${this.base}${path}`, { ...options, method, headers, body, credentials: "same-origin" });
    const data = await response.json();
    if (!response.ok) {
      const error = new Error(typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail || data));
      error.status = response.status;
      throw error;
    }
    if (data.csrf_token !== undefined) this.csrfToken = data.csrf_token;
    return data;
  }
}
