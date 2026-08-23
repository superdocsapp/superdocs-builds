function getTemplateDefinitions(): TemplateDefinition[] {
  // Kept as code so the add-on works without a runtime file system.
  return [
    { id: "software-engineer", name: "Software Engineer", aliases: ["software engineer","software developer","backend developer","frontend developer","full stack developer","web developer"], keywords: ["api","backend","frontend","javascript","typescript","python","java","database","software","programming"], fileName: "software-engineer.html" },
    { id: "data-ai", name: "Data & AI", aliases: ["data scientist","machine learning engineer","ml engineer","ai engineer","data analyst"], keywords: ["machine learning","model","analytics","data","pandas","tensorflow","pytorch","statistics","ai","ml"], fileName: "data-ai.html" },
    { id: "product-manager", name: "Product Manager", aliases: ["product manager","product owner","program manager"], keywords: ["roadmap","product","stakeholder","requirements","kpi","backlog","customer discovery"], fileName: "product-manager.html" },
    { id: "sales-executive", name: "Sales Executive", aliases: ["sales executive","sales representative","account executive","business development executive","bd executive"], keywords: ["sales","pipeline","prospecting","revenue","clients","accounts","negotiation","quota"], fileName: "sales-executive.html" },
    { id: "hr-executive", name: "HR Executive", aliases: ["hr executive","human resources executive","recruiter","talent acquisition","hr manager"], keywords: ["recruitment","hiring","employee relations","hr","talent","onboarding","payroll","people"], fileName: "hr-executive.html" },
    { id: "marketing-executive", name: "Marketing Executive", aliases: ["marketing executive","digital marketer","marketing manager","content marketer"], keywords: ["marketing","campaign","seo","content","brand","social media","lead generation"], fileName: "marketing-executive.html" },
    { id: "finance-analyst", name: "Finance Analyst", aliases: ["finance analyst","financial analyst","accountant","accounts executive","finance executive"], keywords: ["finance","financial","accounting","budget","forecast","reconciliation","audit","ledger"], fileName: "finance-analyst.html" },
    { id: "operations-manager", name: "Operations Manager", aliases: ["operations manager","operations executive","process manager","supply chain executive"], keywords: ["operations","process","supply chain","inventory","logistics","vendor","efficiency"], fileName: "operations-manager.html" },
    { id: "customer-support", name: "Customer Support", aliases: ["customer support","customer success","support executive","customer service executive"], keywords: ["customer service","support","ticket","helpdesk","customer success","sla","resolution"], fileName: "customer-support.html" },
    { id: "general", name: "General", aliases: ["general","other","miscellaneous"], keywords: [], fileName: "general.html" }
  ];
}

function normalizeText(value: RowValue): string {
  return String(value == null ? "" : value).trim().toLowerCase().replace(/\s+/g, " ");
}

function routeRow(row: RosterRow): RoutingResult {
  // `auto` (or an empty setting) enables row-by-row routing. A valid template
  // ID remains available when every row should intentionally use one template.
  var configuredTemplate = getScriptProperty(CONFIG.TEMPLATE_PROPERTY).trim().toLowerCase();
  var configuredDefinition = getTemplateDefinitions().filter(function (definition) {
    return definition.id === configuredTemplate;
  })[0];
  if (configuredDefinition && configuredTemplate !== "auto") {
    return { templateId: configuredDefinition.id, templateName: configuredDefinition.name, confidence: 1, method: "configured" };
  }

  var profile = normalizeText(row.values["Job Profile"] || row.values["JobProfile"] || "");
  var dynamicTemplate = profile ? getDynamicTemplateMap()[profile] : undefined;
  if (dynamicTemplate) {
    return { templateId: dynamicTemplate.templateId, templateName: dynamicTemplate.templateName, confidence: 1, method: "dynamic" };
  }

  // Safe fallback for deployments containing an invalid template property.
  var description = normalizeText(row.values["Job Description"] || row.values["JobDescription"] || "");
  var department = normalizeText(row.values["Department"] || "");
  var combined = [profile, description, department].filter(Boolean).join(" ");

  var definitions = getTemplateDefinitions();
  for (var i = 0; i < definitions.length; i++) {
    var exact = normalizeText(definitions[i].name);
    if (profile === exact) return { templateId: definitions[i].id, templateName: definitions[i].name, confidence: 1, method: "exact" };
  }
  for (var j = 0; j < definitions.length; j++) {
    if (definitions[j].aliases.some(function (alias) { return profile === alias; })) {
      return { templateId: definitions[j].id, templateName: definitions[j].name, confidence: 0.94, method: "alias" };
    }
  }

  var best = { definition: definitions[definitions.length - 1], score: 0 };
  definitions.slice(0, -1).forEach(function (definition) {
    var score = 0;
    definition.keywords.forEach(function (keyword) {
      if (combined.indexOf(keyword.toLowerCase()) !== -1) score += 1;
    });
    if (profile && definition.aliases.some(function (alias) { return profile.indexOf(alias) !== -1; })) score += 3;
    if (score > best.score) best = { definition: definition, score: score };
  });

  if (best.score >= 2) {
    var confidence = Math.min(0.9, 0.55 + best.score * 0.08);
    return { templateId: best.definition.id, templateName: best.definition.name, confidence: confidence, method: "keyword" };
  }

  return { templateId: "general", templateName: "General", confidence: 0.5, method: "general" };
}
