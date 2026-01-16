import { useEffect, useMemo, useState } from 'react';
import {
  Terminal,
  Check,
  AlertCircle,
  Loader2,
  Clock,
  Brain,
  Search,
  Sparkles,
  FileText,
  Hammer,
  ChevronDown,
  ChevronRight,
  Layers,
  Cpu
} from 'lucide-react';
import { useEventStore } from '../../stores/eventStore';
import { api, OpenCodeSession } from '../../api/client';

const agentIcons: Record<string, React.ReactNode> = {
  'cvtr-planner': <Brain className="w-4 h-4" />,
  'cvtr-brainstormer': <Sparkles className="w-4 h-4" />,
  'cvtr-context-reader': <Search className="w-4 h-4" />,
  'cvtr-summarizer': <FileText className="w-4 h-4" />,
  'build': <Hammer className="w-4 h-4" />,
  'builder': <Hammer className="w-4 h-4" />,
};

interface SessionGroup {
  id: string;
  title: string;
  source: string;
  instance?: string;
  sessions: OpenCodeSession[];
  hasActive: boolean;
  icon: React.ReactNode;
  badgeColor: string;
}

export function SessionListPanel() {
  const sessions = useEventStore((s) => s.sessions);
  const selectedSessionId = useEventStore((s) => s.selectedSessionId);
  const setSessions = useEventStore((s) => s.setSessions);
  const selectSession = useEventStore((s) => s.selectSession);

  // Collapsible group state with localStorage persistence
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(() => {
    try {
      const saved = localStorage.getItem('session-expanded-groups');
      return saved ? new Set(JSON.parse(saved)) : new Set(['conversator', 'builder', 'layer2']);
    } catch {
      return new Set(['conversator', 'builder', 'layer2']);
    }
  });

  // Persist expanded state
  useEffect(() => {
    localStorage.setItem('session-expanded-groups', JSON.stringify([...expandedGroups]));
  }, [expandedGroups]);

  useEffect(() => {
    // Fetch sessions on mount
    api.getSessions()
      .then((res) => setSessions(res.sessions))
      .catch(console.error);
  }, [setSessions]);

  const toggleGroup = (groupId: string) => {
    setExpandedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(groupId)) {
        next.delete(groupId);
      } else {
        next.add(groupId);
      }
      return next;
    });
  };

  // Group sessions by source and instance
  const groups = useMemo<SessionGroup[]>(() => {
    const result: SessionGroup[] = [];

    // Conversator subagents (Layer 2)
    const conversator = sessions.filter((s) => s.source === 'conversator');
    if (conversator.length > 0) {
      result.push({
        id: 'conversator',
        title: 'Conversator (Layer 2)',
        source: 'conversator',
        sessions: conversator,
        hasActive: conversator.some((s) => s.status === 'active'),
        icon: <Layers className="w-4 h-4" />,
        badgeColor: 'bg-purple-500/20 text-purple-400',
      });
    }

    // Builder sessions - group by instance
    const builderSessions = sessions.filter((s) => s.source === 'builder');
    const buildersByInstance = new Map<string, OpenCodeSession[]>();

    builderSessions.forEach((s) => {
      const instance = s.instance || 'default';
      if (!buildersByInstance.has(instance)) {
        buildersByInstance.set(instance, []);
      }
      buildersByInstance.get(instance)!.push(s);
    });

    // Create a group for each builder instance
    buildersByInstance.forEach((instanceSessions, instance) => {
      result.push({
        id: `builder-${instance}`,
        title: instance === 'default' ? 'Builder (Layer 3)' : `Builder: ${instance}`,
        source: 'builder',
        instance,
        sessions: instanceSessions,
        hasActive: instanceSessions.some((s) => s.status === 'active'),
        icon: <Cpu className="w-4 h-4" />,
        badgeColor: 'bg-blue-500/20 text-blue-400',
      });
    });

    // External sessions
    const external = sessions.filter((s) => s.source === 'external');
    if (external.length > 0) {
      result.push({
        id: 'external',
        title: 'External',
        source: 'external',
        sessions: external,
        hasActive: external.some((s) => s.status === 'active'),
        icon: <Terminal className="w-4 h-4" />,
        badgeColor: 'bg-gray-500/20 text-gray-400',
      });
    }

    return result;
  }, [sessions]);

  // Count active sessions
  const activeSessions = sessions.filter((s) => s.status === 'active').length;

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'active':
        return <Loader2 className="w-3.5 h-3.5 animate-spin text-yellow-400" />;
      case 'completed':
        return <Check className="w-3.5 h-3.5 text-green-400" />;
      case 'error':
        return <AlertCircle className="w-3.5 h-3.5 text-red-400" />;
      default:
        return <Clock className="w-3.5 h-3.5 text-gray-400" />;
    }
  };

  const getAgentIcon = (agentName: string) => {
    return agentIcons[agentName] || <Terminal className="w-4 h-4" />;
  };

  const formatTime = (timestamp: string) => {
    return new Date(timestamp).toLocaleTimeString([], {
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center gap-2 p-4 border-b border-white/10">
        <Terminal className="w-5 h-5 text-accent" />
        <h2 className="font-semibold">Sessions</h2>
        <div className="ml-auto flex items-center gap-2">
          {activeSessions > 0 && (
            <span className="flex items-center gap-1.5 text-xs">
              <span className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
              <span className="text-green-400">{activeSessions} active</span>
            </span>
          )}
          <span className="text-xs text-gray-400">
            {sessions.length} total
          </span>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto">
        {sessions.length === 0 ? (
          <div className="text-center text-gray-500 py-8">
            <Terminal className="w-8 h-8 mx-auto mb-2 opacity-50" />
            <p className="text-sm">No sessions yet</p>
            <p className="text-xs mt-1">Sessions will appear when agents start working</p>
          </div>
        ) : (
          <div className="py-2">
            {groups.map((group) => {
              const isExpanded = expandedGroups.has(group.id);

              return (
                <div key={group.id} className="mb-2">
                  {/* Group Header - Clickable to collapse */}
                  <button
                    onClick={() => toggleGroup(group.id)}
                    className="w-full flex items-center gap-2 px-4 py-2 text-xs font-medium text-gray-400 uppercase tracking-wider hover:bg-white/5 transition-colors"
                  >
                    {isExpanded ? (
                      <ChevronDown className="w-3 h-3" />
                    ) : (
                      <ChevronRight className="w-3 h-3" />
                    )}
                    <span className={group.badgeColor}>
                      {group.icon}
                    </span>
                    <span>{group.title}</span>

                    {/* Active indicator */}
                    {group.hasActive && (
                      <span className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
                    )}

                    <span className="ml-auto text-gray-500">
                      {group.sessions.length}
                    </span>
                  </button>

                  {/* Sessions in Group - Collapsible */}
                  {isExpanded && (
                    <div className="space-y-0.5">
                      {group.sessions.map((session) => (
                        <button
                          key={session.session_id}
                          onClick={() => selectSession(session.session_id)}
                          className={`w-full px-4 py-2.5 text-left transition-colors ${
                            selectedSessionId === session.session_id
                              ? 'bg-accent/10 border-l-2 border-accent'
                              : 'hover:bg-white/5 border-l-2 border-transparent'
                          }`}
                        >
                          <div className="flex items-center gap-2">
                            <span className="text-gray-400">
                              {getAgentIcon(session.agent_name)}
                            </span>
                            <span className="font-mono text-sm truncate flex-1">
                              {session.agent_name}
                            </span>
                            {getStatusIcon(session.status)}
                          </div>

                          <div className="flex items-center gap-2 mt-1 text-xs text-gray-500">
                            <span>{formatTime(session.created_at)}</span>
                            <span className="text-gray-600">|</span>
                            <span>{session.message_count} msgs</span>
                            {session.instance && session.instance !== 'layer2' && (
                              <>
                                <span className="text-gray-600">|</span>
                                <span className="text-blue-400">
                                  {session.instance}
                                </span>
                              </>
                            )}
                            {session.task_id && (
                              <>
                                <span className="text-gray-600">|</span>
                                <span className="text-accent">
                                  Task: {session.task_id.slice(0, 8)}
                                </span>
                              </>
                            )}
                          </div>
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
