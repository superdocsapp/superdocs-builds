import JSZip from "jszip";

export async function docxPartXml(
  bytes: Uint8Array,
  partName: string,
): Promise<string> {
  const zip = await JSZip.loadAsync(bytes);
  const file = zip.file(partName);
  if (!file) {
    throw new Error(`DOCX is missing ${partName}`);
  }
  return file.async("string");
}

export async function docxFooterXml(bytes: Uint8Array): Promise<string[]> {
  const zip = await JSZip.loadAsync(bytes);
  const names = Object.keys(zip.files).filter((name) =>
    /^word\/footer\d+\.xml$/.test(name),
  );
  if (names.length === 0) {
    throw new Error("DOCX has no Word footer parts");
  }
  return Promise.all(names.map(async (name) => zip.file(name)!.async("string")));
}

export function xmlPlainText(xml: string): string {
  return [...xml.matchAll(/<w:t\b[^>]*>([^<]*)<\/w:t>/g)]
    .map((match) => match[1])
    .join("");
}
