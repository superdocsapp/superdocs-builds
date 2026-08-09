const Resolver = require("@forge/resolver").default;
const { handlers } = require("./handlers");

const resolver = new Resolver();

for (const [name, fn] of Object.entries(handlers)) {
  resolver.define(name, async (req) => {
    const pageId = req.context?.extension?.content?.id;
    const spaceId = req.context?.extension?.space?.id;
    const apiKey = process.env.SUPERDOCS_API_KEY;
    return fn(req.payload || {}, { pageId, spaceId, apiKey, kind: "forge", context: req.context });
  });
}

exports.handler = resolver.getDefinitions();
