import api from "./axios";

export const approveChange = async (
  sessionId,
  jobId,
  changeId
) => {
  const response = await api.post(
    `/approval`,
    {
      session_id: sessionId,
      job_id: jobId,
      change_id: changeId,
      approved: true,
    }
  );

  return response.data;
};

export const rejectChange = async (
  sessionId,
  jobId,
  changeId,
  feedback = ""
) => {
  const response = await api.post(
    `/approval`,
    {
      session_id: sessionId,
      job_id: jobId,
      change_id: changeId,
      approved: false,
      feedback: feedback || null,
    }
  );

  return response.data;
};
export const approveAll = async (
  sessionId,
  jobId,
  changes,
) => {
  const response = await api.post("/approval/all", {
    session_id: sessionId,
    job_id: jobId,

    changes: changes.map((change) => ({
      change_id: change.change_id,
      approved: true,
    })),
  });

  return response.data;
};