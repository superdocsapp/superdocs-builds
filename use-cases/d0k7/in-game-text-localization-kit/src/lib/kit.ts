export type GameString = {
  id: string;
  source: string;
  characterLimit: number;
  speaker: string;
  scene: string;
  gender?: "female" | "male" | "neutral" | "variable";
  plural?: boolean;
};

export type KitInput = {
  game: string;
  targetLanguage: string;
  world: string;
  tone: string;
  doNotTranslate: string[];
  styleRules: string[];
  strings: GameString[];
};

const escape = (text: string) => text.replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" })[char] ?? char);
const chunk = (index: number) => `00000000-0000-4000-8000-${String(index).padStart(12, "0")}`;

export function makeKitHtml(input: KitInput): string {
  const rows = input.strings.map(item => `<tr><td><code>${escape(item.id)}</code></td><td>${escape(item.source)}</td><td>${item.characterLimit}</td><td>${escape(item.speaker || "Unassigned")}</td><td>${escape(item.scene || "No scene note")}</td><td>${item.gender ?? "n/a"}${item.plural ? ", plural" : ""}</td></tr>`).join("");
  const list = (values: string[]) => values.length ? `<ul>${values.map(value => `<li>${escape(value)}</li>`).join("")}</ul>` : "<p>None supplied. Preserve all named people, places, items, variables and markup until the producer confirms otherwise.</p>";
  return `<!doctype html><html><head><meta charset="utf-8"><title>${escape(input.game)} ${escape(input.targetLanguage)} Localization Kit</title></head><body>
  <h1 data-chunk-id="${chunk(1)}">${escape(input.game)}: ${escape(input.targetLanguage)} Localization Kit</h1>
  <h2 data-chunk-id="${chunk(2)}">Translator context</h2><p data-chunk-id="${chunk(3)}">${escape(input.world)}</p><p data-chunk-id="${chunk(4)}"><strong>Tone:</strong> ${escape(input.tone)}</p>
  <h2 data-chunk-id="${chunk(5)}">String table</h2><table data-chunk-id="${chunk(6)}" border="1"><thead><tr><th>ID</th><th>English source</th><th>Limit</th><th>Speaker</th><th>Scene note</th><th>Variables</th></tr></thead><tbody>${rows}</tbody></table>
  <h2 data-chunk-id="${chunk(7)}">Do not translate</h2>${list(input.doNotTranslate)}<h2 data-chunk-id="${chunk(8)}">Style sheet</h2>${list(input.styleRules)}
  </body></html>`;
}

export const exampleInput: KitInput = {
  game: "Ashfall Protocol",
  targetLanguage: "Japanese",
  world: "A flooded orbital shipyard in 2189. The crew is repairing an evacuation vessel while a corporate salvage team closes in.",
  tone: "Tense, capable, spare. Engineers speak plainly under pressure. Keep radio calls short enough to read during combat.",
  doNotTranslate: ["Aegis-9", "Vanta Core", "Rook", "{playerName}", "[BTN_INTERACT]", "<c=warning>"],
  styleRules: ["Preserve tokens, tags and punctuation inside tokens exactly.", "Keep tactical calls concise. Avoid honorifics unless the English source signals rank.", "Use full-width punctuation for Japanese dialogue, but do not change protected tokens."],
  strings: [
    { id: "HUD.REACTOR.OVERLOAD", source: "REACTOR OVERLOAD: {seconds}s", characterLimit: 28, speaker: "System", scene: "HUD warning during repair", gender: "neutral" },
    { id: "DIA.ROOK.ENTRY", source: "Rook, seal bay three. Now.", characterLimit: 36, speaker: "Mara", scene: "First salvage-team breach", gender: "female" },
    { id: "OBJ.SALVAGE", source: "Recover [ITEM_VANTA_CORE]", characterLimit: 30, speaker: "System", scene: "Optional objective", plural: false }
  ]
};
