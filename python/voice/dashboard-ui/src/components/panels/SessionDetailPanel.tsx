import { useEffect, useRef } from 'react';
import { MessageSquare, Bot, User, Wrench, RefreshCw, Layers, Cpu, Radio } from 'lucide-react';
import { useEventStore } from '../../stores/eventStore';
import { api, OpenCodeMessage, OpenCodeMessagePart } from '../../api/client';
import { ThinkingIndicator } from '../sessions/ThinkingIndicator';

export function SessionDetailPanel() {
  const selectedSessionId = useEventStore((s) => s.selectedSessionId);
  const sessionMessages = useEventStore((s) => s.sessionMessages);
  const streamingContent = useEventStore((s) => s.streamingContent);
  const setSessionMessages = useEventStore((s) => s.setSessionMessages);
  const sessions = useEventStore((s) => s.sessions);
  const bottomRef = useRef<HTMLDivElement>(null);

  const selectedSession = sessions.find((s) => s.session_id === selectedSessionId);
  const messages = selectedSessionId ? sessionMessages[selectedSessionId] || [] : [];

  useEffect(() => {
    if (selectedSessionId) {
      api.getSessionMessages(selectedSessionId)
        .then((res) => setSessionMessages(selectedSessionId, res.messages))
        .catch(console.error);
    }
  }, [selectedSessionId, setSessionMessages]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, streamingContent]);

  const handleRefresh = async () => {
    if (!selectedSessionId) return;
    try {
      const res = await api.refreshSession(selectedSessionId);
      setSessionMessages(selectedSessionId, res.messages);
    } catch (e) {
      console.error('Failed to refresh session:', e);
    }
  };

  const extractTextContent = (parts: OpenCodeMessagePart[]): string => {
    return parts
      .filter((p) => p.type === 'text' && p.text)
      .map((p) => p.text)
      .join('\n');
  };

  const getToolCalls = (parts: OpenCodeMessagePart[]) => {
    return parts.filter(
      (p) => p.type === 'tool-invocation' || p.type === 'tool-result'
    );
  };

  const formatTime = (timestamp: string) => {
    return new Date(timestamp).toLocaleTimeString([], {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit'
    });
  };

  if (!selectedSessionId) {
    return (
      <div className="h-full flex items-center justify-center text-gray-500">
        <div className="text-center">
          <MessageSquare className="w-10 h-10 mx-auto mb-3 opacity-30" />
          <p className="text-sm">Select a session to view messages</p>
        </div>
      </div>
    );
  }

  const renderMessage = (msg: OpenCodeMessage) => {
    const isUser = msg.role === 'user';
    const textContent = extractTextContent(msg.parts);
    const toolCalls = getToolCalls(msg.parts);

    // Check for streaming content for this message
    const streamKey = `${msg.session_id}:${msg.message_id}`;
    const streaming = streamingContent[streamKey];

    return (
      <div key={msg.message_id} className="mb-4">
        <div className="flex gap-3">
          {/* Avatar */}
          <div
            className={`w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 ${
              isUser ? 'bg-blue-500/20' : 'bg-accent/20'
            }`}
          >
            {isUser ? (
              <User className="w-4 h-4 text-blue-400" />
            ) : (
              <Bot className="w-4 h-4 text-accent" />
            )}
          </div>

          {/* Message Content */}
          <div className="flex-1 min-w-0">
            {/* Header */}
            <div className="flex items-center gap-2 mb-1">
              <span
                className={`text-sm font-medium ${
                  isUser ? 'text-blue-400' : 'text-accent'
                }`}
              >
                {isUser ? 'User' : 'Assistant'}
              </span>
              <span className="text-xs text-gray-500">
                {formatTime(msg.created_at)}
              </span>
              {!msg.is_complete && (
                <span className="text-xs text-yellow-400 animate-pulse">
                  Streaming...
                </span>
              )}
            </div>

            {/* Text Content */}
            {(textContent || streaming) && (
              <div className="text-gray-200 whitespace-pre-wrap break-words text-sm font-mono">
                {textContent}
                {streaming && (
                  <>
                    <span className="text-yellow-400">{streaming}</span>
                    <span className="inline-block w-2 h-4 bg-accent terminal-cursor ml-0.5 align-middle" />
                  </>
                )}
              </div>
            )}

            {/* Tool Calls */}
            {toolCalls.length > 0 && (
              <div className="mt-2 space-y-2">
                {toolCalls.map((tool, idx) => (
                  <div
                    key={idx}
                    className="bg-purple-500/10 border border-purple-500/20 rounded-lg p-3"
                  >
                    <div className="flex items-center gap-2 text-purple-400 text-sm">
                      <Wrench className="w-4 h-4" />
                      <span className="font-medium">{tool.tool_name || 'Tool Call'}</span>
                    </div>
                    {tool.tool_args && (
                      <pre className="mt-2 text-xs text-gray-400 overflow-x-auto">
                        {JSON.stringify(tool.tool_args, null, 2)}
                      </pre>
                    )}
                    {tool.tool_result !== undefined && tool.tool_result !== null && (
                      <div className="mt-2 pt-2 border-t border-purple-500/20">
                        <span className="text-xs text-gray-500">Result:</span>
                        <pre className="mt-1 text-xs text-gray-400 overflow-x-auto max-h-32">
                          {JSON.stringify(tool.tool_result, null, 2)}
                        </pre>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    );
  };

  // Check if any message is currently streaming
  const isStreaming = selectedSessionId
    ? Object.keys(streamingContent).some((k) => k.startsWith(selectedSessionId))
    : false;

  // Get source badge info
  const getSourceBadge = () => {
    if (!selectedSession) return null;

    if (selectedSession.source === 'conversator') {
      return {
        icon: <Layers className="w-3 h-3" />,
        label: selectedSession.instance || 'Layer 2',
        className: 'bg-purple-500/20 text-purple-400',
      };
    } else if (selectedSession.source === 'builder') {
      return {
        icon: <Cpu className="w-3 h-3" />,
        label: selectedSession.instance || 'Layer 3',
        className: 'bg-blue-500/20 text-blue-400',
      };
    }
    return {
      icon: null,
      label: 'External',
      className: 'bg-gray-500/20 text-gray-400',
    };
  };

  const sourceBadge = getSourceBadge();

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="flex items-center gap-2 p-4 border-b border-white/10">
        <MessageSquare className="w-5 h-5 text-accent" />
        <h2 className="font-semibold">Session Detail</h2>

        {/* Source Badge */}
        {sourceBadge && (
          <span className={`flex items-center gap-1.5 px-2 py-0.5 text-xs rounded ${sourceBadge.className}`}>
            {sourceBadge.icon}
            {sourceBadge.label}
          </span>
        )}

        {/* Streaming Indicator */}
        {isStreaming && (
          <span className="flex items-center gap-1.5 text-xs text-yellow-400">
            <Radio className="w-3 h-3 animate-pulse" />
            <span>Streaming</span>
          </span>
        )}

        <span className="ml-auto text-xs text-gray-400 font-mono">
          {selectedSessionId.slice(0, 12)}...
        </span>
        <button
          onClick={handleRefresh}
          className="p-1.5 rounded hover:bg-white/10 text-gray-400 hover:text-white transition-colors"
          title="Refresh messages"
        >
          <RefreshCw className="w-4 h-4" />
        </button>
      </div>

      {/* Session Info */}
      {selectedSession && (
        <div className="px-4 py-2 bg-surface-primary/50 border-b border-white/5 text-xs">
          <div className="flex items-center gap-4 text-gray-400">
            <span>
              Agent: <span className="text-white font-mono">{selectedSession.agent_name}</span>
            </span>
            <span>
              Status:{' '}
              <span
                className={
                  selectedSession.status === 'active'
                    ? 'text-yellow-400'
                    : selectedSession.status === 'completed'
                    ? 'text-green-400'
                    : 'text-red-400'
                }
              >
                {selectedSession.status}
              </span>
            </span>
            <span>Messages: {messages.length}</span>
          </div>
        </div>
      )}

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4">
        {messages.length === 0 ? (
          <div className="text-center text-gray-500 py-8">
            <MessageSquare className="w-8 h-8 mx-auto mb-2 opacity-50" />
            <p className="text-sm">No messages yet</p>
            {selectedSession?.status === 'active' && (
              <ThinkingIndicator className="justify-center mt-4" />
            )}
          </div>
        ) : (
          <>
            {messages.map(renderMessage)}
            {/* Show thinking indicator when session is active and waiting for response */}
            {selectedSession?.status === 'active' &&
             messages.length > 0 &&
             messages[messages.length - 1].role === 'user' &&
             !isStreaming && (
              <div className="mt-4 pl-11">
                <ThinkingIndicator />
              </div>
            )}
            <div ref={bottomRef} />
          </>
        )}
      </div>
    </div>
  );
}
