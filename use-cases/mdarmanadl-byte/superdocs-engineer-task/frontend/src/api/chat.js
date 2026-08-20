import api from "./axios";

export const chat = async (
  sessionId,
  message,
  approvalMode = "approve_all"
) => {
  const response = await api.post("/chat", {
    session_id: sessionId,
    message,
    approval_mode: approvalMode,

  });
  console.log("Reposne.Data:",response.data)
  return response.data;
};

export const chatAsync = async (
  sessionId,
  message,
  approvalMode = "ask_every_time"
) => {
  const response = await api.post("/chat/async", {
    session_id: sessionId,
    message,
    approval_mode: approvalMode,
  });

  return response.data;
};