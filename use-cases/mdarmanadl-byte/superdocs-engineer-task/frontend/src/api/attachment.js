import api from "./axios";

export const uploadAttachment = async (
  sessionId,
  file
) => {
  const formData = new FormData();

  formData.append("session_id", sessionId);
  formData.append("file", file);

  const response = await api.post(
    "/attachments/upload",
    formData,
    {
      headers: {
        "Content-Type": "multipart/form-data",
      },
    }
  );

  return response.data;
};

export const getAttachmentStatus = async (
  sessionId
) => {
  const response = await api.get(
    `/documents/status/${sessionId}`
  );

  return response.data;
};