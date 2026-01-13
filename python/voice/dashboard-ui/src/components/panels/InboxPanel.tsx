import { Inbox, Bell, AlertTriangle, CheckCircle, Info, XOctagon, Check } from 'lucide-react';
import { useEventStore } from '../../stores/eventStore';
import { api } from '../../api/client';

export function InboxPanel() {
  const inbox = useEventStore((s) => s.inbox);
  const unreadCount = useEventStore((s) => s.unreadCount);
  const markAllRead = useEventStore((s) => s.markAllRead);

  const handleAcknowledgeAll = async () => {
    try {
      await api.acknowledgeInbox();
      markAllRead();
    } catch (e) {
      console.error('Failed to acknowledge:', e);
    }
  };

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center gap-2 p-4 border-b border-white/10">
        <Inbox className="w-5 h-5 text-accent" />
        <h2 className="font-semibold">Notifications</h2>
        {unreadCount > 0 && (
          <span className="bg-accent text-white text-xs rounded-full px-2 py-0.5">
            {unreadCount}
          </span>
        )}
        {unreadCount > 0 && (
          <button
            onClick={handleAcknowledgeAll}
            className="ml-auto text-xs text-gray-400 hover:text-white flex items-center gap-1 transition-colors"
          >
            <Check className="w-3 h-3" />
            Mark all read
          </button>
        )}
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-2">
        {inbox.length === 0 ? (
          <div className="text-center text-gray-500 py-8">
            No notifications
          </div>
        ) : (
          inbox.map((item) => (
            <NotificationCard key={item.inbox_id} item={item} />
          ))
        )}
      </div>
    </div>
  );
}

interface NotificationCardProps {
  item: {
    inbox_id: string;
    task_id?: string;
    severity: string;
    summary: string;
    detail?: string;
    is_read: boolean;
    created_at: string;
  };
}

function NotificationCard({ item }: NotificationCardProps) {
  const severityConfig = {
    info: { icon: Info, color: 'text-blue-400', bg: 'bg-blue-500/10 border-blue-500/20' },
    success: { icon: CheckCircle, color: 'text-green-400', bg: 'bg-green-500/10 border-green-500/20' },
    warning: { icon: AlertTriangle, color: 'text-yellow-400', bg: 'bg-yellow-500/10 border-yellow-500/20' },
    error: { icon: Bell, color: 'text-red-400', bg: 'bg-red-500/10 border-red-500/20' },
    blocking: { icon: XOctagon, color: 'text-red-400', bg: 'bg-red-500/10 border-red-500/30' }
  }[item.severity] || { icon: Info, color: 'text-gray-400', bg: 'bg-gray-500/10 border-gray-500/20' };

  const Icon = severityConfig.icon;

  return (
    <div className={`rounded-lg border p-3 ${severityConfig.bg} ${!item.is_read ? 'ring-1 ring-accent/50' : ''}`}>
      <div className="flex items-start gap-2">
        <Icon className={`w-4 h-4 mt-0.5 ${severityConfig.color}`} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between gap-2">
            <span className={`font-medium text-sm ${!item.is_read ? 'text-white' : 'text-gray-300'}`}>
              {item.summary}
            </span>
            <span className="text-xs text-gray-500 flex-shrink-0">
              {new Date(item.created_at).toLocaleTimeString()}
            </span>
          </div>
          {item.detail && (
            <p className="text-xs text-gray-400 mt-1 truncate">{item.detail}</p>
          )}
        </div>
      </div>
    </div>
  );
}
