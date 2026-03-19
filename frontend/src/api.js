const API_BASE = (process.env.REACT_APP_API_BASE_URL || "http://127.0.0.1:8000").replace(/\/$/, "");

const toQueryString = (params = {}) => {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      query.append(key, String(value));
    }
  });
  const serialized = query.toString();
  return serialized ? `?${serialized}` : "";
};

const request = async (path, { method = "GET", body, headers } = {}) => {
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body,
  });

  const text = await res.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }

  if (!res.ok) {
    const error = new Error((data && data.error) || `Request failed (${res.status})`);
    error.status = res.status;
    error.payload = data;
    throw error;
  }

  return data;
};

export const api = {
  listSessions: () => request("/api/sessions/"),
  createSession: (name) =>
    request("/api/session/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    }),
  updateSession: (name, payload) =>
    request(`/api/session/${encodeURIComponent(name)}/`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  deleteSession: (name) =>
    request(`/api/session/${encodeURIComponent(name)}/`, { method: "DELETE" }),
  listHistory: (session) => request(`/api/history/${toQueryString({ session })}`),
  listPdfs: (session) => request(`/api/pdfs/${toQueryString({ session })}`),
  listMetrics: () => request("/api/metrics/summary/"),
  uploadPdf: (formData) =>
    new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", `${API_BASE}/api/upload/`);
      xhr.responseType = "text";

      xhr.onload = () => {
        const text = xhr.responseText || "";
        let data = null;
        try {
          data = text ? JSON.parse(text) : null;
        } catch {
          data = text;
        }

        if (xhr.status >= 200 && xhr.status < 300) {
          resolve(data);
          return;
        }

        const error = new Error((data && data.error) || `Request failed (${xhr.status})`);
        error.status = xhr.status;
        error.payload = data;
        reject(error);
      };

      xhr.onerror = () => reject(new Error("Upload failed"));
      xhr.onabort = () => {
        const error = new Error("Upload canceled");
        error.aborted = true;
        reject(error);
      };

      const onProgress = formData?.__onProgress;
      if (typeof onProgress === "function") {
        xhr.upload.onprogress = (event) => {
          if (!event.lengthComputable) return;
          onProgress(Math.round((event.loaded / event.total) * 100));
        };
      }

      const signal = formData?.__signal;
      if (signal) {
        signal.addEventListener("abort", () => xhr.abort(), { once: true });
      }

      delete formData.__onProgress;
      delete formData.__signal;
      xhr.send(formData);
    }),
  ask: (payload) =>
    request("/api/ask/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  deletePdf: (payload) =>
    request("/api/delete/", {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  retryDocument: (documentId) =>
    request(`/api/documents/${documentId}/retry/`, { method: "POST" }),
  getDocumentPageText: (documentId, page) =>
    request(`/api/documents/${documentId}/page-text/${toQueryString({ page })}`),
  searchExternal: ({ q, source }) =>
    request(`/api/search/external/${toQueryString({ q, source })}`),
  importExternal: (payload) =>
    request("/api/import/external/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  getRelatedPapers: ({ documentId, paperId, limit }) =>
    request(`/api/papers/related/${toQueryString({ document_id: documentId, paper_id: paperId, limit })}`),
  listHighlights: (params) => {
    if (typeof params === "number" || typeof params === "string") {
      return request(`/api/highlights/${toQueryString({ document_id: params })}`);
    }
    return request(`/api/highlights/${toQueryString(params || {})}`);
  },
  createHighlight: (payload) =>
    request("/api/highlights/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  deleteHighlight: (highlightId) =>
    request(`/api/highlights/${highlightId}/`, { method: "DELETE" }),
  searchHighlights: ({ session, q }) =>
    request(`/api/highlights/search/${toQueryString({ session, q })}`),
};

export { API_BASE };
