import axios from "axios";

import { baseUrl } from "@/platform/config";

import { handleSessionExpiry } from "./session-expiry";

// Create axios instance with default config
const api = axios.create({
  baseURL: baseUrl,
  // CHANGE FROM MAIN: Increased default timeout from 10s to 180s (3 minutes)
  // Operations like file deletion with enrichment, metadata fetching, and large file uploads
  // can take longer than 10 seconds. Setting a reasonable default prevents premature timeouts.
  // Individual endpoints can override this if needed.
  timeout: 180 * 1000,
  headers: {
    "Content-Type": "application/json",
  },
});

api.interceptors.response.use(
  (response) => {
    if (response.data?.detail === "Not authenticated") {
      handleSessionExpiry();
    }
    return response;
  },
  (error) => {
    if (error.response && error.response.status === 401) {
      // If the proxy refreshed cookies behind the scenes, retry the request once
      if (
        error.response.headers["x-cookies-refreshed"] === "true" &&
        !error.config._retried
      ) {
        error.config._retried = true;
        return api.request(error.config);
      }

      // Any other 401 means the session is unrecoverable — log out.
      handleSessionExpiry();
    }
    return Promise.reject(error);
  },
);

// CHANGE FROM MAIN: Added TypeScript interfaces for document and chunk metadata
// These interfaces define the shape of metadata returned from the enrichment API
// Document metadata interface based on API documentation - includes fields like
// summary, topics, keywords, entities, and other document-level information
export default api;
