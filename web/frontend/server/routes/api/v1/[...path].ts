// Same-origin local-development proxy; production can route these paths directly to FastAPI.
export default defineEventHandler(async (event) => {
  const config = useRuntimeConfig(event);
  if (String(config.public.authEnabled) !== "true")
    throw createError({ statusCode: 404 });
  const path = getRouterParam(event, "path") || "";
  if (!/^(auth|users)\/[a-zA-Z0-9/_-]+$/.test(path))
    throw createError({ statusCode: 404 });
  const query = getRequestURL(event).search;
  const target = `${config.apiBaseInternal}/v1/${path}${query}`;
  return proxyRequest(event, target);
});
