import { useState, useEffect } from 'react';
import { Sparkles, Bot, Brain, Search, Hammer, Lightbulb, Loader2, CheckCircle, XCircle, Clock, Send, Wifi, ChevronDown, ChevronUp } from 'lucide-react';
import { useEventStore, ActivityItem } from '../../stores/eventStore';

export function ActivityFeedPanel() {
  const activities = useEventStore((s) => s.activities);

  // Get the currently active (in-progress) activities
  const activeActivities = activities.filter(
    (a) => a.action === 'started' || a.action === 'working' || a.action === 'streaming'
  );
  const hasActiveWork = activeActivities.length > 0;

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center gap-2 p-4 border-b border-white/10">
        <Sparkles className={`w-5 h-5 text-accent ${hasActiveWork ? 'animate-pulse' : ''}`} />
        <h2 className="font-semibold">Activity Feed</h2>
        {hasActiveWork && (
          <span className="ml-auto flex items-center gap-1.5 text-xs text-yellow-400">
            <Loader2 className="w-3 h-3 animate-spin" />
            Working
          </span>
        )}
        {!hasActiveWork && activities.length > 0 && (
          <span className="ml-auto text-xs text-gray-500">{activities.length} events</span>
        )}
      </div>

      <div className="flex-1 overflow-y-auto p-4">
        {activities.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-gray-500">
            <Sparkles className="w-8 h-8 mb-2 opacity-50" />
            <p className="text-sm">No activity yet</p>
            <p className="text-xs opacity-70">Agent work will appear here</p>
          </div>
        ) : (
          <div className="space-y-2">
            {activities.map((activity) => (
              <ActivityItemRow key={activity.id} activity={activity} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function ActivityItemRow({ activity }: { activity: ActivityItem }) {
  const AgentIcon = getAgentIcon(activity.agent);
  const StatusIcon = getStatusIcon(activity.action);
  const statusColor = getStatusColor(activity.action);
  const agentColor = getAgentColor(activity.agent);
  const [expanded, setExpanded] = useState(false);
  const [elapsedTime, setElapsedTime] = useState<number | null>(null);

  const isActive = activity.action === 'started' || activity.action === 'working' || activity.action === 'streaming';
  const isPending = activity.action === 'request_sent' || activity.action === 'sse_connected';

  // Track elapsed time for active activities
  useEffect(() => {
    if ((isActive || isPending) && !activity.duration_ms) {
      const startTime = new Date(activity.timestamp).getTime();
      setElapsedTime(Math.floor((Date.now() - startTime) / 1000));

      const interval = setInterval(() => {
        setElapsedTime(Math.floor((Date.now() - startTime) / 1000));
      }, 1000);
      return () => clearInterval(interval);
    }
  }, [activity.timestamp, isActive, isPending, activity.duration_ms]);

  return (
    <div className={`rounded-lg p-3 border transition-all ${
      isActive
        ? 'bg-yellow-500/10 border-yellow-500/30'
        : isPending
          ? 'bg-blue-500/10 border-blue-500/30'
          : activity.action === 'completed'
            ? 'bg-green-500/5 border-white/5'
            : activity.action === 'error'
              ? 'bg-red-500/10 border-red-500/30'
              : 'bg-white/5 border-white/5'
    }`}>
      <div className="flex items-start gap-3">
        {/* Agent icon */}
        <div className={`w-8 h-8 rounded-full flex items-center justify-center ${agentColor}`}>
          <AgentIcon className="w-4 h-4" />
        </div>

        {/* Content */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium capitalize">{activity.agent}</span>
            <span className={`flex items-center gap-1 text-xs ${statusColor}`}>
              {isActive ? (
                <Loader2 className="w-3 h-3 animate-spin" />
              ) : (
                <StatusIcon className="w-3 h-3" />
              )}
              {activity.action.replace('_', ' ')}
            </span>
            <span className="text-xs text-gray-500 ml-auto">
              {new Date(activity.timestamp).toLocaleTimeString()}
            </span>
          </div>
          <p className="text-sm text-gray-300 mt-1 truncate">{activity.message}</p>
          {activity.detail && !expanded && (
            <p className="text-xs text-gray-500 mt-1 truncate">{activity.detail}</p>
          )}

          {/* Elapsed time for in-progress activities */}
          {(isActive || isPending) && elapsedTime !== null && (
            <p className="text-xs text-yellow-400 mt-1 flex items-center gap-1">
              <Clock className="w-3 h-3" />
              {elapsedTime}s elapsed
            </p>
          )}

          {/* Duration for completed activities */}
          {activity.duration_ms && (
            <p className="text-xs text-gray-500 mt-1">
              Completed in {(activity.duration_ms / 1000).toFixed(1)}s
            </p>
          )}

          {/* Expandable output for completed activities with detail */}
          {activity.action === 'completed' && activity.detail && activity.detail.length > 100 && (
            <div className="mt-2">
              <button
                onClick={() => setExpanded(!expanded)}
                className="text-xs text-accent hover:text-accent/80 flex items-center gap-1"
              >
                {expanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                {expanded ? 'Hide output' : 'View output'}
              </button>
              {expanded && (
                <pre className="mt-2 text-xs bg-black/30 rounded p-2 max-h-48 overflow-y-auto whitespace-pre-wrap text-gray-300">
                  {activity.detail}
                </pre>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function getAgentIcon(agent: ActivityItem['agent']) {
  // Handle both old names and cvtr- prefixed names
  const normalizedAgent = agent.replace('cvtr-', '');
  switch (normalizedAgent) {
    case 'gemini':
      return Bot;
    case 'planner':
      return Brain;
    case 'context-reader':
      return Search;
    case 'builder':
      return Hammer;
    case 'brainstormer':
      return Lightbulb;
    case 'summarizer':
      return Sparkles;
    default:
      return Sparkles;
  }
}

function getAgentColor(agent: ActivityItem['agent']) {
  // Handle both old names and cvtr- prefixed names
  const normalizedAgent = agent.replace('cvtr-', '');
  switch (normalizedAgent) {
    case 'gemini':
      return 'bg-blue-500/20 text-blue-400';
    case 'planner':
      return 'bg-purple-500/20 text-purple-400';
    case 'context-reader':
      return 'bg-cyan-500/20 text-cyan-400';
    case 'builder':
      return 'bg-orange-500/20 text-orange-400';
    case 'brainstormer':
      return 'bg-yellow-500/20 text-yellow-400';
    case 'summarizer':
      return 'bg-pink-500/20 text-pink-400';
    default:
      return 'bg-gray-500/20 text-gray-400';
  }
}

function getStatusIcon(action: ActivityItem['action']) {
  switch (action) {
    case 'completed':
      return CheckCircle;
    case 'error':
      return XCircle;
    case 'request_sent':
      return Send;
    case 'sse_connected':
      return Wifi;
    default:
      return Clock;
  }
}

function getStatusColor(action: ActivityItem['action']) {
  switch (action) {
    case 'completed':
      return 'text-green-400';
    case 'error':
      return 'text-red-400';
    case 'request_sent':
      return 'text-blue-400';
    case 'sse_connected':
      return 'text-cyan-400';
    case 'started':
    case 'working':
    case 'streaming':
      return 'text-yellow-400';
    default:
      return 'text-gray-400';
  }
}
