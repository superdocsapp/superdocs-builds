"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { MessageSquare, Search, Send, X, Bot, ArrowRight } from "lucide-react";
import Link from "next/link";
import { Button } from "@/components/ui/Button";

interface Citation {
  source_type: string;
  identifier: string;
  section?: string | null;
  excerpt: string;
}

interface SearchResultItem {
  entity_type: string;
  entity_id: string;
  title: string;
  subtitle: string;
  matched_text: string;
  url: string;
}

interface ChatMessage {
  role: "user" | "assistant";
  text: string;
  citations?: Citation[];
  followups?: string[];
}

export function ProjectAssistantModal({
  open,
  onClose,
  projectId = "BROD-2026",
}: {
  open: boolean;
  onClose: () => void;
  projectId?: string;
}) {
  const [activeTab, setActiveTab] = useState<"chat" | "search">("chat");
  const [input, setInput] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      role: "assistant",
      text: "Hello! I am your DocTask Project Assistant. Ask me anything about project specifications, submittal register items, comparison findings, deviations, or overdue submissions.",
      followups: [
        "Which submittals are overdue?",
        "Show all deviations across submittals",
        "What specification requirements apply to Section 09 65 00?",
      ],
    },
  ]);

  const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

  // Chat Mutation
  const chatMutation = useMutation({
    mutationFn: async (query: string) => {
      const res = await fetch(`${apiUrl}/projects/${projectId}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query }),
      });
      if (!res.ok) throw new Error("Failed to get answer");
      return res.json();
    },
    onSuccess: (data) => {
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          text: data.answer,
          citations: data.citations,
          followups: data.suggested_followups,
        },
      ]);
    },
    onError: () => {
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          text: "Sorry, I encountered an error connecting to the backend assistant service.",
        },
      ]);
    },
  });

  // Search Mutation
  const searchMutation = useMutation({
    mutationFn: async (q: string) => {
      const res = await fetch(`${apiUrl}/projects/${projectId}/search?q=${encodeURIComponent(q)}`);
      if (!res.ok) throw new Error("Search failed");
      return res.json();
    },
  });

  const handleSend = (textToSend?: string) => {
    const q = textToSend || input;
    if (!q.trim() || chatMutation.isPending) return;

    setMessages((prev) => [...prev, { role: "user", text: q }]);
    setInput("");
    chatMutation.mutate(q);
  };

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (!searchQuery.trim()) return;
    searchMutation.mutate(searchQuery);
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 backdrop-blur-sm p-4">
      <div
        className="w-full max-w-2xl rounded-xl border border-slate-200 bg-white shadow-2xl overflow-hidden flex flex-col h-[600px] animate-in fade-in zoom-in-95 duration-150"
        role="dialog"
        aria-modal="true"
        aria-label="DocTask Project Assistant"
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-slate-100 bg-slate-50 px-5 py-3.5">
          <div className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-blue-600 text-white">
              <Bot className="h-4 w-4" />
            </div>
            <div>
              <h2 className="text-sm font-semibold text-slate-900">DocTask Grounded Assistant</h2>
              <p className="text-[11px] text-slate-500 font-mono">{projectId} · Evidence-backed Q&A</p>
            </div>
          </div>

          {/* Tab toggles */}
          <div className="flex items-center gap-1 rounded-lg border border-slate-200 bg-white p-1">
            <button
              onClick={() => setActiveTab("chat")}
              className={`flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
                activeTab === "chat" ? "bg-blue-50 text-blue-700" : "text-slate-600 hover:text-slate-900"
              }`}
            >
              <MessageSquare className="h-3.5 w-3.5" /> Q&A Chat
            </button>
            <button
              onClick={() => setActiveTab("search")}
              className={`flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
                activeTab === "search" ? "bg-blue-50 text-blue-700" : "text-slate-600 hover:text-slate-900"
              }`}
            >
              <Search className="h-3.5 w-3.5" /> Global Search
            </button>
          </div>

          <button
            onClick={onClose}
            className="rounded p-1 text-slate-400 hover:bg-slate-200 hover:text-slate-700"
            aria-label="Close assistant"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Content Body */}
        {activeTab === "chat" ? (
          <div className="flex-1 overflow-y-auto p-4 space-y-4">
            {messages.map((msg, idx) => (
              <div
                key={idx}
                className={`flex gap-3 ${msg.role === "user" ? "justify-end" : "justify-start"}`}
              >
                {msg.role === "assistant" && (
                  <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-blue-100 text-blue-700 text-xs font-bold mt-0.5">
                    DT
                  </div>
                )}
                <div
                  className={`max-w-[85%] rounded-lg px-4 py-3 text-sm leading-relaxed ${
                    msg.role === "user"
                      ? "bg-blue-600 text-white font-medium"
                      : "bg-slate-50 border border-slate-200 text-slate-800"
                  }`}
                >
                  <p className="whitespace-pre-line">{msg.text}</p>

                  {/* Citations */}
                  {msg.citations && msg.citations.length > 0 && (
                    <div className="mt-3 pt-2.5 border-t border-slate-200/80 space-y-1.5">
                      <p className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">
                        Grounded Sources & Citations
                      </p>
                      {msg.citations.map((c, cIdx) => (
                        <div
                          key={cIdx}
                          className="rounded bg-white border border-slate-200 p-2 text-xs text-slate-600 font-mono"
                        >
                          <span className="font-bold text-blue-700">[{c.source_type}]</span> {c.identifier}
                          {c.section ? ` · ${c.section}` : ""}:
                          <p className="font-sans italic text-slate-700 mt-0.5">&ldquo;{c.excerpt}&rdquo;</p>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Suggested Followups */}
                  {msg.followups && msg.followups.length > 0 && (
                    <div className="mt-3 pt-2 border-t border-slate-200/60 flex flex-wrap gap-1.5">
                      {msg.followups.map((f, fIdx) => (
                        <button
                          key={fIdx}
                          onClick={() => handleSend(f)}
                          className="rounded-full border border-blue-200 bg-blue-50/80 px-2.5 py-1 text-[11px] text-blue-700 hover:bg-blue-100 transition-colors text-left"
                        >
                          {f} →
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ))}
            {chatMutation.isPending && (
              <div className="flex gap-2 items-center text-xs text-slate-400 italic">
                <Bot className="h-4 w-4 animate-spin text-blue-600" />
                Searching project records and formulating grounded response…
              </div>
            )}
          </div>
        ) : (
          <div className="flex-1 overflow-y-auto p-4 space-y-4">
            <form onSubmit={handleSearch} className="flex gap-2">
              <div className="relative flex-1">
                <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                <input
                  type="search"
                  placeholder="Search submittal number, title, specification section, or finding…"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="h-10 w-full rounded-lg border border-slate-300 pl-9 pr-3 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
              <Button type="submit" loading={searchMutation.isPending}>
                Search
              </Button>
            </form>

            {searchMutation.data && (
              <div className="space-y-2">
                <p className="text-xs text-slate-500 font-medium">
                  {searchMutation.data.total_count} result(s) found for &ldquo;{searchMutation.data.query}&rdquo;
                </p>
                <div className="divide-y divide-slate-100 rounded-lg border border-slate-200 bg-white">
                  {searchMutation.data.results.length === 0 ? (
                    <p className="p-8 text-center text-sm text-slate-400">No matching records found.</p>
                  ) : (
                    searchMutation.data.results.map((item: SearchResultItem, idx: number) => (
                      <Link
                        key={idx}
                        href={item.url}
                        onClick={onClose}
                        className="flex items-center justify-between p-3.5 hover:bg-slate-50 transition-colors"
                      >
                        <div>
                          <span className="text-[10px] font-bold text-blue-600 uppercase tracking-wide">
                            {item.entity_type}
                          </span>
                          <p className="text-sm font-semibold text-slate-800">{item.title}</p>
                          <p className="text-xs text-slate-500">{item.subtitle}</p>
                        </div>
                        <ArrowRight className="h-4 w-4 text-slate-300" />
                      </Link>
                    ))
                  )}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Input Footer for Chat */}
        {activeTab === "chat" && (
          <div className="border-t border-slate-200 bg-white p-3">
            <form
              onSubmit={(e) => {
                e.preventDefault();
                handleSend();
              }}
              className="flex gap-2"
            >
              <input
                type="text"
                placeholder="Ask about deviations, requirements, overdue dates, or evidence…"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                disabled={chatMutation.isPending}
                className="flex-1 h-9 rounded-md border border-slate-300 px-3 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50"
              />
              <Button type="submit" size="sm" loading={chatMutation.isPending} disabled={!input.trim()}>
                <Send className="h-3.5 w-3.5 mr-1" /> Ask
              </Button>
            </form>
          </div>
        )}
      </div>
    </div>
  );
}
