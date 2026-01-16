interface ThinkingIndicatorProps {
  className?: string;
}

export function ThinkingIndicator({ className = '' }: ThinkingIndicatorProps) {
  return (
    <div className={`flex items-center gap-2 text-yellow-400 ${className}`}>
      <div className="flex gap-1">
        <span
          className="w-2 h-2 bg-yellow-400 rounded-full animate-bounce"
          style={{ animationDelay: '0ms' }}
        />
        <span
          className="w-2 h-2 bg-yellow-400 rounded-full animate-bounce"
          style={{ animationDelay: '150ms' }}
        />
        <span
          className="w-2 h-2 bg-yellow-400 rounded-full animate-bounce"
          style={{ animationDelay: '300ms' }}
        />
      </div>
      <span className="text-sm">Thinking...</span>
    </div>
  );
}
