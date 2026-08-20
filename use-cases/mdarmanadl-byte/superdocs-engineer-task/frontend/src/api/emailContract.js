import api from "./axios";


export async function createEmailContract({
  negotiationThread,
  contractType,
}) {
  const response = await api.post(
    "/email-contracts/create",
    {
      negotiation_thread: negotiationThread,
      contract_type: contractType,
    }
  );

  return response.data;
}


export async function generateEmailContract({
  contractId,
  negotiationThread,
  contractType,
}) {
  const response = await api.post(
    "/email-contracts/generate",
    {
      contract_id: contractId,
      negotiation_thread: negotiationThread,
      contract_type: contractType,
    }
  );

  return response.data;
}


export async function getEmailContractStatus(
  contractId
) {
  const response = await api.get(
    `/email-contracts/${contractId}/status`
  );

  return response.data;
}


export async function getEmailContract(
  contractId
) {
  const response = await api.get(
    `/email-contracts/${contractId}`
  );

  return response.data;
}


export async function exportEmailContract(
  contractId
) {
  const response = await api.post(
    `/email-contracts/${contractId}/export`,
    {},
    {
      responseType: "blob",
    }
  );

  return response;
}