import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { useForm } from "react-hook-form";
import { useMutation } from "@tanstack/react-query";
import { z } from "zod";
import axios from "axios";
import { AlertTriangle, CheckCircle2, Eye, EyeOff, Loader2, Mail } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Logo } from "@/components/layout/Logo";
import { SUPPORTED_CURRENCIES, type Currency } from "@/lib/constants";
import { cn } from "@/lib/utils";
import * as authApi from "@/api/auth.api";
import { parseApiError } from "@/api/client";
import { selectIsAuthenticated, useAuthStore } from "@/store/authStore";

const loginSchema = z.object({
  email: z.string().email("Invalid email"),
  password: z.string().min(8, "Password must be at least 8 characters"),
  remember: z.boolean().optional(),
});
type LoginValues = z.infer<typeof loginSchema>;

const registerSchema = z.object({
  fullName: z.string().min(2, "Tell us your name"),
  email: z.string().email("Invalid email"),
  password: z.string().min(8, "Password must be at least 8 characters"),
  currency: z.enum(SUPPORTED_CURRENCIES),
});
type RegisterValues = z.infer<typeof registerSchema>;

function passwordStrength(pw: string): { score: 0 | 1 | 2 | 3; label: string; tone: string } {
  let s = 0;
  if (pw.length >= 8) s++;
  if (/[A-Z]/.test(pw) && /[a-z]/.test(pw)) s++;
  if (/\d/.test(pw) && /[^A-Za-z0-9]/.test(pw)) s++;
  if (s >= 3) return { score: 3, label: "Strong", tone: "bg-success" };
  if (s === 2) return { score: 2, label: "OK", tone: "bg-warning" };
  if (s === 1) return { score: 1, label: "Weak", tone: "bg-danger" };
  return { score: 0, label: "—", tone: "bg-border" };
}

export default function AuthPage() {
  const [params, setParams] = useSearchParams();
  const initial = params.get("mode") === "register" ? "register" : "login";
  const [tab, setTab] = useState<"login" | "register">(initial);
  const [pendingVerification, setPendingVerification] = useState<{ email: string; fullName: string } | null>(null);

  const navigate = useNavigate();
  const location = useLocation();
  const isAuthenticated = useAuthStore(selectIsAuthenticated);

  // If a logged-in user lands on /auth, bounce them straight to the dashboard.
  useEffect(() => {
    if (isAuthenticated) {
      const from = (location.state as { from?: { pathname?: string } } | null)?.from?.pathname;
      navigate(from ?? "/dashboard", { replace: true });
    }
  }, [isAuthenticated, navigate, location.state]);

  useEffect(() => {
    setParams(
      (p) => {
        const next = new URLSearchParams(p);
        next.set("mode", tab);
        return next;
      },
      { replace: true },
    );
  }, [tab, setParams]);

  return (
    <div className="flex min-h-screen flex-col bg-background p-md">
      <div className="flex flex-1 flex-col items-center justify-center">
        <div className="mb-lg text-center animate-blur-up">
          <Link to="/" className="focus-ring inline-block rounded-lg" aria-label="Lumen home">
            <Logo size="lg" />
          </Link>
          <p className="mt-2 text-body text-text-muted">Clarity for your money.</p>
        </div>

        <div className="w-full max-w-[440px] rounded-xl border border-border bg-surface p-xl shadow-card animate-slide-up">
          {pendingVerification ? (
            <CheckEmailPanel
              email={pendingVerification.email}
              onBack={() => {
                setPendingVerification(null);
                setTab("login");
              }}
            />
          ) : (
            <Tabs value={tab} onValueChange={(v) => setTab(v as typeof tab)}>
              <TabsList className="grid w-full grid-cols-2">
                <TabsTrigger value="login">Log in</TabsTrigger>
                <TabsTrigger value="register">Create account</TabsTrigger>
              </TabsList>
              <TabsContent value="login">
                <LoginForm />
              </TabsContent>
              <TabsContent value="register">
                <RegisterForm
                  onRegistered={(email, fullName) =>
                    setPendingVerification({ email, fullName })
                  }
                />
              </TabsContent>
            </Tabs>
          )}
        </div>

        {!pendingVerification && (
          <p className="mt-md text-center text-body-small text-text-muted">
            {tab === "login"
              ? "New to Lumen? Switch to "
              : "Already have an account? Switch to "}
            <button
              type="button"
              onClick={() => setTab(tab === "login" ? "register" : "login")}
              className="font-medium text-primary hover:underline focus-ring rounded"
            >
              {tab === "login" ? "Create account" : "Log in"}
            </button>{" "}
            above.
          </p>
        )}
      </div>

      <footer className="mt-lg text-center text-uppercase-label uppercase text-text-muted">
        © 2026 Lumen
      </footer>
    </div>
  );
}

function ServerError({ message }: { message: string }) {
  return (
    <div
      role="alert"
      className="flex items-start gap-2 rounded-lg border border-danger/30 bg-danger/10 p-3 text-body-small text-danger animate-fade-in"
    >
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
      <span>{message}</span>
    </div>
  );
}

/**
 * Inline banner shown when login returns EMAIL_NOT_VERIFIED. Lets the
 * user trigger a resend without losing their typed email.
 */
function UnverifiedBanner({ email, message }: { email: string; message: string }) {
  const [sent, setSent] = useState(false);
  const mutation = useMutation({
    mutationFn: () => authApi.resendVerification(email),
    onSuccess: () => setSent(true),
  });
  return (
    <div
      role="alert"
      className="flex items-start gap-2 rounded-lg border border-warning/30 bg-warning/10 p-3 text-body-small text-warning-700 animate-fade-in"
    >
      <Mail className="mt-0.5 h-4 w-4 shrink-0" />
      <div className="min-w-0 flex-1 space-y-1.5">
        <p>{message}</p>
        {sent ? (
          <p className="text-success">
            Sent. Check your inbox (and spam folder) for the new link.
          </p>
        ) : (
          <button
            type="button"
            onClick={() => mutation.mutate()}
            disabled={mutation.isPending}
            className="font-semibold text-primary hover:underline focus-ring rounded disabled:opacity-60"
          >
            {mutation.isPending ? "Sending…" : "Resend verification email →"}
          </button>
        )}
      </div>
    </div>
  );
}

/**
 * Shown after a successful registration. The account exists but is
 * unverified until the user clicks the link in their inbox.
 */
function CheckEmailPanel({ email, onBack }: { email: string; onBack: () => void }) {
  const [resent, setResent] = useState(false);
  const mutation = useMutation({
    mutationFn: () => authApi.resendVerification(email),
    onSuccess: () => setResent(true),
  });
  return (
    <div className="text-center">
      <div className="mx-auto mb-md flex h-12 w-12 items-center justify-center rounded-full bg-primary-tint text-primary">
        <Mail className="h-6 w-6" />
      </div>
      <h1 className="text-h3 font-h3 text-text-primary">Check your email</h1>
      <p className="mt-2 text-body text-text-muted">
        We sent a verification link to{" "}
        <span className="font-semibold text-text-primary">{email}</span>. Click the link in
        the email to activate your account and start using Lumen.
      </p>
      <p className="mt-md text-body-small text-text-muted">
        The link expires in 24 hours. Check your spam folder if you don't see it after a
        minute or two.
      </p>

      {mutation.isError && (
        <p className="mt-md text-body-small text-danger">
          {parseApiError(mutation.error)}
        </p>
      )}
      {resent && (
        <p className="mt-md inline-flex items-center gap-1.5 text-body-small text-success">
          <CheckCircle2 className="h-4 w-4" /> Resent.
        </p>
      )}

      <div className="mt-lg flex flex-col gap-2">
        <Button
          type="button"
          variant="secondary"
          onClick={() => mutation.mutate()}
          disabled={mutation.isPending || resent}
        >
          {mutation.isPending ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" /> Resending…
            </>
          ) : (
            "Resend the email"
          )}
        </Button>
        <Button type="button" variant="ghost" onClick={onBack}>
          Back to log in
        </Button>
      </div>
    </div>
  );
}

function LoginForm() {
  const [showPw, setShowPw] = useState(false);
  const [unverified, setUnverified] = useState<{ email: string; message: string } | null>(null);
  const navigate = useNavigate();
  const location = useLocation();
  const setAuth = useAuthStore((s) => s.setAuth);

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<LoginValues>({
    defaultValues: { email: "", password: "" },
  });

  const mutation = useMutation({
    mutationFn: (values: LoginValues) =>
      authApi.login({ email: values.email, password: values.password }),
    onSuccess: (data) => {
      setUnverified(null);
      setAuth(data);
      const from = (location.state as { from?: { pathname?: string } } | null)?.from?.pathname;
      navigate(from ?? "/dashboard", { replace: true });
    },
    onError: (err) => {
      // 403 EMAIL_NOT_VERIFIED → show the dedicated banner with a
      // resend-link affordance.
      if (axios.isAxiosError(err) && err.response?.status === 403) {
        const data = err.response.data as
          | { error_code?: string; message?: string; details?: { email?: string } }
          | undefined;
        if (data?.error_code === "EMAIL_NOT_VERIFIED" && data.details?.email) {
          setUnverified({
            email: data.details.email,
            message: data.message ?? "Please verify your email address before logging in.",
          });
          return;
        }
      }
      setUnverified(null);
    },
  });

  return (
    <form noValidate onSubmit={handleSubmit((v) => mutation.mutate(v))} className="mt-lg space-y-md">
      {unverified ? (
        <UnverifiedBanner email={unverified.email} message={unverified.message} />
      ) : mutation.isError ? (
        <ServerError message={parseApiError(mutation.error)} />
      ) : null}

      <div className="space-y-1.5">
        <Label htmlFor="login-email">Email</Label>
        <Input
          id="login-email"
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

      <div className="space-y-1.5">
        <Label htmlFor="login-password">Password</Label>
        <div className="relative">
          <Input
            id="login-password"
            type={showPw ? "text" : "password"}
            autoComplete="current-password"
            placeholder="••••••••"
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
        {errors.password && (
          <p className="text-body-small text-danger">{errors.password.message}</p>
        )}
      </div>

      <div className="flex items-center justify-between text-body-small">
        <label className="flex items-center gap-2 text-text-primary">
          <input
            type="checkbox"
            className="h-4 w-4 rounded border-border text-primary focus-ring"
            {...register("remember")}
          />
          <span>Remember me</span>
        </label>
        <Link
          to="/auth/forgot"
          className="font-medium text-primary hover:underline focus-ring rounded"
        >
          Forgot password?
        </Link>
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
            <Loader2 className="h-4 w-4 animate-spin" /> Signing in…
          </>
        ) : (
          "Log in"
        )}
      </Button>
    </form>
  );
}

function RegisterForm({
  onRegistered,
}: {
  onRegistered: (email: string, fullName: string) => void;
}) {
  const [showPw, setShowPw] = useState(false);

  const {
    register,
    handleSubmit,
    watch,
    setValue,
    formState: { errors },
  } = useForm<RegisterValues>({
    defaultValues: { fullName: "", email: "", password: "", currency: "RON" },
  });

  const password = watch("password");
  const currency = watch("currency");
  const strength = passwordStrength(password ?? "");

  const mutation = useMutation({
    mutationFn: (values: RegisterValues) =>
      authApi.register({
        full_name: values.fullName,
        email: values.email,
        password: values.password,
        base_currency: values.currency,
      }),
    onSuccess: (data, variables) => {
      onRegistered(data.user.email, variables.fullName);
    },
  });

  return (
    <form noValidate onSubmit={handleSubmit((v) => mutation.mutate(v))} className="mt-lg space-y-md">
      {mutation.isError && <ServerError message={parseApiError(mutation.error)} />}

      <div className="space-y-1.5">
        <Label htmlFor="reg-name">Full name</Label>
        <Input
          id="reg-name"
          autoComplete="name"
          placeholder="Ana Popescu"
          aria-invalid={!!errors.fullName}
          {...register("fullName")}
        />
        {errors.fullName && (
          <p className="text-body-small text-danger">{errors.fullName.message}</p>
        )}
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="reg-email">Email</Label>
        <Input
          id="reg-email"
          type="email"
          autoComplete="email"
          placeholder="you@example.com"
          aria-invalid={!!errors.email}
          {...register("email")}
        />
        {errors.email && (
          <p className="text-body-small text-danger">{errors.email.message}</p>
        )}
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="reg-password">Password</Label>
        <div className="relative">
          <Input
            id="reg-password"
            type={showPw ? "text" : "password"}
            autoComplete="new-password"
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
                  i < strength.score && strength.tone,
                )}
              />
            ))}
          </div>
          <span className="w-12 text-right text-uppercase-label uppercase text-text-muted">
            {strength.label}
          </span>
        </div>
        {errors.password && (
          <p className="text-body-small text-danger">{errors.password.message}</p>
        )}
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="reg-currency">Default currency</Label>
        <div className="grid grid-cols-3 gap-2">
          {SUPPORTED_CURRENCIES.map((c) => (
            <button
              type="button"
              key={c}
              onClick={() => setValue("currency", c as Currency)}
              className={cn(
                "rounded-lg border px-3 py-2 text-body-small font-medium transition-all focus-ring",
                currency === c
                  ? "border-primary bg-primary-tint text-primary"
                  : "border-border bg-surface text-text-muted hover:border-outline hover:text-text-primary",
              )}
            >
              {c}
            </button>
          ))}
        </div>
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
            <Loader2 className="h-4 w-4 animate-spin" /> Creating account…
          </>
        ) : (
          "Create my account"
        )}
      </Button>
    </form>
  );
}
