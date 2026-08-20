import api from "./axios";

export async function uploadClaimEvidence({
  carrier,
  files,
  documentTypes,
}) {
  const formData = new FormData();

  formData.append("carrier", carrier);
  formData.append(
    "document_types",
    JSON.stringify(documentTypes)
  );

  files.forEach((file) => {
    formData.append("files", file);
  });

  const response = await api.post(
    "/freight-claims/upload",
    formData
  );

  return response.data;
}


export async function generateClaim({
  sessionId,
  carrier,
}) {
  const response = await api.post(
    "/freight-claims/generate",
    {
      session_id: sessionId,
      carrier,
    }
  );

  return response.data;
}


export async function buildClaimPacket({
  sessionId,
  carrier,
}) {
  const response = await api.post(
    "/freight-claims/packet",
    {
      session_id: sessionId,
      carrier,
    }
  );

  return response.data;
}


export async function generateChaser({
  sessionId,
  carrier,
  followUpDate,
}) {
  const response = await api.post(
    "/freight-claims/chaser",
    {
      session_id: sessionId,
      carrier,
      follow_up_date: followUpDate,
    }
  );

  return response.data;
}


export async function getClaimStatus(
  claimId
) {
  const response = await api.get(
    `/freight-claims/${claimId}/status`
  );

  return response.data;
}


export async function approveAllChanges({
  sessionId,
  jobId,
  changes,
}) {
  const response = await api.post(
    "/approval/all",
    {
      session_id: sessionId,
      job_id: jobId,
      changes,
    }
  );

  return response.data;
}


export async function exportFreightClaim({
  claimId,
  sessionId,
  format = "pdf",
}) {
  const response = await api.post(
    `/freight-claims/${claimId}/export`,
    {
      session_id: sessionId,
      format,
    },
    {
      responseType: "blob",
    }
  );

  return response;
}