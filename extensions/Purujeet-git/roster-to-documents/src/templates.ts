function getTemplateBody(templateId: string): string {
  var folderId = getScriptProperty(CONFIG.TEMPLATE_FOLDER_PROPERTY);
  if (folderId) {
    var files = DriveApp.getFolderById(folderId).getFilesByName(templateId + ".html");
    if (files.hasNext()) return files.next().getBlob().getDataAsString();
  }
  if (templateId.indexOf("dynamic-") === 0) {
    throw new Error("Dynamic template file not found: " + templateId + ". Run preview again to regenerate templates.");
  }
  var allowed = getTemplateDefinitions().some(function (template) { return template.id === templateId; });
  var selected = allowed ? templateId : "general";
  return HtmlService.createTemplateFromFile("templates/" + selected).getRawContent();
}

function getDynamicTemplateMap(): Record<string, DynamicTemplateRecord> {
  var raw = getScriptProperty(CONFIG.DYNAMIC_TEMPLATE_MAP_PROPERTY);
  if (!raw) return {};
  try {
    return JSON.parse(raw) as Record<string, DynamicTemplateRecord>;
  } catch (_error) {
    return {};
  }
}

function saveDynamicTemplateMap(map: Record<string, DynamicTemplateRecord>): void {
  PropertiesService.getScriptProperties().setProperty(CONFIG.DYNAMIC_TEMPLATE_MAP_PROPERTY, JSON.stringify(map));
}

function dynamicTemplateId(profile: string): string {
  var slug = normalizeText(profile).replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 60);
  return "dynamic-" + (slug || "general");
}

function getTemplateFolder(): any {
  var folderId = getScriptProperty(CONFIG.TEMPLATE_FOLDER_PROPERTY);
  var folder = folderId ? DriveApp.getFolderById(folderId) : DriveApp.createFolder("Roster to Documents Templates");
  if (!folderId) PropertiesService.getScriptProperties().setProperty(CONFIG.TEMPLATE_FOLDER_PROPERTY, folder.getId());
  return folder;
}

function generateDynamicTemplate(profile: string, folder: any): DynamicTemplateRecord {
  var templateId = dynamicTemplateId(profile);
  var templateName = profile + " Template";
  var starter = "<html><body><h1>" + escapeHtml(profile) + " Employment Document</h1><p>Dear {{Name}},</p><p>Role: {{JobProfile}}</p><p>Department: {{Department}}</p><p>{{JobDescription}}</p><p>Sincerely,<br>HR / Administration</p></body></html>";
  var prompt = "Create a polished professional employment document template specifically for the job profile '" + profile + "'. Preserve these placeholders exactly: {{Name}}, {{Email}}, {{JobProfile}}, {{JobDescription}}, {{Department}}, {{Salary}}, {{Remote}}. Use clean semantic HTML, preserve data-chunk-id attributes, and do not invent employee-specific facts.";
  var refined = refineDocumentWithSuperDocs(starter, prompt, "dynamic-template-generation-" + templateId);
  folder.createFile(Utilities.newBlob(refined, "text/html", templateId + ".html"));
  return { profile: profile, templateId: templateId, templateName: templateName };
}

function prepareDynamicTemplatesForSheet(sheet: any): { generated: string[]; reused: string[]; folderId: string } {
  var rows = readRosterRows(sheet);
  var profiles: Record<string, string> = {};
  rows.forEach(function (row) {
    var original = String(row.values["Job Profile"] || row.values["JobProfile"] || "").trim();
    var normalized = normalizeText(original);
    if (normalized && !profiles[normalized]) profiles[normalized] = original;
  });
  var map = getDynamicTemplateMap();
  var folder = getTemplateFolder();
  var generated: string[] = [];
  var reused: string[] = [];
  Object.keys(profiles).forEach(function (normalized) {
    if (map[normalized]) {
      reused.push(profiles[normalized]);
      return;
    }
    map[normalized] = generateDynamicTemplate(profiles[normalized], folder);
    generated.push(profiles[normalized]);
  });
  saveDynamicTemplateMap(map);
  return { generated: generated, reused: reused, folderId: folder.getId() };
}

function generateTemplateWithSuperDocs(templateId: string): any {
  var definition = getTemplateDefinitions().filter(function (template) { return template.id === templateId; })[0];
  if (!definition) throw new Error("Unknown template id: " + templateId);
  var starter = "<html><body><h1>" + definition.name + " Employment Document</h1><p>Dear {{Name}},</p><p>Role: {{JobProfile}}</p><p>Department: {{Department}}</p><p>{{JobDescription}}</p><p>Sincerely,<br>HR / Administration</p></body></html>";
  var prompt = "Create a polished, professional employment/appointment document template for the job family '" + definition.name + "'. Preserve these placeholders exactly: {{Name}}, {{Email}}, {{JobProfile}}, {{JobDescription}}, {{Department}}, {{Salary}}, {{Remote}}. Use clean semantic HTML and preserve the document's data-chunk-id attributes. Do not invent employee-specific facts. Include a strong structure appropriate to the job family, while keeping factual fields as placeholders.";
  var refined = refineDocumentWithSuperDocs(starter, prompt, "template-generation-" + definition.id);
  return Utilities.newBlob(refined, "text/html", definition.id + ".html");
}

function generateAllTemplatesWithSuperDocs(): { generated: string[]; folderId: string } {
  var folderId = getScriptProperty(CONFIG.TEMPLATE_FOLDER_PROPERTY);
  var folder = folderId ? DriveApp.getFolderById(folderId) : DriveApp.createFolder("Roster to Documents Templates");
  if (!folderId) PropertiesService.getScriptProperties().setProperty(CONFIG.TEMPLATE_FOLDER_PROPERTY, folder.getId());
  var generated: string[] = [];
  getTemplateDefinitions().forEach(function (definition) {
    var blob = generateTemplateWithSuperDocs(definition.id);
    folder.createFile(blob);
    generated.push(definition.id);
  });
  return { generated: generated, folderId: folder.getId() };
}
