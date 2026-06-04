import { Link } from "react-router-dom";
import { useForm } from "react-hook-form";
import { useMutation } from "@tanstack/react-query";
import { z } from "zod";
import { ArrowLeft, CheckCircle2, Loader2, Mail } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Logo } from "@/components/layout/Logo";
import * as authApi from "@/api/auth.api";
import { parseApiError } from "@/api/client";

const schema = z.object({
  email: z.string().email("Invalid email"),
});
type Values = z.infer<typeof schema>;

export default function ForgotPasswordPage() {
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<Values>({ defaultValues: { email: "" } });

  const mutation = useMutation({
    mutationFn: (v: Values) => authApi.forgot({ email: v.email }),
  });

  return (
    <div className="flex min-h-screen flex-col bg-background p-md">
      <div className="flex flex-1 flex-col items-center justify-center">
        <div className="mb-lg text-center animate-blur-up">
          <Link to="/" className="focus-ring inline-block rounded-lg" aria-label="Lumen home">
            <Logo size="lg" />
          </Link>
          <p className="mt-2 text-body text-text-muted">Reset your password.</p>
        </div>

        <div className="w-full max-w-[440px] rounded-xl border border-border bg-surface p-xl shadow-card animate-slide-up">
          {mutation.isSuccess ? (
            <div className="text-center">
              <div className="mx-auto mb-md flex h-12 w-12 items-center justify-center rounded-full bg-success/15 text-success">
                <CheckCircle2 className="h-6 w-6" />
              </div>
              <h1 className="text-h3 font-h3 text-text-primary">Check your inbox</h1>
              <p className="mt-2 text-body text-text-muted">
                If an account exists for that email, we sent a link to reset your password. The
                link is valid for one hour.
              </p>
              <Button asChild variant="ghost" className="mt-md">
                <Link to="/auth">
                  <ArrowLeft className="h-4 w-4" /> Back to log in
                </Link>
              </Button>
            </div>
          ) : (
            <>
              <div className="mb-md flex h-12 w-12 items-center justify-center rounded-lg bg-primary-tint text-primary">
                <Mail className="h-6 w-6" />
              </div>
              <h1 className="text-h3 font-h3 text-text-primary">Forgot your password?</h1>
              <p className="mt-1 text-body-small text-text-muted">
                Enter the email tied to your Lumen account. We&apos;ll send a one-time link to set
                a new password.
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
                  <Label htmlFor="forgot-email">Email</Label>
                  <Input
                    id="forgot-email"
                    type="email"
                    autoComplete="email"
                    autoFocus
                    placeholder="you@example.com"
                    aria-invalid={!!errors.email}
                    {...register("email")}
                  />
                  {errors.email && (
                    <p className="text-body-small text-danger">{errors.email.message}</p>
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
                      <Loader2 className="h-4 w-4 animate-spin" /> Sending…
                    </>
                  ) : (
                    "Send reset link"
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

        <p className="mt-md max-w-[440px] text-center text-uppercase-label uppercase text-text-muted">
          If you don&apos;t receive an email within a few minutes, check your spam folder or get in
          touch with support.
        </p>
      </div>
    </div>
  );
}
