interface ChatPanelProps {
  messages: { role: string; content: string }[];
  loading: boolean;
}

export default function ChatPanel({ messages, loading }: ChatPanelProps) {
  return (
    <div className="flex-1 overflow-y-auto py-4 space-y-4">
      {messages.map((msg, i) => (
        <div
          key={i}
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
          <div className="bg-surface border border-border px-4 py-3 rounded-lg">
            <span className="flex gap-1 items-center">
              <span className="w-1.5 h-1.5 bg-text-2 rounded-full animate-bounce [animation-delay:0ms]" />
              <span className="w-1.5 h-1.5 bg-text-2 rounded-full animate-bounce [animation-delay:150ms]" />
              <span className="w-1.5 h-1.5 bg-text-2 rounded-full animate-bounce [animation-delay:300ms]" />
            </span>
          </div>
        </div>
      )}
    </div>
  );
}