import { cn } from "@/lib/utils";

interface LogoProps {
  className?: string;
  showWordmark?: boolean;
  size?: "sm" | "md" | "lg";
}

const sizeMap = {
  sm: { mark: "h-7 w-7", text: "text-body" },
  md: { mark: "h-8 w-8", text: "text-body-large" },
  lg: { mark: "h-10 w-10", text: "text-h4" },
};

export function Logo({ className, showWordmark = true, size = "md" }: LogoProps) {
  const s = sizeMap[size];
  return (
    <div className={cn("flex items-center gap-2", className)}>
      <div
        className={cn(
          "relative flex shrink-0 items-center justify-center rounded-lg bg-primary text-on-primary shadow-card",
          s.mark,
        )}
        aria-hidden="true"
      >
        <svg viewBox="0 0 24 24" fill="none" className="h-3/5 w-3/5">
          <path
            d="M12 2.5a9.5 9.5 0 1 0 9.5 9.5"
            stroke="currentColor"
            strokeWidth="2.4"
            strokeLinecap="round"
          />
          <circle cx="17.5" cy="6.5" r="2.2" fill="currentColor" />
        </svg>
      </div>
      {showWordmark ? (
        <span className={cn("font-semibold tracking-tight text-text-primary", s.text)}>
          Lumen
        </span>
      ) : null}
    </div>
  );
}
