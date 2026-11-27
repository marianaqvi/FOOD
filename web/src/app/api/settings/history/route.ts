import { getDeps } from "@/lib/server/deps";
import * as h from "@/lib/server/handlers";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
export const GET = (req: Request) => h.getHistory(req, getDeps());
