export const ROAD_LOGIC_MODELER_PATH = "road_logic_modeler/index.html";

export function resolveRoadModelerUrl(baseUrl = "/") {
  const normalizedBase = baseUrl.endsWith("/") ? baseUrl : `${baseUrl}/`;
  return `${normalizedBase}${ROAD_LOGIC_MODELER_PATH}`;
}

export function roadModelerLinkAttributes(baseUrl = "/") {
  return {
    href: resolveRoadModelerUrl(baseUrl),
    target: "_blank",
    rel: "noopener noreferrer",
  };
}
