import { create } from 'zustand';
import type { ConversationEntry, Task, InboxItem, Builder, SystemHealth } from '../api/client';

interface EventStore {
  // Conversation
  conversation: ConversationEntry[];
  addConversationEntry: (entry: ConversationEntry) => void;
  setConversation: (entries: ConversationEntry[]) => void;

  // Tasks
  tasks: Task[];
  setTasks: (tasks: Task[]) => void;
  updateTask: (task: Task) => void;

  // Inbox
  inbox: InboxItem[];
  unreadCount: number;
  setInbox: (items: InboxItem[], unreadCount: number) => void;
  addInboxItem: (item: InboxItem) => void;
  markAllRead: () => void;

  // Builders
  builders: Builder[];
  setBuilders: (builders: Builder[]) => void;
  updateBuilderStatus: (name: string, status: string) => void;

  // System
  health: SystemHealth | null;
  setHealth: (health: SystemHealth) => void;

  // WebSocket
  wsConnected: boolean;
  setWsConnected: (connected: boolean) => void;
}

export const useEventStore = create<EventStore>((set) => ({
  // Conversation
  conversation: [],
  addConversationEntry: (entry) =>
    set((state) => ({
      conversation: [...state.conversation, entry].slice(-500) // Keep last 500
    })),
  setConversation: (entries) => set({ conversation: entries }),

  // Tasks
  tasks: [],
  setTasks: (tasks) => set({ tasks }),
  updateTask: (task) =>
    set((state) => ({
      tasks: state.tasks.map((t) => (t.task_id === task.task_id ? task : t))
    })),

  // Inbox
  inbox: [],
  unreadCount: 0,
  setInbox: (items, unreadCount) => set({ inbox: items, unreadCount }),
  addInboxItem: (item) =>
    set((state) => ({
      inbox: [item, ...state.inbox].slice(0, 100),
      unreadCount: state.unreadCount + (item.is_read ? 0 : 1)
    })),
  markAllRead: () =>
    set((state) => ({
      inbox: state.inbox.map((i) => ({ ...i, is_read: true })),
      unreadCount: 0
    })),

  // Builders
  builders: [],
  setBuilders: (builders) => set({ builders }),
  updateBuilderStatus: (name, status) =>
    set((state) => ({
      builders: state.builders.map((b) =>
        b.name === name ? { ...b, status } : b
      )
    })),

  // System
  health: null,
  setHealth: (health) => set({ health }),

  // WebSocket
  wsConnected: false,
  setWsConnected: (connected) => set({ wsConnected: connected })
}));
