import { ChevronLeft, ChevronRight, Calendar as CalendarIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";

export interface YearMonth {
  year: number;
  /** 1–12 */
  month: number;
}

interface MonthPickerProps {
  value: YearMonth;
  onChange: (next: YearMonth) => void;
  /** Latest selectable month — defaults to current. Prevents picking the future. */
  max?: YearMonth;
  /** Earliest selectable month — defaults to 5 years ago. */
  min?: YearMonth;
  className?: string;
}

const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
] as const;

function thisMonth(): YearMonth {
  const d = new Date();
  return { year: d.getFullYear(), month: d.getMonth() + 1 };
}

function add(ym: YearMonth, monthsDelta: number): YearMonth {
  const total = ym.year * 12 + (ym.month - 1) + monthsDelta;
  return { year: Math.floor(total / 12), month: (total % 12) + 1 };
}

function compare(a: YearMonth, b: YearMonth): number {
  return (a.year - b.year) * 12 + (a.month - b.month);
}

export function MonthPicker({ value, onChange, max, min, className }: MonthPickerProps) {
  // `cap` = upper navigation bound (current month by default, but can be
  // pushed into the future by the `max` prop — Planned uses today+5y so
  // the user can browse upcoming bills). `home` = the month the shortcut
  // button jumps to. Earlier these were conflated as one variable and
  // the "Jump to..." button ended up sending users to `max` when max
  // was set — surfaced 2026-06-03 when a user navigated to 2031 in the
  // Planned picker and the shortcut still said "Jump to June 2031".
  const cap = max ?? thisMonth();
  const floor = min ?? add(cap, -60); // 5 years back default
  const home = thisMonth();

  const isAtHome = compare(value, home) === 0;
  const canGoBack = compare(value, floor) > 0;
  const canGoFwd = compare(value, cap) < 0;

  return (
    <div
      className={cn(
        "inline-flex items-center gap-1 rounded-lg border border-border bg-surface p-1 shadow-card",
        className,
      )}
    >
      <Button
        variant="ghost"
        size="icon-sm"
        aria-label="Previous month"
        disabled={!canGoBack}
        onClick={() => canGoBack && onChange(add(value, -1))}
      >
        <ChevronLeft className="h-4 w-4" />
      </Button>

      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size="sm" className="min-w-[140px] gap-2 px-2">
            <CalendarIcon className="h-3.5 w-3.5 text-text-muted" />
            <span className="font-medium text-text-primary">
              {MONTH_NAMES[value.month - 1]} {value.year}
            </span>
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="min-w-[220px]">
          <DropdownMenuLabel className="flex items-center justify-between gap-2 py-1.5">
            <button
              type="button"
              aria-label="Previous year"
              className="rounded p-1 text-text-muted transition-colors hover:bg-surface-soft hover:text-text-primary focus-ring"
              onClick={(e) => {
                e.preventDefault();
                const next = add(value, -12);
                if (compare(next, floor) >= 0) onChange(next);
              }}
            >
              <ChevronLeft className="h-3.5 w-3.5" />
            </button>
            <span className="text-body-small font-semibold text-text-primary">{value.year}</span>
            <button
              type="button"
              aria-label="Next year"
              className="rounded p-1 text-text-muted transition-colors hover:bg-surface-soft hover:text-text-primary focus-ring"
              onClick={(e) => {
                e.preventDefault();
                const next = add(value, 12);
                if (compare(next, cap) <= 0) onChange(next);
              }}
            >
              <ChevronRight className="h-3.5 w-3.5" />
            </button>
          </DropdownMenuLabel>
          <DropdownMenuSeparator />
          <div className="grid grid-cols-3 gap-1 p-1">
            {MONTH_NAMES.map((m, i) => {
              const ym = { year: value.year, month: i + 1 };
              const disabled = compare(ym, floor) < 0 || compare(ym, cap) > 0;
              const isSelected = value.month === i + 1;
              const isToday = compare(ym, home) === 0;
              return (
                <button
                  key={m}
                  type="button"
                  disabled={disabled}
                  onClick={() => onChange(ym)}
                  className={cn(
                    "rounded-md px-2 py-1.5 text-body-small transition-colors focus-ring",
                    disabled && "cursor-not-allowed text-text-muted/40",
                    !disabled && !isSelected && "text-text-muted hover:bg-surface-soft hover:text-text-primary",
                    isSelected && "bg-primary text-on-primary",
                    isToday && !isSelected && "ring-1 ring-primary/30 text-primary",
                  )}
                >
                  {m.slice(0, 3)}
                </button>
              );
            })}
          </div>
          <DropdownMenuSeparator />
          <DropdownMenuItem
            onSelect={() => onChange(home)}
            disabled={isAtHome}
            className="justify-center font-medium"
          >
            Jump to {MONTH_NAMES[home.month - 1]} {home.year}
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      <Button
        variant="ghost"
        size="icon-sm"
        aria-label="Next month"
        disabled={!canGoFwd}
        onClick={() => canGoFwd && onChange(add(value, 1))}
      >
        <ChevronRight className="h-4 w-4" />
      </Button>
    </div>
  );
}

/** Convenient default: current month, used as the initial state of consumers. */
MonthPicker.thisMonth = thisMonth;
