import { Monitor, Terminal } from 'lucide-react';
import { useEventStore } from '../../stores/eventStore';

export function TabNav() {
  const activeTab = useEventStore((s) => s.activeTab);
  const setActiveTab = useEventStore((s) => s.setActiveTab);
  const sessions = useEventStore((s) => s.sessions);

  const activeSessions = sessions.filter((s) => s.status === 'active').length;

  return (
    <div className="flex items-center gap-1 bg-surface-secondary rounded-lg p-1">
      <button
        onClick={() => setActiveTab('monitoring')}
        className={`flex items-center gap-2 px-4 py-2 rounded-md text-sm font-medium transition-colors ${
          activeTab === 'monitoring'
            ? 'bg-accent text-white'
            : 'text-gray-400 hover:text-white hover:bg-white/5'
        }`}
      >
        <Monitor className="w-4 h-4" />
        <span>Monitoring</span>
      </button>

      <button
        onClick={() => setActiveTab('sessions')}
        className={`flex items-center gap-2 px-4 py-2 rounded-md text-sm font-medium transition-colors ${
          activeTab === 'sessions'
            ? 'bg-accent text-white'
            : 'text-gray-400 hover:text-white hover:bg-white/5'
        }`}
      >
        <Terminal className="w-4 h-4" />
        <span>Sessions</span>
        {activeSessions > 0 && (
          <span className="ml-1 px-1.5 py-0.5 text-xs rounded-full bg-yellow-500/20 text-yellow-400">
            {activeSessions}
          </span>
        )}
      </button>
    </div>
  );
}
