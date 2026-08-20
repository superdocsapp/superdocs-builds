import api from "./axios";

export const getJob = async (jobId) => {
  const response = await api.get(`/chat/job/${jobId}`);
  return response.data;
};
export const getActiveJob = async (sessionId) => {
  const response = await api.get("/chat/active", {
    params: {
      session_id: sessionId,
    },
  });

  return response.data;
};