import { useEffect, useRef, useState } from "react";
import { chat, chatAsync } from "../api/chat";

import { getJob, getActiveJob } from "../api/jobs";
export default function Chat({
  sessionId,
  setJobId,
  setPendingChanges,
  openApproval,
  setResponse,
  setUpdatedDocumentHtml,
  setLastPrompt,
}) {
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);

  const [messages, setMessages] = useState([
    {
      id: 1,
      role: "assistant",
      content: "Hi! Tell me what you'd like to do with your document.",
    },
  ]);

  const bottomRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({
      behavior: "smooth",
    });
  }, [messages, loading]);

  // --------------------------------------------------
  // Poll async job until it reaches a final state
  // --------------------------------------------------

  const pollJob = async (jobId) => {
    while (true) {
      const job = await getJob(jobId);

      console.log("JOB STATUS:", job);

      // ----------------------------------------------
      // AI is waiting for human approval
      // ----------------------------------------------

      if (job.status === "awaiting_approval") {
        const changes = job.metadata?.pending_changes || [];

        setJobId(job.job_id);

        setPendingChanges(changes);

        // If there are pending changes, show modal
        if (changes.length > 0) {
          openApproval();
        }

        return;
      }

      // ----------------------------------------------
      // Job completed
      // ----------------------------------------------

      if (job.status === "completed") {
        const result = job.result;

        const resultText = result?.response || "Request completed.";

        setResponse(resultText);

        const updatedHtml = result?.document_changes?.updated_html;

        if (updatedHtml) {
          setUpdatedDocumentHtml(updatedHtml);
        }

        setMessages((prev) => [
          ...prev,
          {
            id: Date.now(),
            role: "assistant",
            content: resultText,
          },
        ]);

        return;
      }

      // ----------------------------------------------
      // Job failed
      // ----------------------------------------------

      if (job.status === "failed") {
        throw new Error(job.error || "Async job failed.");
      }

      // ----------------------------------------------
      // Job cancelled
      // ----------------------------------------------

      if (job.status === "cancelled") {
        throw new Error("The request was cancelled.");
      }

      // ----------------------------------------------
      // pending / in_progress
      // Poll again
      // ----------------------------------------------

      await new Promise((resolve) => setTimeout(resolve, 1500));
    }
  };

  // --------------------------------------------------
  // Send message
  // --------------------------------------------------

  const handleSend = async () => {
    const text = message.trim();

    if (!sessionId) {
      alert("Please upload a document first.");
      return;
    }

    if (!text || loading) {
      return;
    }

    setMessages((prev) => [
      ...prev,
      {
        id: Date.now(),
        role: "user",
        content: text,
      },
    ]);

    setMessage("");
    setLoading(true);
    setLastPrompt(text);

    try {
      const lower = text.toLowerCase();

      // ----------------------------------------------
      // Simple informational requests
      // ----------------------------------------------

      const isAnalyze =
        lower.includes("list") ||
        lower.includes("show") ||
        lower.includes("find") ||
        lower.includes("search") ||
        lower.includes("what") ||
        lower.includes("which") ||
        lower.includes("skill") ||
        lower.includes("summary") ||
        lower.includes("summarize") ||
        lower.includes("analyse") ||
        lower.includes("analyze");

      // =================================================
      // SIMPLE CHAT
      // =================================================

      if (isAnalyze) {
        console.log("CALLING SIMPLE CHAT");

        const data = await chat(sessionId, text, "approve_all");

        console.log("SIMPLE CHAT RESPONSE:", data);

        /*
         * Your backend returns:
         *
         * {
         *   superdocs_status: 200,
         *   superdocs_response: "{\"response\":\"...\"}"
         * }
         *
         * Therefore parse superdocs_response.
         */

        let parsed = null;

        if (data?.superdocs_response) {
          parsed = JSON.parse(data.superdocs_response);
        }

        const resultText =
          parsed?.response ||
          data?.response ||
          data?.result?.response ||
          "I've processed your request.";

        setResponse(resultText);

        const updatedHtml =
          parsed?.document_changes?.updated_html ||
          data?.document_changes?.updated_html ||
          data?.updated_html;

        if (updatedHtml) {
          setUpdatedDocumentHtml(updatedHtml);
        }

        setMessages((prev) => [
          ...prev,
          {
            id: Date.now() + 1,
            role: "assistant",
            content: resultText,
          },
        ]);

        return;
      }

      // =================================================
      // ASYNC CHAT
      // =================================================

      console.log("CALLING ASYNC CHAT");
      const activeJob = await getActiveJob(sessionId);

      if (activeJob?.job_id) {
        console.log("ACTIVE JOB FOUND:", activeJob);

        setJobId(activeJob.job_id);

        await pollJob(activeJob.job_id);

        return;
      }
      const data = await chatAsync(sessionId, text, "ask_every_time");

      console.log("ASYNC CHAT RESPONSE:", data);

      /*
       * Async response should initially look like:
       *
       * {
       *   job_id: "...",
       *   session_id: "...",
       *   status: "pending",
       *   message: "Chat request queued..."
       * }
       */

      if (!data?.job_id) {
        throw new Error("Async chat did not return a job_id.");
      }

      // Store the active job
      setJobId(data.job_id);

      // Poll this SAME job.
      // Do NOT call chatAsync again.
      await pollJob(data.job_id);
    } catch (error) {
      console.error("Chat request failed:", error);

      console.error("Status:", error?.response?.status);

      console.error("Backend:", error?.response?.data);

      const errorMessage =
        error?.response?.data?.detail ||
        error?.message ||
        "Something went wrong. Please try again.";

      setMessages((prev) => [
        ...prev,
        {
          id: Date.now() + 2,
          role: "assistant",
          content: errorMessage,
        },
      ]);
    } finally {
      setLoading(false);
    }
  };

  // --------------------------------------------------
  // Enter / Shift + Enter
  // --------------------------------------------------

  const handleKeyDown = (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      handleSend();
    }
  };

  const suggestions = [
    "edit the name to aaryan",
    "Summarize the document",
    "Make it more professional",
    "Improve the introduction",
  ];

  return (
    <div className="chat-shell">
      {/* Header */}

      <div className="chat-header">
        <div className="chat-avatar">✦</div>

        <div>
          <h2>AI Editor</h2>

          <p>Ask questions or edit your document</p>
        </div>
      </div>

      {/* Messages */}

      <div className="chat-messages">
        {messages.map((item) => (
          <div
            key={item.id}
            className={`message-row ${
              item.role === "user" ? "message-user" : "message-ai"
            }`}
          >
            <div
              className={`message-bubble ${
                item.role === "user" ? "bubble-user" : "bubble-ai"
              }`}
            >
              {item.content}
            </div>
          </div>
        ))}

        {loading && (
          <div className="message-row message-ai">
            <div className="bubble-ai typing">
              <span />
              <span />
              <span />
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Composer */}

      <div className="chat-composer">
        <div className="suggestions">
          {suggestions.map((item) => (
            <button
              key={item}
              onClick={() => setMessage(item)}
              disabled={loading}
            >
              {item}
            </button>
          ))}
        </div>

        <div className="composer-box">
          <textarea
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask SuperDocs AI..."
            rows={1}
            disabled={!sessionId || loading}
          />

          <button
            className="send-button"
            onClick={handleSend}
            disabled={!sessionId || !message.trim() || loading}
          >
            ↑
          </button>
        </div>

        <div className="composer-hint">
          Enter to send · Shift + Enter for new line
        </div>
      </div>
    </div>
  );
}
