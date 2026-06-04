import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useForm } from "react-hook-form";
import { useMutation } from "@tanstack/react-query";
import { z } from "zod";
import { AlertTriangle, ArrowLeft, CheckCircle2, Eye, EyeOff, KeyRound, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Logo } from "@/components/layout/Logo";
import * as authApi from "@/api/auth.api";
import { parseApiError } from "@/api/client";
import { cn } from "@/lib/utils";

const schema = z
  .object({
    password: z.string().min(8, "Password must be at least 8 characters"),
    confirm: z.string(),
  })
  .refine((d) => d.password === d.confirm, {
    message: "Passwords don't match",
    path: ["confirm"],
  });
type Values = z.infer<typeof schema>;

function strength(pw: string): { score: 0 | 1 | 2 | 3; label: string; tone: string } {
  let s = 0;
  if (pw.length >= 8) s++;
  if (/[A-Z]/.test(pw) && /[a-z]/.test(pw)) s++;
  if (/\d/.test(pw) && /[^A-Za-z0-9]/.test(pw)) s++;
  if (s >= 3) return { score: 3, label: "Strong", tone: "bg-success" };
  if (s === 2) return { score: 2, label: "OK", tone: "bg-warning" };
  if (s === 1) return { score: 1, label: "Weak", tone: "bg-danger" };
  return { score: 0, label: "—", tone: "bg-border" };
}

export default function ResetPasswordPage() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const navigate = useNavigate();
  const [showPw, setShowPw] = useState(false);

  const {
    register,
    handleSubmit,
    watch,
    formState: { errors },
  } = useForm<Values>({ defaultValues: { password: "", confirm: "" } });

  const password = watch("password");
  const meter = strength(password ?? "");

  const mutation = useMutation({
    mutationFn: (v: Values) => authApi.reset({ token, password: v.password }),
  });

  useEffect(() => {
    if (mutation.isSuccess) {
      const t = window.setTimeout(() => navigate("/auth", { replace: true }), 2200);
      return () => window.clearTimeout(t);
    }
  }, [mutation.isSuccess, navigate]);

  return (
    <div className="flex min-h-screen flex-col bg-background p-md">
      <div className="flex flex-1 flex-col items-center justify-center">
        <div className="mb-lg text-center animate-blur-up">
          <Link to="/" className="focus-ring inline-block rounded-lg" aria-label="Lumen home">
            <Logo size="lg" />
          </Link>
          <p className="mt-2 text-body text-text-muted">Pick a new password.</p>
        </div>

        <div className="w-full max-w-[440px] rounded-xl border border-border bg-surface p-xl shadow-card animate-slide-up">
          {!token ? (
            <div className="text-center">
              <div className="mx-auto mb-md flex h-12 w-12 items-center justify-center rounded-full bg-warning/15 text-warning-700">
                <AlertTriangle className="h-6 w-6" />
              </div>
              <h1 className="text-h3 font-h3 text-text-primary">Invalid reset link</h1>
              <p className="mt-2 text-body text-text-muted">
                This password reset link is invalid or has expired. Request a fresh one and we
                will email it to you.
              </p>
              <Button asChild variant="primary" className="mt-md">
                <Link to="/auth/forgot">Request a new link</Link>
              </Button>
            </div>
          ) : mutation.isSuccess ? (
            <div className="text-center">
              <div className="mx-auto mb-md flex h-12 w-12 items-center justify-center rounded-full bg-success/15 text-success">
                <CheckCircle2 className="h-6 w-6" />
              </div>
              <h1 className="text-h3 font-h3 text-text-primary">Password updated</h1>
              <p className="mt-2 text-body text-text-muted">
                Redirecting you to log in…
              </p>
            </div>
          ) : (
            <>
              <div className="mb-md flex h-12 w-12 items-center justify-center rounded-lg bg-primary-tint text-primary">
                <KeyRound className="h-6 w-6" />
              </div>
              <h1 className="text-h3 font-h3 text-text-primary">Set a new password</h1>
              <p className="mt-1 text-body-small text-text-muted">
                Choose something at least 8 characters long. Mix cases, digits, and symbols for a
                stronger score.
              </p>

              <form
                noValidate
                onSubmit={handleSubmit((v) => mutation.mutate(v))}
                className="mt-lg space-y-md"
              >
                {mutation.isError && (
                  <div
                    role="alert"
                    className="rounded-lg border border-danger/30 bg-danger/10 p-3 text-body-small text-danger animate-fade-in"
                  >
                    {parseApiError(mutation.error)}
                  </div>
                )}

                <div className="space-y-1.5">
                  <Label htmlFor="reset-pw">New password</Label>
                  <div className="relative">
                    <Input
                      id="reset-pw"
                      type={showPw ? "text" : "password"}
                      autoComplete="new-password"
                      autoFocus
                      placeholder="At least 8 characters"
                      className="pr-10"
                      aria-invalid={!!errors.password}
                      {...register("password")}
                    />
                    <button
                      type="button"
                      onClick={() => setShowPw((s) => !s)}
                      aria-label={showPw ? "Hide password" : "Show password"}
                      className="absolute right-2 top-1/2 -translate-y-1/2 rounded-md p-1.5 text-text-muted transition-colors hover:bg-surface-soft hover:text-text-primary focus-ring"
                    >
                      {showPw ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                    </button>
                  </div>
                  <div className="flex items-center gap-2">
                    <div className="flex flex-1 gap-1">
                      {[0, 1, 2].map((i) => (
                        <div
                          key={i}
                          className={cn(
                            "h-1 flex-1 rounded-full bg-border transition-colors",
                            i < meter.score && meter.tone,
                          )}
                        />
                      ))}
                    </div>
                    <span className="w-12 text-right text-uppercase-label uppercase text-text-muted">
                      {meter.label}
                    </span>
                  </div>
                  {errors.password && (
                    <p className="text-body-small text-danger">{errors.password.message}</p>
                  )}
                </div>

                <div className="space-y-1.5">
                  <Label htmlFor="reset-confirm">Confirm new password</Label>
                  <Input
                    id="reset-confirm"
                    type={showPw ? "text" : "password"}
                    autoComplete="new-password"
                    placeholder="Repeat the new password"
                    aria-invalid={!!errors.confirm}
                    {...register("confirm")}
                  />
                  {errors.confirm && (
                    <p className="text-body-small text-danger">{errors.confirm.message}</p>
                  )}
                </div>

                <Button
                  type="submit"
                  variant="primary"
                  size="lg"
                  className="w-full"
                  disabled={mutation.isPending}
                >
                  {mutation.isPending ? (
                    <>
                      <Loader2 className="h-4 w-4 animate-spin" /> Updating…
                    </>
                  ) : (
                    "Update password"
                  )}
                </Button>
              </form>

              <div className="mt-md text-center text-body-small text-text-muted">
                <Link
                  to="/auth"
                  className="inline-flex items-center gap-1 font-medium text-primary hover:underline focus-ring rounded"
                >
                  <ArrowLeft className="h-3.5 w-3.5" /> Back to log in
                </Link>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
