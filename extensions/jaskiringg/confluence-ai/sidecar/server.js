const path = require("path");
const fs = require("fs");
const express = require("express");
const cors = require("cors");
require("dotenv").config({ path: path.join(__dirname, "../.env") });

const { handlers } = require("../src/handlers");

const app = express();
app.use(cors());
app.use(express.json({ limit: "8mb" }));

app.post("/api/:action", async (req, res) => {
  const fn = handlers[req.params.action];
  if (!fn) return res.status(404).json({ error: `Unknown action ${req.params.action}` });
  try {
    const data = await fn(req.body || {}, {
      kind: "sidecar",
      apiKey: process.env.SUPERDOCS_API_KEY,
      pageId: req.body?.pageId,
      spaceId: req.body?.spaceId,
    });
    res.json(data);
  } catch (err) {
    console.error(req.params.action, err);
    res.status(err.status || 500).json({ error: err.message || String(err) });
  }
});

const uiBuild = path.join(__dirname, "../static/ui/build");
if (fs.existsSync(uiBuild)) {
  app.use(express.static(uiBuild));
  app.get("*", (_req, res) => res.sendFile(path.join(uiBuild, "index.html")));
}

const port = Number(process.env.SIDECAR_PORT || 8787);
app.listen(port, () => {
  console.log(`Confluence AI sidecar http://127.0.0.1:${port}`);
  console.log(process.env.SUPERDOCS_API_KEY ? "SuperDocs key: set" : "SuperDocs key: MISSING (.env)");
});
