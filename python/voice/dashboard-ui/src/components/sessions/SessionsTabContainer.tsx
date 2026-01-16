import { SessionListPanel } from '../panels/SessionListPanel';
import { SessionDetailPanel } from '../panels/SessionDetailPanel';

export function SessionsTabContainer() {
  return (
    <div className="flex-1 flex overflow-hidden">
      {/* Sidebar - Session List */}
      <div className="w-64 flex-shrink-0 bg-surface-secondary border-r border-white/10 overflow-hidden">
        <SessionListPanel />
      </div>

      {/* Main Content - Session Detail */}
      <div className="flex-1 bg-surface-tertiary overflow-hidden">
        <SessionDetailPanel />
      </div>
    </div>
  );
}
