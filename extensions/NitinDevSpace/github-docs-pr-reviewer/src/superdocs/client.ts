export type SuperDocsExportFormat = "docx" | "pdf";

export type SuperDocsExportInput = {
  html: string;
  title: string;
  format: SuperDocsExportFormat;
  idempotencyKey: string;
};

export type SuperDocsExportResult = {
  data: Uint8Array;
  contentType: string;
  filename: string;
};

export interface SuperDocsClient {
  exportDocument(input: SuperDocsExportInput): Promise<SuperDocsExportResult>;
}

export class HttpSuperDocsClient implements SuperDocsClient {
  private readonly baseUrl: string;
  private readonly apiKey: string;
  private readonly fetchImpl: typeof fetch;

  constructor({
    apiKey,
    baseUrl,
    fetchImpl = fetch
  }: {
    apiKey: string;
    baseUrl: string;
    fetchImpl?: typeof fetch;
  }) {
    this.apiKey = apiKey;
    this.baseUrl = baseUrl.replace(/\/$/, "");
    this.fetchImpl = fetchImpl;
  }

  async exportDocument(input: SuperDocsExportInput): Promise<SuperDocsExportResult> {
    const response = await this.fetchImpl(`${this.baseUrl}/v1/documents/export`, {
      method: "POST",
      headers: {
        authorization: `Bearer ${this.apiKey}`,
        "content-type": "application/json",
        "idempotency-key": input.idempotencyKey
      },
      body: JSON.stringify({
        title: input.title,
        format: input.format,
        html: input.html
      })
    });

    if (!response.ok) {
      throw new Error(`SuperDocs export failed with status ${response.status}`);
    }

    return {
      data: new Uint8Array(await response.arrayBuffer()),
      contentType: response.headers.get("content-type") ?? "application/octet-stream",
      filename: `preview.${input.format}`
    };
  }
}
