import { NextRequest, NextResponse } from "next/server";
export const runtime = "nodejs";
async function proxy(request: NextRequest, context: {params: Promise<{path: string[]}>}) {
  const path = (await context.params).path.join("/");
  if (!((request.method === "GET" && path === "dashboard") || (request.method === "POST" && (path === "sessions" || /^callbacks\/[a-zA-Z0-9-]+$/.test(path)))))
    return NextResponse.json({detail: "Not found"}, {status: 404});
  // This console is a local demo. Mutations must originate from the same browser origin.
  if (request.method === "POST" && request.headers.get("origin") !== request.nextUrl.origin)
    return NextResponse.json({detail: "Invalid origin"}, {status: 403});
  if (!process.env.BACKEND_API_KEY)
    return NextResponse.json({detail: "frontend/.env.local içindeki BACKEND_API_KEY alanını doldurun."}, {status: 503});
  try {
    const response = await fetch(`${process.env.BACKEND_URL || "http://127.0.0.1:8000"}/${path}`, {
      method: request.method, headers: {"Content-Type": "application/json", "X-API-Key": process.env.BACKEND_API_KEY},
      body: request.method === "POST" ? await request.text() : undefined,
      cache: "no-store", signal: AbortSignal.timeout(15000),
    });
    return new NextResponse(await response.text(), {status: response.status, headers: {"Content-Type": "application/json"}});
  } catch {
    return NextResponse.json({detail: "Python API'ye ulaşılamıyor. Backend servisini başlatın."}, {status: 502});
  }
}
export { proxy as GET, proxy as POST };
