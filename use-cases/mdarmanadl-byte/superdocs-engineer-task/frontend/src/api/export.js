import api from "./axios";

export const exportDocument = async (
  sessionId,
  documentId = "doc_primary",
  format = "pdf"
) => {
  const response = await api.post(
    "/export",
    {
      session_id: sessionId,
      document_id: documentId,
      format,
    },
    {
      responseType: "blob",
    }
  );

  return response.data;
};