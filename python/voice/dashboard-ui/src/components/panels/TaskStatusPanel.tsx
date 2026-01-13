import { ListTodo, Clock, CheckCircle2, XCircle } from 'lucide-react';
import { useEventStore } from '../../stores/eventStore';
import { StatusBadge } from '../shared/StatusBadge';

export function TaskStatusPanel() {
  const tasks = useEventStore((s) => s.tasks);

  const activeTasks = tasks.filter((t) =>
    !['done', 'failed', 'canceled'].includes(t.status)
  );
  const completedTasks = tasks.filter((t) =>
    ['done', 'failed', 'canceled'].includes(t.status)
  );

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center gap-2 p-4 border-b border-white/10">
        <ListTodo className="w-5 h-5 text-accent" />
        <h2 className="font-semibold">Tasks</h2>
        <span className="text-xs text-gray-400 ml-auto">
          {activeTasks.length} active
        </span>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {/* Active Tasks */}
        {activeTasks.length > 0 && (
          <div>
            <h3 className="text-xs font-medium text-gray-400 uppercase mb-2">Active</h3>
            <div className="space-y-2">
              {activeTasks.map((task) => (
                <TaskCard key={task.task_id} task={task} />
              ))}
            </div>
          </div>
        )}

        {/* Completed Tasks */}
        {completedTasks.length > 0 && (
          <div>
            <h3 className="text-xs font-medium text-gray-400 uppercase mb-2">Completed</h3>
            <div className="space-y-2">
              {completedTasks.slice(0, 5).map((task) => (
                <TaskCard key={task.task_id} task={task} />
              ))}
            </div>
          </div>
        )}

        {tasks.length === 0 && (
          <div className="text-center text-gray-500 py-8">
            No tasks yet
          </div>
        )}
      </div>
    </div>
  );
}

interface TaskCardProps {
  task: {
    task_id: string;
    title: string;
    status: string;
    builder_id?: string;
    created_at: string;
    updated_at: string;
  };
}

function TaskCard({ task }: TaskCardProps) {
  const statusIcon = {
    pending: <Clock className="w-4 h-4 text-yellow-400" />,
    planning: <Clock className="w-4 h-4 text-blue-400 animate-pulse" />,
    executing: <Clock className="w-4 h-4 text-purple-400 animate-pulse" />,
    done: <CheckCircle2 className="w-4 h-4 text-green-400" />,
    failed: <XCircle className="w-4 h-4 text-red-400" />,
    canceled: <XCircle className="w-4 h-4 text-gray-400" />
  }[task.status] || <Clock className="w-4 h-4 text-gray-400" />;

  return (
    <div className="rounded-lg border border-white/10 bg-surface-secondary p-3">
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-start gap-2">
          {statusIcon}
          <div>
            <div className="font-medium text-sm">{task.title}</div>
            <div className="text-xs text-gray-400 mt-1">
              {task.builder_id && (
                <span className="mr-2">Builder: {task.builder_id}</span>
              )}
              <span>
                {new Date(task.updated_at).toLocaleTimeString()}
              </span>
            </div>
          </div>
        </div>
        <StatusBadge status={task.status} />
      </div>
    </div>
  );
}
