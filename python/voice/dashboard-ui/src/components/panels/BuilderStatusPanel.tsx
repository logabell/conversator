import { Server, Cpu, Activity } from 'lucide-react';
import { useEventStore } from '../../stores/eventStore';
import { StatusBadge } from '../shared/StatusBadge';

export function BuilderStatusPanel() {
  const builders = useEventStore((s) => s.builders);

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center gap-2 p-4 border-b border-white/10">
        <Server className="w-5 h-5 text-accent" />
        <h2 className="font-semibold">Builders</h2>
        <span className="text-xs text-gray-400 ml-auto">
          {builders.filter((b) => b.status === 'healthy').length}/{builders.length} healthy
        </span>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {builders.length === 0 ? (
          <div className="text-center text-gray-500 py-8">
            No builders configured
          </div>
        ) : (
          builders.map((builder) => (
            <BuilderCard key={builder.name} builder={builder} />
          ))
        )}
      </div>
    </div>
  );
}

interface BuilderCardProps {
  builder: {
    name: string;
    type: string;
    port: number;
    model: string;
    status: string;
    active_tasks: number;
  };
}

function BuilderCard({ builder }: BuilderCardProps) {
  const isHealthy = builder.status === 'healthy';

  return (
    <div className={`rounded-lg border p-3 ${
      isHealthy
        ? 'border-green-500/30 bg-green-500/5'
        : 'border-red-500/30 bg-red-500/5'
    }`}>
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <div className={`w-2 h-2 rounded-full ${isHealthy ? 'bg-green-500' : 'bg-red-500'}`} />
          <span className="font-medium">{builder.name}</span>
        </div>
        <StatusBadge status={builder.status} />
      </div>

      <div className="grid grid-cols-2 gap-2 text-xs">
        <div className="flex items-center gap-1 text-gray-400">
          <Cpu className="w-3 h-3" />
          <span>{builder.model}</span>
        </div>
        <div className="flex items-center gap-1 text-gray-400">
          <Activity className="w-3 h-3" />
          <span>{builder.active_tasks} active</span>
        </div>
        <div className="text-gray-500">
          Type: {builder.type}
        </div>
        <div className="text-gray-500">
          Port: {builder.port}
        </div>
      </div>
    </div>
  );
}
