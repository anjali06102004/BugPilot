import { NextRequest } from "next/server";

/**
 * Server-side proxy for the BugPilot API.
 *
 * In production the dashboard is served with `BUGPILOT_API_URL` and
 * `BUGPILOT_API_KEY` on the server only, so the API key is never shipped to the
 * browser. The client uses `/backend` as its base URL.
 *
 * This route intentionally forwards only `/api/v1` paths and never exposes the
 * key to the response.
 */

const API_URL = (process.env.BUGPILOT_API_URL || "http://localhost:8000").replace(/\/$/, "");
const API_KEY = process.env.BUGPILOT_API_KEY || "";

const FORWARDED_HEADERS = ["content-type", "accept", "x-request-id"];

async function handler(request: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params;
  const target = `${API_URL}/api/v1/${path.join("/")}${request.nextUrl.search}`;

  const headers = new Headers();
  for (const name of FORWARDED_HEADERS) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  if (API_KEY) headers.set("x-api-key", API_KEY);

  const init: RequestInit = { method: request.method, headers, cache: "no-store" };
  if (request.method !== "GET" && request.method !== "HEAD") {
    init.body = await request.text();
  }

  try {
    const upstream = await fetch(target, init);
    const body = await upstream.arrayBuffer();
    const response = new Response(body, { status: upstream.status });
    const contentType = upstream.headers.get("content-type");
    if (contentType) response.headers.set("content-type", contentType);
    const disposition = upstream.headers.get("content-disposition");
    if (disposition) response.headers.set("content-disposition", disposition);
    return response;
  } catch {
    return Response.json(
      {
        detail: {
          code: "upstream_unreachable",
          message: "The BugPilot API could not be reached.",
          details: null,
        },
      },
      { status: 502 },
    );
  }
}

export const GET = handler;
export const POST = handler;
export const PATCH = handler;
export const PUT = handler;
export const DELETE = handler;