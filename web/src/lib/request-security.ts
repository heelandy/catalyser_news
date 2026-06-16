export function isSameOriginRequest(request: Request, expectedOrigin: string) {
  const origin = request.headers.get("origin");
  if (!origin) return true;
  try {
    return new URL(origin).origin === new URL(expectedOrigin).origin;
  } catch {
    return false;
  }
}

export function rejectCrossOriginRequest(
  request: Request,
  expectedOrigin: string,
) {
  if (isSameOriginRequest(request, expectedOrigin)) return null;
  return Response.json(
    { error: "Cross-origin request rejected." },
    { status: 403 },
  );
}
