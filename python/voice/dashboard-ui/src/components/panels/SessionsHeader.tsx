import { Focus, Radio, Layers, Cpu } from 'lucide-react';
import { useEventStore } from '../../stores/eventStore';

export function SessionsHeader() {
  const sessions = useEventStore((s) => s.sessions);
  const registeredSources = useEventStore((s) => s.registeredSources);
  const autoSelectNewSessions = useEventStore((s) => s.autoSelectNewSessions);
  const setAutoSelectNewSessions = useEventStore((s) => s.setAutoSelectNewSessions);

  // Count active sessions
  const activeSessions = sessions.filter((s) => s.status === 'active').length;

  // Count by source
  const conversatorCount = sessions.filter((s) => s.source === 'conversator').length;
  const builderCount = sessions.filter((s) => s.source === 'builder').length;

  return (
    <div className="flex items-center gap-4 px-4 py-3 bg-surface-secondary border-b border-white/10">
      {/* Session Counts */}
      <div className="flex items-center gap-4 text-xs">
        {/* Active indicator */}
        {activeSessions > 0 && (
          <span className="flex items-center gap-1.5 text-green-400">
            <Radio className="w-3.5 h-3.5 animate-pulse" />
            <span>{activeSessions} active</span>
          </span>
        )}

        {/* Source breakdown */}
        {conversatorCount > 0 && (
          <span className="flex items-center gap-1.5 text-purple-400">
            <Layers className="w-3.5 h-3.5" />
            <span>{conversatorCount} conversator</span>
          </span>
        )}
        {builderCount > 0 && (
          <span className="flex items-center gap-1.5 text-blue-400">
            <Cpu className="w-3.5 h-3.5" />
            <span>{builderCount} builder</span>
          </span>
        )}

        {/* Connected sources */}
        {registeredSources.length > 0 && (
          <span className="text-gray-500">
            {registeredSources.filter((s) => s.status === 'connected').length}/{registeredSources.length} sources
          </span>
        )}
      </div>

      {/* Spacer */}
      <div className="flex-1" />

      {/* Auto-select toggle */}
      <label className="flex items-center gap-2 text-sm cursor-pointer group">
        <div className="relative">
          <input
            type="checkbox"
            checked={autoSelectNewSessions}
            onChange={(e) => setAutoSelectNewSessions(e.target.checked)}
            className="sr-only peer"
          />
          <div className="w-9 h-5 bg-gray-700 rounded-full peer peer-checked:bg-accent/50 transition-colors" />
          <div className="absolute left-0.5 top-0.5 w-4 h-4 bg-gray-400 rounded-full peer-checked:translate-x-4 peer-checked:bg-accent transition-all" />
        </div>
        <span className="flex items-center gap-1.5 text-gray-400 group-hover:text-gray-300 transition-colors">
          <Focus className="w-4 h-4" />
          <span>Auto-focus new</span>
        </span>
      </label>
    </div>
  );
}
