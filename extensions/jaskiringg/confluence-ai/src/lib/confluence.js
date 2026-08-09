const DEMO_PAGE_ID = "demo-page";
const DEMO_SPACE_ID = "demo-space";

const DEMO_ADF = {
  type: "doc",
  version: 1,
  content: [
    {
      type: "heading",
      attrs: { level: 1 },
      content: [{ type: "text", text: "IT Change Policy — North Region" }],
    },
    {
      type: "paragraph",
      content: [
        {
          type: "text",
          text: "All production changes require a CAB ticket before cutover. Emergency changes still need a follow-up ticket within 24 hours.",
        },
      ],
    },
    {
      type: "heading",
      attrs: { level: 2 },
      content: [{ type: "text", text: "Freeze windows" }],
    },
    {
      type: "paragraph",
      content: [
        {
          type: "text",
          text: "North region freeze is 02:00-06:00 IST on release nights. No master-data edits during freeze.",
        },
      ],
    },
    {
      type: "table",
      attrs: { isNumberColumnEnabled: false, layout: "default" },
      content: [
        {
          type: "tableRow",
          content: [
            {
              type: "tableHeader",
              attrs: {},
              content: [{ type: "paragraph", content: [{ type: "text", text: "System" }] }],
            },
            {
              type: "tableHeader",
              attrs: {},
              content: [{ type: "paragraph", content: [{ type: "text", text: "Owner" }] }],
            },
          ],
        },
        {
          type: "tableRow",
          content: [
            {
              type: "tableCell",
              attrs: {},
              content: [{ type: "paragraph", content: [{ type: "text", text: "Order API" }] }],
            },
            {
              type: "tableCell",
              attrs: {},
              content: [{ type: "paragraph", content: [{ type: "text", text: "Platform" }] }],
            },
          ],
        },
      ],
    },
    {
      type: "heading",
      attrs: { level: 2 },
      content: [{ type: "text", text: "Rollback" }],
    },
    {
      type: "paragraph",
      content: [
        {
          type: "text",
          text: "If error rate exceeds 2% after cutover, roll back within 15 minutes and page the on-call.",
        },
      ],
    },
    {
      type: "codeBlock",
      attrs: { language: "bash" },
      content: [{ type: "text", text: "kubectl rollout undo deploy/order-api" }],
    },
  ],
};

function loadDemoAdf() {
  return JSON.parse(JSON.stringify(DEMO_ADF));
}

function authHeader(email, token) {
  return `Basic ${Buffer.from(`${email}:${token}`).toString("base64")}`;
}

function confluenceConfigured(env) {
  return !!(env.CONFLUENCE_BASE_URL && env.CONFLUENCE_EMAIL && env.CONFLUENCE_API_TOKEN);
}

function liveConfluence(env, id) {
  if (id && String(id).startsWith("demo")) return false;
  return !!(env.useForgeApi || confluenceConfigured(env));
}

async function forgeFetch(pathname, { method = "GET", body } = {}) {
  const { asApp, assumeTrustedRoute } = require("@forge/api");
  const res = await asApp().requestConfluence(assumeTrustedRoute(pathname), {
    method,
    headers: {
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

async function productFetch(env, pathname, opts) {
  if (env.useForgeApi) return forgeFetch(pathname, opts);
  return cfFetch(env, pathname, opts);
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
  if (!liveConfluence(env, pageId)) {
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
  const page = await productFetch(
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
  if (!liveConfluence(env, pageId)) {
    return {
      id: DEMO_PAGE_ID,
      title,
      version: { number: (versionNumber || 1) + 1, message },
      demo: true,
      adf,
    };
  }
  return productFetch(env, `/wiki/api/v2/pages/${encodeURIComponent(pageId)}`, {
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
  if (!liveConfluence(env, spaceId) || spaceId === DEMO_SPACE_ID) {
    return [
      { id: DEMO_PAGE_ID, title: "IT Change Policy — North Region", status: "current" },
      { id: "demo-page-2", title: "Go-live checklist (draft)", status: "current" },
      { id: "demo-page-3", title: "SIT notes — week 12", status: "current" },
    ];
  }
  const data = await productFetch(
    env,
    `/wiki/api/v2/spaces/${encodeURIComponent(spaceId)}/pages?limit=50&status=current`
  );
  return (data.results || []).map((p) => ({
    id: String(p.id),
    title: p.title,
    status: p.status,
  }));
}

function mapUser(u) {
  if (!u) return null;
  return {
    accountId: u.accountId,
    displayName: u.displayName || u.publicName || u.email,
    email: u.email,
  };
}

async function searchUsers(env, query) {
  if (!liveConfluence(env)) {
    return [
      { accountId: "demo-approver", displayName: "Priya Sharma (demo)", email: "priya@example.com" },
      { accountId: "demo-author", displayName: "Jaskirat Singh (demo)", email: "singhjass6404@gmail.com" },
    ].filter((u) => !query || u.displayName.toLowerCase().includes(query.toLowerCase()));
  }
  try {
    const q = String(query || "").trim();
    if (!q) {
      const me = await productFetch(env, "/wiki/rest/api/user/current");
      const mapped = mapUser(me);
      return mapped ? [mapped] : [];
    }
    const data = await productFetch(
      env,
      `/wiki/rest/api/user/search?query=${encodeURIComponent(q)}&limit=10`
    );
    const rows = Array.isArray(data) ? data : data.results || [];
    return rows.map(mapUser).filter(Boolean);
  } catch {
    return [
      {
        accountId: "current-user",
        displayName: "Jaskirat Singh",
        email: env.CONFLUENCE_EMAIL || "singhjass6404@gmail.com",
      },
    ];
  }
}

const PROPERTY_KEY = "superdocs-review";

async function getReviewState(env, pageId, memory) {
  if (memory.has(pageId)) return memory.get(pageId);
  if (!liveConfluence(env, pageId) || pageId === DEMO_PAGE_ID) {
    return { status: "draft" };
  }
  try {
    const data = await productFetch(
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
  if (!liveConfluence(env, pageId) || pageId === DEMO_PAGE_ID) return value;
  try {
    await productFetch(
      env,
      `/wiki/rest/api/content/${encodeURIComponent(pageId)}/property/${PROPERTY_KEY}`,
      { method: "PUT", body: { key: PROPERTY_KEY, value } }
    );
  } catch {
    await productFetch(
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
