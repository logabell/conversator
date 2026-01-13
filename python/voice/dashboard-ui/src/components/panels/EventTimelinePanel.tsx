import { useEffect, useState } from 'react';
import { Activity, CheckCircle, XCircle, Clock, MessageSquare, Wrench, FileText, User, Bot } from 'lucide-react';
import { api, TimelineEvent } from '../../api/client';

type FilterType = 'all' | 'conversation' | 'task_event' | 'tool_call';

export function EventTimelinePanel() {
  const [events, setEvents] = useState<TimelineEvent[]>([]);
  const [filter, setFilter] = useState<FilterType>('all');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchEvents = async () => {
      try {
        const eventTypes = filter === 'all' ? undefined : filter;
        const { events } = await api.getEventTimeline(50, 0, eventTypes);
        setEvents(events);
      } catch (e) {
        console.error('Failed to fetch timeline:', e);
      } finally {
        setLoading(false);
      }
    };

    fetchEvents();
    const interval = setInterval(fetchEvents, 5000);
    return () => clearInterval(interval);
  }, [filter]);

  const filteredEvents = events;

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center gap-2 p-4 border-b border-white/10">
        <Activity className="w-5 h-5 text-accent" />
        <h2 className="font-semibold">Event Timeline</h2>
        <span className="ml-auto text-xs text-gray-500">{events.length} events</span>
      </div>

      {/* Filter */}
      <div className="px-4 py-2 border-b border-white/10">
        <select
          className="w-full bg-surface border border-white/10 rounded px-2 py-1.5 text-sm"
          value={filter}
          onChange={(e) => setFilter(e.target.value as FilterType)}
        >
          <option value="all">All Events</option>
          <option value="conversation">Conversation</option>
          <option value="task_event">Task Events</option>
          <option value="tool_call">Tool Calls</option>
        </select>
      </div>

      <div className="flex-1 overflow-y-auto p-4">
        {loading ? (
          <div className="text-center text-gray-500 py-8">Loading events...</div>
        ) : filteredEvents.length === 0 ? (
          <div className="text-center text-gray-500 py-8">No events yet</div>
        ) : (
          <div className="relative">
            {/* Timeline line */}
            <div className="absolute left-[11px] top-2 bottom-2 w-0.5 bg-white/10" />

            <div className="space-y-3">
              {filteredEvents.map((event) => (
                <TimelineItem key={event.id} event={event} />
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function TimelineItem({ event }: { event: TimelineEvent }) {
  const StatusIcon = event.status === 'success' ? CheckCircle :
                     event.status === 'error' ? XCircle : Clock;
  const statusColor = event.status === 'success' ? 'text-green-400' :
                      event.status === 'error' ? 'text-red-400' : 'text-yellow-400';
  const statusBg = event.status === 'success' ? 'bg-green-500/20' :
                   event.status === 'error' ? 'bg-red-500/20' : 'bg-yellow-500/20';

  const getIcon = () => {
    if (event.type === 'task_event') {
      return FileText;
    }
    if (event.subtype === 'user') return User;
    if (event.subtype === 'assistant') return Bot;
    if (event.subtype === 'tool_call' || event.subtype === 'tool_result') return Wrench;
    return MessageSquare;
  };

  const Icon = getIcon();

  const getLabel = () => {
    if (event.type === 'task_event') {
      return event.subtype.replace(/([A-Z])/g, ' $1').trim();
    }
    if (event.subtype === 'user') return 'User';
    if (event.subtype === 'assistant') return 'Assistant';
    if (event.subtype === 'tool_call') return event.details.tool_name || 'Tool Call';
    return event.subtype;
  };

  const getContent = () => {
    if (event.details.content) {
      return event.details.content.length > 100
        ? event.details.content.slice(0, 100) + '...'
        : event.details.content;
    }
    if (event.details.tool_name) {
      return `${event.details.tool_name}${event.details.duration_ms ? ` (${event.details.duration_ms.toFixed(0)}ms)` : ''}`;
    }
    if (event.type === 'task_event' && event.task_id) {
      return `Task: ${event.task_id.slice(0, 8)}...`;
    }
    return null;
  };

  const content = getContent();

  return (
    <div className="flex gap-3 pl-0">
      {/* Status dot */}
      <div className={`w-6 h-6 rounded-full flex items-center justify-center z-10 ${statusBg}`}>
        <StatusIcon className={`w-3 h-3 ${statusColor}`} />
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <Icon className="w-3.5 h-3.5 text-accent" />
          <span className="text-xs font-medium text-accent">{getLabel()}</span>
          <span className="text-xs text-gray-500">
            {new Date(event.timestamp).toLocaleTimeString()}
          </span>
        </div>
        {content && (
          <div className="text-sm text-gray-400 mt-1 truncate">{content}</div>
        )}
      </div>
    </div>
  );
}
