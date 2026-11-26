// A small fetch wrapper. Cookies carry the session. A 401 from any call
// tells the app to go back to Login. Errors carry the server's sentence.

export class ApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

let onUnauthorized: () => void = () => {};

export function setUnauthorizedHandler(handler: () => void): void {
  onUnauthorized = handler;
}

async function readDetail(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string" && body.detail) return body.detail;
  } catch {
    // Not JSON: fall through to the general sentence.
  }
  // The status code stays out of sight: the server log has the detail, by run id. Only a server fault
  // is worth trying again; a refusal with no sentence of its own would be refused again.
  return response.status >= 500 ? "That did not work. Try again." : "That could not be done.";
}

async function send(method: string, path: string, body?: BodyInit, headers?: HeadersInit): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(path, { method, credentials: "same-origin", headers, body });
  } catch {
    throw new ApiError(0, "The server cannot be reached. Try again.");
  }
  if (!response.ok) {
    const detail = await readDetail(response);
    if (response.status === 401) onUnauthorized();
    throw new ApiError(response.status, detail);
  }
  return response;
}

export async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const json = body !== undefined;
  const response = await send(
    method,
    path,
    json ? JSON.stringify(body) : undefined,
    json ? { "Content-Type": "application/json" } : undefined,
  );
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/** Sends one file as the multipart form field `file`. */
export async function uploadFile<T>(path: string, file: File): Promise<T> {
  const form = new FormData();
  form.append("file", file);
  const response = await send("POST", path, form);
  return (await response.json()) as T;
}

/** Fetches a file and hands it to the browser to save. */
export async function downloadFile(path: string, filename: string): Promise<void> {
  const response = await send("GET", path);
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return "Something went wrong.";
}
