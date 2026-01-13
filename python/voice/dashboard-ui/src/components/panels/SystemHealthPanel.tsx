import { Activity, Database, Wifi, Settings, CheckCircle, XCircle, MinusCircle, Mic, Server, Hammer } from 'lucide-react';
import { useEventStore } from '../../stores/eventStore';

export function SystemHealthPanel() {
  const health = useEventStore((s) => s.health);
  const wsConnected = useEventStore((s) => s.wsConnected);

  const isOverallHealthy = health?.status === 'healthy';

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center gap-2 p-4 border-b border-white/10">
        <Activity className="w-5 h-5 text-accent" />
        <h2 className="font-semibold">Service Health</h2>
        {health && (
          <span className={`ml-auto text-xs font-medium ${isOverallHealthy ? 'text-green-400' : 'text-yellow-400'}`}>
            {health.status}
          </span>
        )}
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {/* Core Services Section */}
        <h3 className="text-xs font-medium text-gray-400 uppercase mb-2">Core Services</h3>

        {/* Conversator OpenCode (Layer 2 - Subagents) */}
        {health?.components.opencode_orchestration && (
          <HealthItem
            icon={Server}
            label="Conversator: OpenCode"
            status={health.components.opencode_orchestration.status}
            healthy={health.components.opencode_orchestration.status === 'connected'}
            detail={`Port ${health.components.opencode_orchestration.port || 4096} (Subagents)${
              health.components.opencode_orchestration.managed ? ' - managed' : ''
            }`}
          />
        )}

        {/* Gemini Live */}
        {health?.components.gemini_live && (
          <HealthItem
            icon={Mic}
            label="Gemini Live"
            status={health.components.gemini_live.status}
            healthy={health.components.gemini_live.status === 'connected'}
            detail={health.components.gemini_live.model}
          />
        )}

        {/* WebSocket Connection */}
        <HealthItem
          icon={Wifi}
          label="Dashboard WebSocket"
          status={wsConnected ? 'connected' : 'disconnected'}
          healthy={wsConnected}
        />

        {/* Builder Health (Layer 3) */}
        {health?.components.builders && Object.entries(health.components.builders).length > 0 && (
          <div className="mt-4">
            <h3 className="text-xs font-medium text-gray-400 uppercase mb-2">Builders (Layer 3)</h3>
            <div className="space-y-2">
              {Object.entries(health.components.builders).map(([name, status]) => (
                <HealthItem
                  key={name}
                  icon={Hammer}
                  label={name}
                  status={status}
                  healthy={status === 'healthy'}
                />
              ))}
            </div>
          </div>
        )}

        {/* System Section */}
        <div className="mt-4">
          <h3 className="text-xs font-medium text-gray-400 uppercase mb-2">System</h3>

          {/* State Store */}
          {health?.components.state_store && (
            <HealthItem
              icon={Database}
              label="State Store"
              status={health.components.state_store.status}
              healthy={health.components.state_store.status === 'healthy'}
              detail={health.components.state_store.path}
            />
          )}

          {/* Config */}
          {health?.components.config && (
            <HealthItem
              icon={Settings}
              label="Config"
              status={health.components.config.status}
              healthy={health.components.config.status === 'loaded'}
              detail={health.components.config.root_project_dir}
            />
          )}
        </div>

        {!health && (
          <div className="text-center text-gray-500 py-8">
            Loading health data...
          </div>
        )}
      </div>
    </div>
  );
}

interface HealthItemProps {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  status: string;
  healthy: boolean;
  detail?: string;
}

type HealthState = 'healthy' | 'not_started' | 'unhealthy';

function getHealthState(status: string, healthy: boolean): HealthState {
  if (status === 'not_started') return 'not_started';
  if (healthy) return 'healthy';
  return 'unhealthy';
}

function HealthItem({ icon: Icon, label, status, healthy, detail }: HealthItemProps) {
  const state = getHealthState(status, healthy);

  const borderClass = {
    healthy: 'border-green-500/20 bg-green-500/5',
    not_started: 'border-gray-500/20 bg-gray-500/5',
    unhealthy: 'border-red-500/20 bg-red-500/5'
  }[state];

  const iconColor = {
    healthy: 'text-green-400',
    not_started: 'text-gray-400',
    unhealthy: 'text-red-400'
  }[state];

  const StatusIcon = {
    healthy: CheckCircle,
    not_started: MinusCircle,
    unhealthy: XCircle
  }[state];

  return (
    <div className={`rounded-lg border p-3 ${borderClass}`}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Icon className={`w-4 h-4 ${iconColor}`} />
          <span className="font-medium text-sm">{label}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <StatusIcon className={`w-4 h-4 ${iconColor}`} />
          <span className={`text-xs ${iconColor}`}>
            {status === 'not_started' ? 'not started' : status}
          </span>
        </div>
      </div>
      {detail && (
        <div className="text-xs text-gray-500 mt-1 truncate">{detail}</div>
      )}
    </div>
  );
}
