const fs = require("fs");
const path = require("path");

const DEMO_PAGE_ID = "demo-page";
const DEMO_SPACE_ID = "demo-space";

function loadDemoAdf() {
  const p = path.join(__dirname, "../../fixtures/demo-page.adf.json");
  return JSON.parse(fs.readFileSync(p, "utf8"));
}

function authHeader(email, token) {
  return `Basic ${Buffer.from(`${email}:${token}`).toString("base64")}`;
}

function confluenceConfigured(env) {
  return !!(env.CONFLUENCE_BASE_URL && env.CONFLUENCE_EMAIL && env.CONFLUENCE_API_TOKEN);
}

async function cfFetch(env, pathname, { method = "GET", body } = {}) {
  const url = `${env.CONFLUENCE_BASE_URL.replace(/\/$/, "")}${pathname}`;
  const res = await fetch(url, {
    method,
    headers: {
      Authorization: authHeader(env.CONFLUENCE_EMAIL, env.CONFLUENCE_API_TOKEN),
      Accept: "application/json",
      ...(body ? { "Content-Type": "application/json" } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) {
    throw new Error(`Confluence ${res.status}: ${text.slice(0, 500)}`);
  }
  return data;
}

function parseAdfFromPage(page) {
  const value =
    page?.body?.atlas_doc_format?.value ||
    page?.body?.value ||
    null;
  if (!value) throw new Error("Page has no atlas_doc_format body");
  return typeof value === "string" ? JSON.parse(value) : value;
}

const DEMO_TITLES = {
  [DEMO_PAGE_ID]: "IT Change Policy — North Region",
  "demo-page-2": "Go-live checklist (draft)",
  "demo-page-3": "SIT notes — week 12",
};

async function getPage(env, pageId) {
  if (!confluenceConfigured(env) || String(pageId).startsWith("demo")) {
    const adf = loadDemoAdf();
    if (pageId === "demo-page-2") {
      adf.content[0] = {
        type: "heading",
        attrs: { level: 1 },
        content: [{ type: "text", text: "Go-live checklist (draft)" }],
      };
    }
    if (pageId === "demo-page-3") {
      adf.content[0] = {
        type: "heading",
        attrs: { level: 1 },
        content: [{ type: "text", text: "SIT notes — week 12" }],
      };
    }
    return {
      id: String(pageId),
      title: DEMO_TITLES[pageId] || "Demo page",
      status: "current",
      spaceId: DEMO_SPACE_ID,
      version: { number: 1 },
      adf,
      demo: true,
    };
  }
  const page = await cfFetch(
    env,
    `/wiki/api/v2/pages/${encodeURIComponent(pageId)}?body-format=atlas_doc_format`
  );
  return {
    id: String(page.id),
    title: page.title,
    status: page.status,
    spaceId: String(page.spaceId),
    version: page.version,
    adf: parseAdfFromPage(page),
    demo: false,
  };
}

async function updatePage(env, { pageId, title, adf, versionNumber, message }) {
  if (!confluenceConfigured(env) || String(pageId).startsWith("demo")) {
    return {
      id: DEMO_PAGE_ID,
      title,
      version: { number: (versionNumber || 1) + 1, message },
      demo: true,
      adf,
    };
  }
  return cfFetch(env, `/wiki/api/v2/pages/${encodeURIComponent(pageId)}`, {
    method: "PUT",
    body: {
      id: String(pageId),
      status: "current",
      title,
      body: {
        representation: "atlas_doc_format",
        value: JSON.stringify(adf),
      },
      version: {
        number: versionNumber + 1,
        message: message || "SuperDocs AI edit (approved batch)",
      },
    },
  });
}

async function listSpacePages(env, spaceId) {
  if (!confluenceConfigured(env) || spaceId === DEMO_SPACE_ID) {
    return [
      { id: DEMO_PAGE_ID, title: "IT Change Policy — North Region", status: "current" },
      { id: "demo-page-2", title: "Go-live checklist (draft)", status: "current" },
      { id: "demo-page-3", title: "SIT notes — week 12", status: "current" },
    ];
  }
  const data = await cfFetch(
    env,
    `/wiki/api/v2/spaces/${encodeURIComponent(spaceId)}/pages?limit=50&status=current`
  );
  return (data.results || []).map((p) => ({
    id: String(p.id),
    title: p.title,
    status: p.status,
  }));
}

async function searchUsers(env, query) {
  if (!confluenceConfigured(env)) {
    return [
      { accountId: "demo-approver", displayName: "Priya Sharma (demo)", email: "priya@example.com" },
      { accountId: "demo-author", displayName: "Jaskirat Singh (demo)", email: "singhjass6404@gmail.com" },
    ].filter((u) => !query || u.displayName.toLowerCase().includes(query.toLowerCase()));
  }
  const data = await cfFetch(
    env,
    `/wiki/rest/api/search/user?cql=${encodeURIComponent(`user.fullname~"${query}"`)}&limit=10`
  );
  return (data.results || []).map((r) => ({
    accountId: r.user?.accountId,
    displayName: r.user?.displayName,
    email: r.user?.email,
  }));
}

const PROPERTY_KEY = "superdocs-review";

async function getReviewState(env, pageId, memory) {
  if (memory.has(pageId)) return memory.get(pageId);
  if (!confluenceConfigured(env) || pageId === DEMO_PAGE_ID) {
    return { status: "draft" };
  }
  try {
    const data = await cfFetch(
      env,
      `/wiki/rest/api/content/${encodeURIComponent(pageId)}/property/${PROPERTY_KEY}`
    );
    return data.value || { status: "draft" };
  } catch {
    return { status: "draft" };
  }
}

async function setReviewState(env, pageId, value, memory) {
  memory.set(pageId, value);
  if (!confluenceConfigured(env) || pageId === DEMO_PAGE_ID) return value;
  try {
    await cfFetch(
      env,
      `/wiki/rest/api/content/${encodeURIComponent(pageId)}/property/${PROPERTY_KEY}`,
      { method: "PUT", body: { key: PROPERTY_KEY, value } }
    );
  } catch {
    await cfFetch(
      env,
      `/wiki/rest/api/content/${encodeURIComponent(pageId)}/property`,
      { method: "POST", body: { key: PROPERTY_KEY, value } }
    );
  }
  return value;
}

module.exports = {
  DEMO_PAGE_ID,
  DEMO_SPACE_ID,
  confluenceConfigured,
  getPage,
  updatePage,
  listSpacePages,
  searchUsers,
  getReviewState,
  setReviewState,
  loadDemoAdf,
};
