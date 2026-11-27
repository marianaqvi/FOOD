import { getDeps } from "@/lib/server/deps";
import * as h from "@/lib/server/handlers";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
export const POST = (req: Request) => h.logout(req, getDeps());
