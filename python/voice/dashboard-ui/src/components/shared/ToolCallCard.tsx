import { useState } from 'react';
import { ChevronDown, ChevronRight, Wrench, Clock } from 'lucide-react';

interface ToolCallCardProps {
  toolName: string;
  args?: Record<string, unknown>;
  result?: Record<string, unknown>;
  durationMs?: number;
  timestamp?: string;
}

export function ToolCallCard({
  toolName,
  args,
  result,
  durationMs,
  timestamp
}: ToolCallCardProps) {
  const [expanded, setExpanded] = useState(false);

  const hasError = result && 'error' in result;

  return (
    <div className={`rounded-lg border ${hasError ? 'border-red-500/30 bg-red-500/5' : 'border-accent-muted/30 bg-surface-secondary'}`}>
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between p-3 text-left hover:bg-white/5 transition-colors"
      >
        <div className="flex items-center gap-2">
          <Wrench className="w-4 h-4 text-accent" />
          <span className="font-mono text-sm text-gray-200">{toolName}</span>
        </div>
        <div className="flex items-center gap-3 text-xs text-gray-400">
          {durationMs !== undefined && (
            <span className="flex items-center gap-1">
              <Clock className="w-3 h-3" />
              {durationMs}ms
            </span>
          )}
          {timestamp && (
            <span>{new Date(timestamp).toLocaleTimeString()}</span>
          )}
          {expanded ? (
            <ChevronDown className="w-4 h-4" />
          ) : (
            <ChevronRight className="w-4 h-4" />
          )}
        </div>
      </button>

      {expanded && (
        <div className="border-t border-white/10 p-3 space-y-3">
          {args && Object.keys(args).length > 0 && (
            <div>
              <div className="text-xs text-gray-400 mb-1">Arguments</div>
              <pre className="text-xs bg-black/30 rounded p-2 overflow-x-auto text-gray-300">
                {JSON.stringify(args, null, 2)}
              </pre>
            </div>
          )}
          {result && (
            <div>
              <div className={`text-xs mb-1 ${hasError ? 'text-red-400' : 'text-gray-400'}`}>
                {hasError ? 'Error' : 'Result'}
              </div>
              <pre className={`text-xs rounded p-2 overflow-x-auto ${hasError ? 'bg-red-500/10 text-red-300' : 'bg-black/30 text-gray-300'}`}>
                {JSON.stringify(result, null, 2)}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
