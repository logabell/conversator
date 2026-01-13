interface StatusBadgeProps {
  status: string;
  size?: 'sm' | 'md';
}

const statusColors: Record<string, string> = {
  // Task statuses
  pending: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
  planning: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
  executing: 'bg-purple-500/20 text-purple-400 border-purple-500/30',
  done: 'bg-green-500/20 text-green-400 border-green-500/30',
  failed: 'bg-red-500/20 text-red-400 border-red-500/30',
  canceled: 'bg-gray-500/20 text-gray-400 border-gray-500/30',

  // Builder statuses
  healthy: 'bg-green-500/20 text-green-400 border-green-500/30',
  unreachable: 'bg-red-500/20 text-red-400 border-red-500/30',
  error: 'bg-red-500/20 text-red-400 border-red-500/30',
  unknown: 'bg-gray-500/20 text-gray-400 border-gray-500/30',

  // Severity levels
  info: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
  success: 'bg-green-500/20 text-green-400 border-green-500/30',
  warning: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
  blocking: 'bg-red-500/20 text-red-400 border-red-500/30'
};

export function StatusBadge({ status, size = 'sm' }: StatusBadgeProps) {
  const colors = statusColors[status.toLowerCase()] || statusColors.unknown;
  const sizeClasses = size === 'sm' ? 'text-xs px-2 py-0.5' : 'text-sm px-3 py-1';

  return (
    <span className={`inline-flex items-center rounded-full border font-medium ${colors} ${sizeClasses}`}>
      {status}
    </span>
  );
}
