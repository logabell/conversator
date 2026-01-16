import { useEffect, useRef } from 'react';
import { Mic, Bot, User, Wrench, Trash2 } from 'lucide-react';
import { useEventStore } from '../../stores/eventStore';
import type { GeminiTranscriptEntry } from '../../api/client';

export function GeminiTranscriptPanel() {
  const transcript = useEventStore((s) => s.geminiTranscript);
  const clearGeminiTranscript = useEventStore((s) => s.clearGeminiTranscript);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [transcript]);

  const formatTime = (timestamp: string) => {
    return new Date(timestamp).toLocaleTimeString([], {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit'
    });
  };

  const renderEntry = (entry: GeminiTranscriptEntry) => {
    const isUser = entry.role === 'user';
    const isToolCall = entry.is_tool_call || entry.role === 'tool_call';

    const Icon = isUser ? User : isToolCall ? Wrench : Bot;
    const colorClass = isUser
      ? 'text-blue-400 bg-blue-500/20'
      : isToolCall
      ? 'text-purple-400 bg-purple-500/20'
      : 'text-accent bg-accent/20';

    const label = isUser
      ? 'You (voice)'
      : isToolCall
      ? entry.tool_name || 'Tool Call'
      : 'Conversator';

    return (
      <div key={entry.id} className="flex gap-3 mb-3">
        {/* Avatar */}
        <div
          className={`w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 ${colorClass}`}
        >
          <Icon className="w-4 h-4" />
        </div>

        {/* Content */}
        <div className="flex-1 min-w-0">
          {/* Header */}
          <div className="flex items-center gap-2 mb-1">
            <span className={`text-sm font-medium ${colorClass.split(' ')[0]}`}>
              {label}
            </span>
            <span className="text-xs text-gray-500">
              {formatTime(entry.timestamp)}
            </span>
          </div>

          {/* Message */}
          <p className="text-gray-200 text-sm whitespace-pre-wrap break-words">
            {entry.content}
          </p>

          {/* Tool Args (if tool call) */}
          {isToolCall && entry.tool_args && (
            <div className="mt-2 bg-purple-500/5 border border-purple-500/10 rounded p-2">
              <pre className="text-xs text-gray-400 overflow-x-auto">
                {JSON.stringify(entry.tool_args, null, 2)}
              </pre>
            </div>
          )}
        </div>
      </div>
    );
  };

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="flex items-center gap-2 p-4 border-b border-white/10">
        <Mic className="w-5 h-5 text-accent" />
        <h2 className="font-semibold">Voice Transcript</h2>
        <span className="ml-auto text-xs text-gray-400">
          {transcript.length} entries
        </span>
        {transcript.length > 0 && (
          <button
            onClick={clearGeminiTranscript}
            className="p-1.5 rounded hover:bg-white/10 text-gray-400 hover:text-red-400 transition-colors"
            title="Clear transcript"
          >
            <Trash2 className="w-4 h-4" />
          </button>
        )}
      </div>

      {/* Transcript */}
      <div className="flex-1 overflow-y-auto p-4">
        {transcript.length === 0 ? (
          <div className="text-center text-gray-500 py-8">
            <Mic className="w-10 h-10 mx-auto mb-3 opacity-30" />
            <p className="text-sm">Voice transcript will appear here</p>
            <p className="text-xs mt-1 text-gray-600">
              Speak to Conversator to see the conversation
            </p>
          </div>
        ) : (
          <>
            {transcript.map(renderEntry)}
            <div ref={bottomRef} />
          </>
        )}
      </div>
    </div>
  );
}
