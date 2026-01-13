// In development, API is on different port (8080) than Vite dev server (5173)
const API_BASE = import.meta.env.DEV ? 'http://localhost:8080/api' : '/api';

export interface Task {
  task_id: string;
  title: string;
  status: string;
  builder_id?: string;
  created_at: string;
  updated_at: string;
  working_prompt_path?: string;
}

export interface InboxItem {
  inbox_id: string;
  task_id?: string;
  severity: 'info' | 'success' | 'warning' | 'error' | 'blocking';
  summary: string;
  detail?: string;
  is_read: boolean;
  created_at: string;
}

export interface Builder {
  name: string;
  type: string;
  port: number;
  model: string;
  status: string;
  active_tasks: number;
}

export interface ConversationEntry {
  entry_id: number;
  timestamp: string;
  role: 'user' | 'assistant' | 'tool_call';
  content: string;
  tool_name?: string;
  tool_args?: Record<string, unknown>;
  tool_result?: Record<string, unknown>;
  duration_ms?: number;
}

export interface SystemHealth {
  status: string;
  components: {
    opencode_orchestration?: {
      status: string;
      port?: number;
      managed?: boolean;
      running?: boolean;
      error?: string;
    };
    gemini_live?: {
      status: string;
      model?: string;
    };
    state_store: { status: string; path?: string };
    builders: Record<string, string>;
    websocket: { active_connections: number };
    config: { status: string; root_project_dir?: string };
  };
}

export interface TimelineEvent {
  id: string;
  timestamp: string;
  type: 'task_event' | 'conversation';
  subtype: string;
  status: 'success' | 'error' | 'pending';
  task_id?: string;
  details: {
    content?: string;
    tool_name?: string;
    duration_ms?: number;
    event_type?: string;
    payload?: Record<string, unknown>;
  };
}

// Fetch helpers
async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined
  });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

// API methods
export const api = {
  // Tasks
  getTasks: (status?: string) =>
    get<{ tasks: Task[] }>(`/tasks${status ? `?status=${status}` : ''}`),

  getActiveTasks: () =>
    get<{ tasks: Task[] }>('/tasks/active'),

  getTask: (id: string) =>
    get<Task>(`/tasks/${id}`),

  // Inbox
  getInbox: (unreadOnly = false) =>
    get<{ items: InboxItem[]; unread_count: number }>(`/inbox?unread_only=${unreadOnly}`),

  getUnreadCount: () =>
    get<{ count: number }>('/inbox/unread/count'),

  acknowledgeInbox: (ids?: string[]) =>
    post<{ acknowledged: number }>('/inbox/acknowledge', { inbox_ids: ids }),

  // Builders
  getBuilders: () =>
    get<{ builders: Builder[] }>('/builders'),

  getBuildersHealth: () =>
    get<{ health: Record<string, string> }>('/builders/health/all'),

  // Events / Conversation
  getConversation: (limit = 100) =>
    get<{ entries: ConversationEntry[] }>(`/events/conversation?limit=${limit}`),

  getTranscript: (count = 20) =>
    get<{ transcript: string }>(`/events/conversation/transcript?count=${count}`),

  // System
  getHealth: () =>
    get<SystemHealth>('/system/health'),

  getStats: () =>
    get<Record<string, unknown>>('/system/stats'),

  // Event Timeline
  getEventTimeline: (limit = 100, afterId = 0, eventTypes?: string) =>
    get<{ events: TimelineEvent[]; count: number }>(
      `/system/events/timeline?limit=${limit}&after_id=${afterId}${eventTypes ? `&event_types=${eventTypes}` : ''}`
    )
};
