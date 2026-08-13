import type { WriterPort } from "./types";
import { initializeSigma } from "./api";

interface WriterClientApi {
  dispatch(event: string, payload: Record<string, unknown>): Promise<unknown>;
}

declare global {
  interface Window {
    WriterClient?: WriterClientApi;
  }
}

const client = (): WriterClientApi => {
  if (!window.WriterClient) {
    throw new Error("Writer client is unavailable. Open the extension in Zoho Writer.");
  }
  return window.WriterClient;
};

export class ZohoWriterAdapter implements WriterPort {
  initialize(): Promise<void> {
    return initializeSigma();
  }

  async getSelectedHtml(): Promise<string> {
    const selected = await client().dispatch("SelectedContent", { type: "html" });
    if (typeof selected !== "string") {
      throw new Error("Writer returned an unexpected selection response.");
    }
    return selected;
  }
}
