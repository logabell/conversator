import { useEffect, useRef } from 'react';
import { MessageCircle, Bot, User } from 'lucide-react';
import { useEventStore } from '../../stores/eventStore';
import { ToolCallCard } from '../shared/ToolCallCard';

export function ConversationLogPanel() {
  const conversation = useEventStore((s) => s.conversation);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [conversation]);

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center gap-2 p-4 border-b border-white/10">
        <MessageCircle className="w-5 h-5 text-accent" />
        <h2 className="font-semibold">Conversation</h2>
        <span className="text-xs text-gray-400 ml-auto">{conversation.length} entries</span>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {conversation.length === 0 ? (
          <div className="text-center text-gray-500 py-8">
            No conversation yet. Start speaking to Conversator.
          </div>
        ) : (
          conversation.map((entry) => (
            <div key={entry.entry_id}>
              {entry.role === 'user' && (
                <div className="flex gap-3">
                  <div className="w-8 h-8 rounded-full bg-blue-500/20 flex items-center justify-center flex-shrink-0">
                    <User className="w-4 h-4 text-blue-400" />
                  </div>
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-sm font-medium text-blue-400">You</span>
                      <span className="text-xs text-gray-500">
                        {new Date(entry.timestamp).toLocaleTimeString()}
                      </span>
                    </div>
                    <p className="text-gray-200">{entry.content}</p>
                  </div>
                </div>
              )}

              {entry.role === 'assistant' && (
                <div className="flex gap-3">
                  <div className="w-8 h-8 rounded-full bg-accent/20 flex items-center justify-center flex-shrink-0">
                    <Bot className="w-4 h-4 text-accent" />
                  </div>
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-sm font-medium text-accent">Conversator</span>
                      <span className="text-xs text-gray-500">
                        {new Date(entry.timestamp).toLocaleTimeString()}
                      </span>
                    </div>
                    <p className="text-gray-200">{entry.content}</p>
                  </div>
                </div>
              )}

              {entry.role === 'tool_call' && (
                <div className="ml-11">
                  <ToolCallCard
                    toolName={entry.tool_name || 'unknown'}
                    args={entry.tool_args}
                    result={entry.tool_result}
                    durationMs={entry.duration_ms}
                    timestamp={entry.timestamp}
                  />
                </div>
              )}
            </div>
          ))
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
