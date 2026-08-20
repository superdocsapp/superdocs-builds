import { apiUrl, get, post } from "./client";
import type {
  ApproveTransmittalResponse,
  CreateTransmittalResponse,
  EditTransmittalResponse,
  ExportTransmittalResponse,
  TransmittalJobResponse,
} from "./types";

// ============================================================
// Transmittal CRUD
// ============================================================

export function createTransmittal(
  submittalNumber: string,
): Promise<CreateTransmittalResponse> {
  return post<CreateTransmittalResponse>(
    `/transmittals/${encodeURIComponent(submittalNumber)}`,
  );
}

/**
 * Request a SuperDocs edit.
 * The backend receives `message` as a query parameter.
 */
export function editTransmittal(
  transmittalId: string,
  message: string,
): Promise<EditTransmittalResponse> {
  const params = new URLSearchParams({ message });
  return post<EditTransmittalResponse>(
    `/transmittals/${transmittalId}/edit?${params.toString()}`,
  );
}

export function getTransmittalJob(
  transmittalId: string,
): Promise<TransmittalJobResponse> {
  return get<TransmittalJobResponse>(`/transmittals/${transmittalId}/job`);
}

/**
 * Approve or reject a SuperDocs proposed change.
 * Both `approved` and optional `change_id` are query parameters.
 */
export function approveTransmittalChange(
  transmittalId: string,
  approved: boolean,
  changeId?: string,
): Promise<ApproveTransmittalResponse> {
  const params = new URLSearchParams({ approved: String(approved) });
  if (changeId) params.set("change_id", changeId);
  return post<ApproveTransmittalResponse>(
    `/transmittals/${transmittalId}/approve?${params.toString()}`,
  );
}

export function exportTransmittal(
  transmittalId: string,
): Promise<ExportTransmittalResponse> {
  return post<ExportTransmittalResponse>(
    `/transmittals/${transmittalId}/export`,
  );
}

/**
 * Returns the direct browser URL for downloading the DOCX.
 * The browser navigates directly to the backend endpoint,
 * which streams the binary file.
 */
export function downloadTransmittalUrl(transmittalId: string): string {
  return apiUrl(`/transmittals/${transmittalId}/download`);
}
