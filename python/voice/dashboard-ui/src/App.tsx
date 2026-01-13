import { useEffect, useCallback } from 'react';
import { Zap, WifiOff, Wifi } from 'lucide-react';
import { useWebSocket, WebSocketMessage } from './hooks/useWebSocket';
import { useEventStore } from './stores/eventStore';
import { api, ConversationEntry, Task, InboxItem } from './api/client';
import { ConversationLogPanel } from './components/panels/ConversationLogPanel';
import { TaskStatusPanel } from './components/panels/TaskStatusPanel';
import { BuilderStatusPanel } from './components/panels/BuilderStatusPanel';
import { InboxPanel } from './components/panels/InboxPanel';
import { SystemHealthPanel } from './components/panels/SystemHealthPanel';
import { EventTimelinePanel } from './components/panels/EventTimelinePanel';

function App() {
  const setConversation = useEventStore((s) => s.setConversation);
  const addConversationEntry = useEventStore((s) => s.addConversationEntry);
  const setTasks = useEventStore((s) => s.setTasks);
  const updateTask = useEventStore((s) => s.updateTask);
  const setInbox = useEventStore((s) => s.setInbox);
  const addInboxItem = useEventStore((s) => s.addInboxItem);
  const setBuilders = useEventStore((s) => s.setBuilders);
  const updateBuilderStatus = useEventStore((s) => s.updateBuilderStatus);
  const setHealth = useEventStore((s) => s.setHealth);
  const setWsConnected = useEventStore((s) => s.setWsConnected);
  const wsConnected = useEventStore((s) => s.wsConnected);

  // Handle WebSocket messages
  const handleMessage = useCallback((msg: WebSocketMessage) => {
    switch (msg.type) {
      case 'conversation_entry':
        addConversationEntry(msg.data as ConversationEntry);
        break;
      case 'task_update':
        updateTask(msg.data as Task);
        break;
      case 'inbox_item':
        addInboxItem(msg.data as InboxItem);
        break;
      case 'builder_status': {
        const { name, status } = msg.data as { name: string; status: string };
        updateBuilderStatus(name, status);
        break;
      }
    }
  }, [addConversationEntry, updateTask, addInboxItem, updateBuilderStatus]);

  // WebSocket connection
  useWebSocket({
    onMessage: handleMessage,
    onConnect: () => setWsConnected(true),
    onDisconnect: () => setWsConnected(false)
  });

  // Initial data fetch
  useEffect(() => {
    const fetchInitialData = async () => {
      try {
        // Fetch all data in parallel
        const [conversationRes, tasksRes, inboxRes, buildersRes, healthRes] = await Promise.all([
          api.getConversation(200),
          api.getTasks(),
          api.getInbox(),
          api.getBuilders(),
          api.getHealth()
        ]);

        setConversation(conversationRes.entries);
        setTasks(tasksRes.tasks);
        setInbox(inboxRes.items, inboxRes.unread_count);
        setBuilders(buildersRes.builders);
        setHealth(healthRes);
      } catch (e) {
        console.error('Failed to fetch initial data:', e);
      }
    };

    fetchInitialData();

    // Refresh health periodically
    const healthInterval = setInterval(async () => {
      try {
        const health = await api.getHealth();
        setHealth(health);
      } catch (e) {
        console.error('Health check failed:', e);
      }
    }, 10000);

    return () => clearInterval(healthInterval);
  }, [setConversation, setTasks, setInbox, setBuilders, setHealth]);

  return (
    <div className="min-h-screen bg-surface flex flex-col">
      {/* Header */}
      <header className="border-b border-white/10 bg-surface-secondary px-6 py-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Zap className="w-6 h-6 text-accent" />
            <h1 className="text-xl font-bold">Conversator Dashboard</h1>
          </div>
          <div className="flex items-center gap-2 text-sm">
            {wsConnected ? (
              <>
                <Wifi className="w-4 h-4 text-green-400" />
                <span className="text-green-400">Connected</span>
              </>
            ) : (
              <>
                <WifiOff className="w-4 h-4 text-red-400" />
                <span className="text-red-400">Disconnected</span>
              </>
            )}
          </div>
        </div>
      </header>

      {/* Main Grid */}
      <main className="flex-1 p-4 grid grid-cols-12 gap-4 overflow-hidden">
        {/* Conversation Log - Main panel */}
        <div className="col-span-5 bg-surface-secondary rounded-xl border border-white/10 overflow-hidden">
          <ConversationLogPanel />
        </div>

        {/* Right side panels */}
        <div className="col-span-7 grid grid-rows-2 gap-4 overflow-hidden">
          {/* Top row: Tasks + Event Timeline + Service Health */}
          <div className="grid grid-cols-3 gap-4 overflow-hidden">
            <div className="bg-surface-secondary rounded-xl border border-white/10 overflow-hidden">
              <TaskStatusPanel />
            </div>
            <div className="bg-surface-secondary rounded-xl border border-white/10 overflow-hidden">
              <EventTimelinePanel />
            </div>
            <div className="bg-surface-secondary rounded-xl border border-white/10 overflow-hidden">
              <SystemHealthPanel />
            </div>
          </div>

          {/* Bottom row: Inbox + Builders */}
          <div className="grid grid-cols-2 gap-4 overflow-hidden">
            <div className="bg-surface-secondary rounded-xl border border-white/10 overflow-hidden">
              <InboxPanel />
            </div>
            <div className="bg-surface-secondary rounded-xl border border-white/10 overflow-hidden">
              <BuilderStatusPanel />
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}

export default App;
