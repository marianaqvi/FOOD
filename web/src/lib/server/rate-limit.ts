// Small in-memory sliding-window limiter. Per instance only: good enough for the LAN proof of
// concept; production (Vercel) needs a shared store (milestone 5).
export class RateLimiter {
  private hits = new Map<string, number[]>();
  check(key: string, limit: number, windowMs: number, now: number): boolean {
    const arr = (this.hits.get(key) ?? []).filter((t) => now - t < windowMs);
    if (arr.length >= limit) {
      this.hits.set(key, arr);
      return false;
    }
    arr.push(now);
    this.hits.set(key, arr);
    if (this.hits.size > 5000) for (const [k, v] of this.hits) if (!v.length || now - v[v.length - 1] > windowMs) this.hits.delete(k);
    return true;
  }
}
