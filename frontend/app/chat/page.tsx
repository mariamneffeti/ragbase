"use client";

import { useState, useRef, useEffect } from "react";
import { useSupabase } from "@/components/providers";
import { toast } from "sonner";

interface Message {
  role: "user" | "assistant";
  content: string;
}

export default function ChatPage() {
  const { user } = useSupabase();
  const tenantId = user?.app_metadata?.tenant_id || "default-tenant";
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, loading]);

  const sendMessage = async () => {
    if (!input.trim() || loading) return;

    const userMsg: Message = { role: "user", content: input };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setLoading(true);

    try {
      const res = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL}/chat/query`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-Tenant-ID": tenantId,
          },
          body: JSON.stringify({ message: input }),
        }
      );

      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.detail || "Chat request failed");
      }

      const data = await res.json();
      const fullAnswer = data.answer;

      setMessages((prev) => [...prev, { role: "assistant", content: "" }]);
      const words = fullAnswer.split(" ");
      for (let i = 0; i < words.length; i++) {
        await new Promise((resolve) => setTimeout(resolve, 40));
        setMessages((prev) => {
          const updated = [...prev];
          const lastIdx = updated.length - 1;
          updated[lastIdx] = {
            ...updated[lastIdx],
            content: updated[lastIdx].content + (i ? " " : "") + words[i],
          };
          return updated;
        });
      }
    } catch (err: any) {
      toast.error(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="max-w-2xl mx-auto flex flex-col h-[calc(100vh-4rem)]">
      {/* Header */}
      <div className="pb-4 mb-2 border-b border-border">
        <h2 className="text-xl font-semibold text-text tracking-tight">AI Chat</h2>
        <p className="text-sm text-text-2 mt-0.5">Ask questions about your documents.</p>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto py-4 space-y-4">
        {messages.length === 0 && (
          <div className="flex items-center justify-center h-full">
            <p className="text-sm text-text-2">No messages yet. Ask something.</p>
          </div>
        )}

        {messages.map((msg, idx) => (
          <div
            key={idx}
            className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
          >
            <div
              className={`max-w-[78%] px-4 py-2.5 rounded-lg text-sm leading-relaxed ${
                msg.role === "user"
                  ? "bg-accent text-white"
                  : "bg-surface border border-border text-text"
              }`}
            >
              {msg.content}
            </div>
          </div>
        ))}

        {loading && (
          <div className="flex justify-start">
            <div className="bg-surface border border-border px-4 py-2.5 rounded-lg">
              <span className="flex gap-1 items-center">
                <span className="w-1.5 h-1.5 bg-text-2 rounded-full animate-bounce [animation-delay:0ms]" />
                <span className="w-1.5 h-1.5 bg-text-2 rounded-full animate-bounce [animation-delay:150ms]" />
                <span className="w-1.5 h-1.5 bg-text-2 rounded-full animate-bounce [animation-delay:300ms]" />
              </span>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="pt-3 border-t border-border">
        <div className="flex gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && sendMessage()}
            placeholder="Ask about your documents…"
            className="flex-1 bg-surface border border-border rounded-md px-3 py-2 text-sm text-text placeholder:text-text-2 focus:outline-none focus:ring-1 focus:ring-accent transition disabled:opacity-50"
            disabled={loading}
          />
          <button
            onClick={sendMessage}
            disabled={loading || !input.trim()}
            className="px-4 py-2 bg-accent text-white text-sm font-medium rounded-md hover:bg-accent-2 disabled:opacity-40 transition-colors duration-150"
          >
            Send
          </button>
        </div>
      </div>
    </div>
  );
}