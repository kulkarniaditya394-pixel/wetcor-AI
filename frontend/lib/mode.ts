/** Hosted static-demo mode (Netlify): no backend exists; only the pre-computed showcase is available.
 *  Set NEXT_PUBLIC_STATIC_DEMO=1 at build time. A function so tests can toggle it. */
export const isStaticDemo = () => process.env.NEXT_PUBLIC_STATIC_DEMO === "1";

export const REPO_URL = "https://github.com/kulkarniaditya394-pixel/wetcor-AI";
export const SNAPSHOT_URL = "/showcase-static/snapshot.json";
