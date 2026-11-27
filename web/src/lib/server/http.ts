export function json(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", "cache-control": "no-store", "x-content-type-options": "nosniff", ...headers },
  });
}
export function fail(status: number, code: string, errors: string[] = [], extra: Record<string, unknown> = {}): Response {
  return json({ error: code, errors, ...extra }, status);
}

/** Read a JSON body with a hard size cap (checked on the declared length and the actual text). */
export async function readJson(req: Request, maxBytes: number): Promise<{ ok: true; value: unknown } | { ok: false; res: Response }> {
  const declared = Number(req.headers.get("content-length") ?? "0");
  if (declared > maxBytes) return { ok: false, res: fail(413, "too_large", [`body over ${maxBytes} bytes`]) };
  const type = req.headers.get("content-type") ?? "";
  if (!type.toLowerCase().startsWith("application/json")) return { ok: false, res: fail(415, "unsupported_media_type", ["send application/json"]) };
  const text = await req.text();
  if (new TextEncoder().encode(text).length > maxBytes) return { ok: false, res: fail(413, "too_large", [`body over ${maxBytes} bytes`]) };
  try {
    return { ok: true, value: JSON.parse(text) };
  } catch {
    return { ok: false, res: fail(400, "bad_json", ["body is not valid JSON"]) };
  }
}

export function clientKey(req: Request): string {
  const fwd = req.headers.get("x-forwarded-for");
  return (fwd ? fwd.split(",")[0].trim() : "") || "local";
}
