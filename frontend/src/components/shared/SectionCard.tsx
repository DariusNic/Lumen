import { forwardRef, type HTMLAttributes, type ReactNode } from "react";
import { cn } from "@/lib/utils";

interface SectionCardProps extends Omit<HTMLAttributes<HTMLDivElement>, "title"> {
  title?: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  contentClassName?: string;
  noPadding?: boolean;
}

export const SectionCard = forwardRef<HTMLDivElement, SectionCardProps>(
  (
    { title, description, action, children, className, contentClassName, noPadding, ...props },
    ref,
  ) => (
    <section
      ref={ref}
      className={cn(
        "rounded-xl border border-border bg-surface shadow-card",
        "transition-shadow duration-200 hover:shadow-card-hover",
        className,
      )}
      {...props}
    >
      {(title || description || action) && (
        <header className="flex flex-col items-start gap-2 p-lg pb-md sm:flex-row sm:items-start sm:justify-between sm:gap-md">
          <div className="min-w-0">
            {title && (
              <h3 className="text-h4 font-h4 text-text-primary truncate">{title}</h3>
            )}
            {description && (
              <p className="mt-0.5 text-body-small text-text-muted">{description}</p>
            )}
          </div>
          {action && <div className="shrink-0">{action}</div>}
        </header>
      )}
      <div className={cn(noPadding ? "" : "p-lg pt-0", contentClassName)}>{children}</div>
    </section>
  ),
);
SectionCard.displayName = "SectionCard";
