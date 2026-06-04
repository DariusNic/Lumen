import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Flag,
  GraduationCap,
  Home,
  Loader2,
  MoreHorizontal,
  Plane,
  Plus,
  ShieldCheck,
  Sparkles,
  Trash2,
  type LucideIcon,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { SectionCard } from "@/components/shared/SectionCard";
import { EmptyState } from "@/components/shared/EmptyState";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { GoalFormDialog } from "@/components/goals/GoalFormDialog";
import { GoalAmountDisplay } from "@/components/goals/GoalAmountDisplay";
import { ContributeDialog } from "@/components/goals/ContributeDialog";
import { qk } from "@/lib/queryKeys";
import { formatMoney } from "@/lib/format";
import { parseApiError } from "@/api/client";
import * as goalsApi from "@/api/goals.api";
import { useCurrency } from "@/hooks/useCurrency";
import { useFxRate } from "@/hooks/useFxRate";
import { cn } from "@/lib/utils";

const TYPE_ICON: Record<goalsApi.GoalType, LucideIcon> = {
  travel: Plane,
  home: Home,
  emergency: ShieldCheck,
  education: GraduationCap,
  vehicle: Sparkles,
  other: Flag,
};

const STATUS_PILL: Record<goalsApi.GoalStatus, { label: string; tone: string }> = {
  "on-track": { label: "On track", tone: "bg-success/15 text-success" },
  ahead: { label: "Ahead", tone: "bg-success/15 text-success" },
  behind: { label: "Behind schedule", tone: "bg-warning/15 text-warning-700" },
  completed: { label: "Completed", tone: "bg-text-muted/15 text-text-muted" },
};

export default function GoalsPage() {
  const qc = useQueryClient();
  const goalsQuery = useQuery({ queryKey: qk.goals.all(), queryFn: goalsApi.listGoals });

  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<goalsApi.Goal | null>(null);
  const [contributing, setContributing] = useState<goalsApi.Goal | null>(null);
  const [deleteCandidate, setDeleteCandidate] = useState<goalsApi.Goal | null>(null);

  const deleteMutation = useMutation({
    mutationFn: (id: string) => goalsApi.deleteGoal(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.goals.all() });
      // Backend `_close_linked_recurring` soft-deletes any auto-contribute
      // recurring payment tied to this goal, so /planned must refetch too
      // — otherwise the orphan entry lingers in the UI until next page load.
      qc.invalidateQueries({ queryKey: qk.recurring.all() });
      setDeleteCandidate(null);
    },
  });

  const goals = goalsQuery.data ?? [];
  const active = goals.filter((g) => g.status !== "completed");
  const completed = goals.filter((g) => g.status === "completed");
  // Completed goals sink to the bottom of the grid so the user always sees
  // ongoing work first. Order within each bucket is preserved (API default).
  const sortedGoals = [...active, ...completed];

  if (goalsQuery.isLoading) {
    return (
      <div className="flex items-center justify-center gap-2 py-2xl text-body-small text-text-muted">
        <Loader2 className="h-4 w-4 animate-spin" /> Loading goals…
      </div>
    );
  }

  if (goalsQuery.isError) {
    return (
      <SectionCard title="Goals">
        <p className="text-body-small text-danger">{parseApiError(goalsQuery.error)}</p>
      </SectionCard>
    );
  }

  if (goals.length === 0) {
    return (
      <>
        <EmptyState
          icon={Flag}
          title="You don't have any goals yet"
          description="A goal is a target amount, a deadline, and a monthly plan. We'll do the math for you and tell you exactly how much to put aside each month."
          action={
            <Button
              variant="primary"
              onClick={() => {
                setEditing(null);
                setFormOpen(true);
              }}
            >
              <Plus className="h-4 w-4" /> Create your first goal
            </Button>
          }
        />
        <GoalFormDialog
          open={formOpen}
          onOpenChange={(o) => {
            setFormOpen(o);
            if (!o) setEditing(null);
          }}
          editing={editing}
        />
      </>
    );
  }

  return (
    <div className="space-y-lg animate-fade-in">
      <header className="flex flex-wrap items-center justify-between gap-md">
        <div>
          <h1 className="text-h2 font-h2 text-text-primary">Goals</h1>
          <p className="text-body-small text-text-muted">
            {active.length} active · {completed.length} completed
          </p>
        </div>
        <Button
          variant="primary"
          onClick={() => {
            setEditing(null);
            setFormOpen(true);
          }}
        >
          <Plus className="h-4 w-4" /> Create a goal
        </Button>
      </header>

      <div className="grid gap-md sm:grid-cols-2 lg:grid-cols-3">
        {sortedGoals.map((g) => (
          <GoalCard
            key={g.id}
            goal={g}
            onEdit={() => {
              setEditing(g);
              setFormOpen(true);
            }}
            onContribute={() => setContributing(g)}
            onDelete={() => setDeleteCandidate(g)}
          />
        ))}
      </div>

      <GoalFormDialog
        open={formOpen}
        onOpenChange={(o) => {
          setFormOpen(o);
          if (!o) setEditing(null);
        }}
        editing={editing}
      />

      <ContributeDialog
        open={!!contributing}
        onOpenChange={(o) => !o && setContributing(null)}
        goal={contributing}
      />

      <ConfirmDelete
        candidate={deleteCandidate}
        onClose={() => setDeleteCandidate(null)}
        onConfirm={(id) => deleteMutation.mutate(id)}
        isPending={deleteMutation.isPending}
      />
    </div>
  );
}

function GoalCard({
  goal,
  onEdit,
  onContribute,
  onDelete,
}: {
  goal: goalsApi.Goal;
  onEdit: () => void;
  onContribute: () => void;
  onDelete: () => void;
}) {
  const Icon = TYPE_ICON[goal.type];
  const statusMeta = STATUS_PILL[goal.status];
  const isCompleted = goal.status === "completed";
  // Overdue goal: deadline has passed but balance isn't met. The monthly
  // contribution row reads "€0/mo" once months_remaining is zero, so swap
  // it for a one-line nudge instead.
  const isOverdue = !isCompleted && goal.months_remaining <= 0;
  const remaining = Math.max(0, goal.target_amount - goal.saved_amount);

  // When the user's base currency differs from the goal's native currency,
  // we convert monthly/auto/remaining amounts to base so the card stays in
  // sync with the currency switcher (same pattern as GoalAmountDisplay).
  // While the FX rate is still loading we fall back to native to avoid a
  // mid-conversion flash.
  const baseCurrency = useCurrency();
  const rate = useFxRate(goal.currency, baseCurrency);
  const sameCurrency = goal.currency === baseCurrency;
  const convert = (amount: number): { value: number; currency: goalsApi.Goal["currency"] } =>
    sameCurrency || rate == null
      ? { value: amount, currency: goal.currency }
      : { value: amount * rate, currency: baseCurrency };
  const monthly = convert(goal.monthly_simple);
  const remainingDisplay = convert(remaining);

  return (
    <SectionCard
      className={cn(
        "group transition-all hover:-translate-y-0.5 hover:border-primary/30",
        isCompleted && "opacity-75 saturate-50",
      )}
      noPadding
    >
      <div className="flex items-center justify-between p-md">
        <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary-tint text-primary transition-transform group-hover:scale-110">
          <Icon className="h-5 w-5" />
        </span>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon-sm" aria-label="Goal options">
              <MoreHorizontal className="h-4 w-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onSelect={onEdit} disabled={isCompleted}>
              Edit
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              onSelect={onDelete}
              className="text-danger focus:bg-danger/10 focus:text-danger"
            >
              <Trash2 className="h-3.5 w-3.5" /> Delete
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      <div className="px-md">
        <div className="flex items-start justify-between gap-2">
          <h3 className="line-clamp-2 min-w-0 text-h3 font-h3 leading-snug" title={goal.name}>
            {goal.name}
          </h3>
          {isCompleted && (
            <span className="shrink-0 rounded-full bg-success/15 px-2 py-0.5 text-uppercase-label uppercase text-success">
              ✓ Done
            </span>
          )}
        </div>
        <p className="mt-0.5 text-body-small text-text-muted">
          by{" "}
          {new Date(goal.target_date).toLocaleDateString("en-US", {
            month: "long",
            year: "numeric",
          })}
        </p>
      </div>

      <div className="my-3 flex justify-center">
        <BigRing pct={goal.progress_pct} />
      </div>

      <div className="px-md text-center text-body-small">
        <GoalAmountDisplay goal={goal} className="font-medium" />
        {goal.auto_contribute && (() => {
          const auto = convert(goal.auto_contribute.amount);
          return (
            <div className="mt-1 inline-flex items-center gap-1 rounded-full bg-primary-tint px-2 py-0.5 text-uppercase-label uppercase text-primary">
              ⟳ Auto · {formatMoney(auto.value, auto.currency, { maximumFractionDigits: 0 })}/mo
            </div>
          );
        })()}
        <span
          className={cn(
            "mt-1 inline-block rounded-full px-2 py-0.5 text-uppercase-label uppercase",
            statusMeta.tone,
          )}
        >
          {statusMeta.label}
        </span>
      </div>

      {!isCompleted && (
        isOverdue ? (
          <div className="mt-md border-t border-border bg-warning/10 px-md py-3 text-center">
            <div className="text-uppercase-label uppercase text-warning-700">Deadline passed</div>
            <div className="mt-0.5 text-body-small text-text-primary">
              {formatMoney(remainingDisplay.value, remainingDisplay.currency, { maximumFractionDigits: 0 })} left.
              Adjust the target date or contribute the remainder.
            </div>
          </div>
        ) : (
          <div className="mt-md border-t border-border bg-surface-soft px-md py-3 text-center">
            <div className="text-uppercase-label uppercase text-text-muted">Monthly contribution</div>
            <div className="mt-0.5 text-body-small font-semibold tabular text-primary">
              {formatMoney(monthly.value, monthly.currency, { maximumFractionDigits: 0 })}
              /mo
            </div>
          </div>
        )
      )}

      <div className="border-t border-border p-md">
        <Button
          variant={isCompleted ? "ghost" : "outline"}
          className="w-full"
          onClick={onContribute}
          disabled={isCompleted}
        >
          {isCompleted ? "Goal completed" : "Contribute"}
        </Button>
      </div>
    </SectionCard>
  );
}

function BigRing({ pct }: { pct: number }) {
  const r = 56;
  const c = 2 * Math.PI * r;
  const offset = c - (Math.min(100, pct) / 100) * c;
  return (
    <div className="relative h-[140px] w-[140px]">
      <svg viewBox="0 0 140 140" className="h-full w-full -rotate-90">
        <circle cx="70" cy="70" r={r} fill="none" stroke="rgb(var(--surface-variant))" strokeWidth="12" />
        <circle
          cx="70"
          cy="70"
          r={r}
          fill="none"
          stroke="rgb(79 70 229)"
          strokeWidth="12"
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={offset}
          className="transition-all duration-700 ease-out"
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-h2 font-h2 tabular leading-none">{Math.round(pct)}%</span>
      </div>
    </div>
  );
}

function ConfirmDelete({
  candidate,
  onClose,
  onConfirm,
  isPending,
}: {
  candidate: goalsApi.Goal | null;
  onClose: () => void;
  onConfirm: (id: string) => void;
  isPending: boolean;
}) {
  return (
    <Dialog open={!!candidate} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Delete this goal?</DialogTitle>
          <DialogDescription>
            The goal disappears from your list immediately. Past contributions are kept in your
            history so any reports stay accurate.
          </DialogDescription>
        </DialogHeader>
        {candidate && (
          <div className="rounded-lg border border-border bg-surface-soft p-3 text-body-small">
            <div className="font-medium text-text-primary">{candidate.name}</div>
            <div className="text-text-muted tabular">
              {formatMoney(candidate.saved_amount, candidate.currency)} saved of{" "}
              {formatMoney(candidate.target_amount, candidate.currency)}
            </div>
          </div>
        )}
        <DialogFooter>
          <Button variant="ghost" onClick={onClose} disabled={isPending}>
            Cancel
          </Button>
          <Button
            variant="danger"
            onClick={() => candidate && onConfirm(candidate.id)}
            disabled={isPending}
          >
            {isPending ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" /> Deleting…
              </>
            ) : (
              <>
                <Trash2 className="h-4 w-4" /> Delete
              </>
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
