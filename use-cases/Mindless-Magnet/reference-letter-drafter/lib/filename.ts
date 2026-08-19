/** Export filename base from a subject's name, shared everywhere a download is offered. */
export function filenameFor(subjectName: string): string {
  return subjectName.replace(/\s+/g, "-").toLowerCase() || "reference-letter";
}
